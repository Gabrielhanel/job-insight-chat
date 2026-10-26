"""Sessões de análise (Etapa 7): histórico persistente no SQLite.

Uma sessão agrupa, em ordem cronológica, as análises que o usuário fez (busca por cargo, busca por habilidades, evolução por
senioridade, comparação de vagas). Cada interação guarda o tipo, a consulta, os parâmetros e o RESULTADO ESTRUTURADO que a
interface exibiu (inclusive os dados dos gráficos), para reabrir tudo sem nova chamada externa e sem gastar cota.

- O servidor grava o resultado que ele mesmo calculou (a rota recebe `sessao_id`); o navegador não envia resultados.
- `uid` (id do evento, gerado no navegador) torna a gravação idempotente: o mesmo evento repetido devolve o mesmo registro.
- O id da sessão é aleatório e independe do título; renomear não muda nenhuma relação.
- Nada de chaves/segredos: valores de variáveis de ambiente sensíveis são removidos do JSON antes de gravar.
"""
import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from app import db, insights, skills

log = logging.getLogger("vagas")

TIPOS = ("chat", "habilidades", "evolucao", "comparar")
TITULO_PADRAO = "Nova conversa"
MAX_TITULO = 80
MAX_CONSULTA = 500
MAX_INTERACOES = 200            # por sessão: acima disso o usuário deve abrir uma nova conversa
MAX_RESULTADO_BYTES = 1_500_000  # resultado maior que isso não é guardado (a interação fica registrada, sem o resultado)
MAX_LISTA = 100
MAX_IMPORTAR = 50
_ID = re.compile(r"^[0-9a-f]{32}$")
_UID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_SEGREDOS = ("OPENWEBNINJA_API_KEY", "RAPIDAPI_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "ANTHROPIC_API_KEY", "CHAVE_OPENROUTER")


class ErroSessao(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def validar_id(sessao_id) -> str:
    if not isinstance(sessao_id, str) or not _ID.fullmatch(sessao_id):
        raise ErroSessao(422, "Identificador de sessão inválido.")
    return sessao_id


def validar_uid(uid) -> str | None:
    if uid is None:
        return None
    if not isinstance(uid, str) or not _UID.fullmatch(uid):
        raise ErroSessao(422, "Identificador da interação inválido (use de 8 a 64 caracteres: letras, números, _ ou -).")
    return uid


def _titulo_de(texto: str) -> str:
    t = skills.limpar(texto or "")
    if not t:
        return TITULO_PADRAO
    return t if len(t) <= MAX_TITULO else t[: MAX_TITULO - 1].rstrip() + "…"


def _sessao(linha) -> dict:
    return {"id": linha[0], "titulo": linha[1], "titulo_manual": bool(linha[2]), "criada_em": linha[3], "atualizada_em": linha[4]}


def _existe(sessao_id: str) -> tuple:
    linhas = db.consultar("SELECT id, titulo, titulo_manual, criada_em, atualizada_em FROM sessoes WHERE id=?", (sessao_id,))
    if not linhas:
        raise ErroSessao(404, "Sessão não encontrada. Ela pode ter sido excluída.")
    return linhas[0]


def _falha(e: sqlite3.Error, acao: str):
    log.error("Falha de persistência (%s): %s", acao, type(e).__name__)  # sem dados do usuário no log
    raise ErroSessao(500, f"Não foi possível {acao}. Nada foi alterado; tente novamente.")


# ---------------------------------------------------------------- sessões
def criar(titulo: str | None = None) -> dict:
    sid, agora = uuid.uuid4().hex, _agora()
    manual = 1 if titulo and skills.limpar(titulo) else 0
    try:
        with db.transacao() as c:
            c.execute("INSERT INTO sessoes (id, titulo, titulo_manual, criada_em, atualizada_em) VALUES (?, ?, ?, ?, ?)",
                      (sid, _titulo_de(titulo) if manual else TITULO_PADRAO, manual, agora, agora))
    except sqlite3.Error as e:
        _falha(e, "criar a sessão")
    return {**_sessao((sid, _titulo_de(titulo) if manual else TITULO_PADRAO, manual, agora, agora)), "total_interacoes": 0}


def listar(limite: int = MAX_LISTA) -> list[dict]:
    """Lista leve (sem resultados nem descrições), da atividade mais recente para a mais antiga."""
    limite = max(1, min(int(limite), MAX_LISTA))
    try:
        linhas = db.consultar(
            "SELECT s.id, s.titulo, s.titulo_manual, s.criada_em, s.atualizada_em, "
            "(SELECT COUNT(*) FROM interacoes i WHERE i.sessao_id = s.id), "
            "(SELECT i.tipo FROM interacoes i WHERE i.sessao_id = s.id ORDER BY i.seq DESC LIMIT 1), "
            "(SELECT i.resumo FROM interacoes i WHERE i.sessao_id = s.id ORDER BY i.seq DESC LIMIT 1) "
            "FROM sessoes s ORDER BY s.atualizada_em DESC, s.rowid DESC LIMIT ?", (limite,))
    except sqlite3.Error as e:
        _falha(e, "carregar o histórico")
    return [{**_sessao(l[:5]), "total_interacoes": l[5], "ultimo_tipo": l[6], "ultimo_resumo": l[7] or ""} for l in linhas]


def _interacao(l, com_resultado: bool) -> dict:
    out = {"id": l[0], "seq": l[1], "tipo": l[2], "consulta": l[3], "parametros": None, "status": l[6], "resumo": l[7], "criada_em": l[8],
           "resultado": None, "resultado_disponivel": l[5] is not None}
    try:
        out["parametros"] = json.loads(l[4])
    except ValueError:
        out["parametros"] = None
    if com_resultado and l[5] is not None:
        try:
            out["resultado"] = json.loads(l[5])
            out["insights"] = insights.gerar(l[2], out["resultado"])  # calculado na leitura, nunca persistido
        except ValueError:  # registro corrompido: o resto da sessão continua utilizável
            out["resultado_disponivel"] = False
            out["aviso"] = "Este resultado salvo não pôde ser reconstruído."
    if l[5] is None:
        out["aviso"] = "O resultado desta análise não foi guardado (era grande demais); a consulta foi registrada."
    return out


_COLS = "id, seq, tipo, consulta, parametros, resultado, status, resumo, criada_em"


def obter(sessao_id: str) -> dict:
    """Sessão com todas as interações em ordem cronológica e seus resultados salvos (nenhuma chamada externa)."""
    sid = validar_id(sessao_id)
    s = _existe(sid)
    try:
        linhas = db.consultar(f"SELECT {_COLS} FROM interacoes WHERE sessao_id=? ORDER BY seq", (sid,))
    except sqlite3.Error as e:
        _falha(e, "carregar a sessão")
    return {"sessao": {**_sessao(s), "total_interacoes": len(linhas)}, "interacoes": [_interacao(l, True) for l in linhas]}


def garantir(sessao_id: str) -> dict:
    """Valida o id e confirma que a sessão existe."""
    return _sessao(_existe(validar_id(sessao_id)))


def renomear(sessao_id: str, titulo: str) -> dict:
    sid = validar_id(sessao_id)
    novo = skills.limpar(titulo or "")
    if not novo:
        raise ErroSessao(422, "Informe um título para a sessão.")
    if len(novo) > MAX_TITULO:
        raise ErroSessao(422, f"O título pode ter no máximo {MAX_TITULO} caracteres (atual: {len(novo)}).")
    _existe(sid)
    try:
        with db.transacao() as c:
            c.execute("UPDATE sessoes SET titulo=?, titulo_manual=1 WHERE id=?", (novo, sid))  # só o rótulo muda; id e relações não
    except sqlite3.Error as e:
        _falha(e, "renomear a sessão")
    return {**_sessao(_existe(sid))}


def excluir(sessao_id: str) -> dict:
    """Remove a sessão e as suas interações. Cache de páginas, cota, perfil e histórico de vagas não são tocados."""
    sid = validar_id(sessao_id)
    _existe(sid)
    try:
        with db.transacao() as c:
            c.execute("DELETE FROM interacoes WHERE sessao_id=?", (sid,))
            c.execute("DELETE FROM sessoes WHERE id=?", (sid,))
    except sqlite3.Error as e:
        _falha(e, "excluir a sessão")
    return {"removida": sid}


# ---------------------------------------------------------------- interações
def _limpar_segredos(texto: str) -> str:
    for nome in _SEGREDOS:
        v = os.getenv(nome)
        if v and len(v) >= 8:
            texto = texto.replace(v, "[removido]")
    return texto


def descrever(tipo: str, parametros: dict, resultado: dict) -> tuple[str, str, str]:
    """(consulta curta, resumo, status) a partir do que a própria análise devolveu."""
    p, r = parametros or {}, resultado or {}
    status = r.get("estado") if isinstance(r.get("estado"), str) else "ok"
    if tipo == "chat":
        d = r.get("dados") or {}
        return p.get("mensagem") or d.get("cargo") or "", f"{d.get('vagas_analisadas', 0)} vagas analisadas", status
    if tipo == "habilidades":
        c = r.get("contagens") or {}
        return ", ".join(r.get("habilidades") or p.get("habilidades") or []), f"{c.get('unicas', 0)} vagas · {c.get('avaliadas', 0)} avaliadas", status
    if tipo == "evolucao":
        c = r.get("contagens") or {}
        return r.get("cargo") or p.get("cargo") or "", f"{c.get('unicas', 0)} vagas · {c.get('analisadas', 0)} analisadas", status
    tit = lambda x: ((x or {}).get("identidade") or {}).get("titulo") or "(vaga sem título)"
    return f"{tit(r.get('a'))} × {tit(r.get('b'))}", "comparação completa" if status == "completa" else "comparação parcial", status


def interacao_por_uid(sessao_id: str, uid: str | None) -> dict | None:
    if not uid:
        return None
    sid = validar_id(sessao_id)
    linhas = db.consultar(f"SELECT {_COLS} FROM interacoes WHERE sessao_id=? AND uid=?", (sid, validar_uid(uid)))
    return _interacao(linhas[0], True) if linhas else None


def registrar(sessao_id: str, tipo: str, parametros: dict, resultado: dict, uid: str | None = None) -> dict:
    """Grava a interação numa transação (seq, interação e atividade da sessão juntos). Idempotente por `uid`."""
    sid, uid = validar_id(sessao_id), validar_uid(uid)
    if tipo not in TIPOS:
        raise ErroSessao(422, "Tipo de análise inválido.")
    _existe(sid)
    consulta, resumo, status = descrever(tipo, parametros, resultado)
    consulta = skills.limpar(consulta)[:MAX_CONSULTA]
    texto_res = _limpar_segredos(json.dumps(resultado, ensure_ascii=False, separators=(",", ":"), default=str))
    guardar = len(texto_res.encode("utf-8")) <= MAX_RESULTADO_BYTES
    texto_par = _limpar_segredos(json.dumps(parametros, ensure_ascii=False, separators=(",", ":"), default=str))
    agora = _agora()
    try:
        with db.transacao() as c:
            if uid:
                ja = c.execute(f"SELECT {_COLS} FROM interacoes WHERE sessao_id=? AND uid=?", (sid, uid)).fetchone()
                if ja:
                    return {**_meta(ja, sid), "repetida": True}
            n, = c.execute("SELECT COUNT(*) FROM interacoes WHERE sessao_id=?", (sid,)).fetchone()
            if n >= MAX_INTERACOES:
                raise ErroSessao(409, f"Esta sessão atingiu o limite de {MAX_INTERACOES} análises. Abra uma nova conversa para continuar salvando.")
            seq, = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM interacoes WHERE sessao_id=?", (sid,)).fetchone()
            cur = c.execute(
                "INSERT INTO interacoes (sessao_id, seq, uid, tipo, consulta, parametros, resultado, status, resumo, criada_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, seq, uid, tipo, consulta, texto_par, texto_res if guardar else None, status, resumo, agora))
            c.execute("UPDATE sessoes SET atualizada_em=? WHERE id=?", (agora, sid))
            if n == 0:  # 1ª análise: o título vem da consulta (sem IA), a menos que a pessoa já tenha dado um título
                c.execute("UPDATE sessoes SET titulo=? WHERE id=? AND titulo_manual=0", (_titulo_de(consulta), sid))
            titulo_atual, = c.execute("SELECT titulo FROM sessoes WHERE id=?", (sid,)).fetchone()
            return {"id": cur.lastrowid, "sessao_id": sid, "seq": seq, "tipo": tipo, "consulta": consulta, "status": status, "resumo": resumo,
                    "criada_em": agora, "resultado_guardado": guardar, "repetida": False, "titulo_sessao": titulo_atual}
    except sqlite3.Error as e:
        _falha(e, "salvar a análise no histórico")


def _meta(l, sid: str) -> dict:
    return {"id": l[0], "sessao_id": sid, "seq": l[1], "tipo": l[2], "consulta": l[3], "status": l[6], "resumo": l[7], "criada_em": l[8],
            "resultado_guardado": l[5] is not None}


def importar_legado(itens: list) -> dict:
    """Uma vez: converte o histórico antigo do navegador (lista de {q, d} da busca por cargo) em uma sessão."""
    validos = []
    for it in (itens or [])[:MAX_IMPORTAR]:
        d = it.get("d") if isinstance(it, dict) else None
        q = it.get("q") if isinstance(it, dict) else None
        if isinstance(q, str) and q.strip() and isinstance(d, dict) and isinstance(d.get("vagas_analisadas"), int) and isinstance(d.get("tecnologias"), list):
            validos.append((q.strip()[:MAX_CONSULTA], d))
    if not validos:
        raise ErroSessao(422, "Nenhum item válido para importar.")
    s = criar("Conversas anteriores (importadas)")
    for q, d in validos:
        registrar(s["id"], "chat", {"mensagem": q, "importado": True}, {"resposta": "", "dados": d, "importado": True})
    return obter(s["id"])
