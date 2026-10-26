"""Caso de uso: comparar duas vagas.

Seleção por pesquisa independente (cada lado tem a sua consulta) ou por entrada manual. Uma seleção por pesquisa guarda
{consulta, pais, paginas, id}: a comparação recarrega a vaga pelo MESMO `jobs.buscar_vagas` da busca (cache de páginas e
cota existentes), então uma vaga vista nas últimas horas não custa nova requisição; se o cache expirou, a página é buscada
de novo (e contada na cota). Vaga manual: texto do usuário, marcada como não verificada; links só são validados
(http/https), nunca acessados. Nada é gravado no banco; vagas A e B são carregadas, extraídas e analisadas isoladamente.
"""
import hashlib
import logging
import re
from datetime import datetime, timezone

from app import cache, comparar, jobs, perfil, reversa, skills
from app.extract import extrair_por_vaga

log = logging.getLogger("vagas")

MIN_CONSULTA, MAX_CONSULTA = 2, 80  # consulta DIGITADA na busca da tela Comparar vagas
MAX_PAGINAS = 3  # páginas da busca digitada na tela Comparar vagas
# Seleções vindas de "Vagas por habilidades" carregam a consulta e as páginas que aquela busca usou, então os limites
# da SELEÇÃO derivam das constantes que geram esses dados (uma fonte só; mudar lá muda aqui):
#   consulta = área (<= reversa.MAX_AREA) + até N habilidades de <= perfil.MAX_HABILIDADE caracteres + espaços
MAX_CONSULTA_SELECAO = reversa.MAX_AREA + max(reversa.HABILIDADES_POR_CONSULTA.values()) * (perfil.MAX_HABILIDADE + 1) + 1
MAX_PAGINAS_SELECAO = reversa.MAX_PAGINAS
# ID do anúncio: valor opaco do provedor, guardado e enviado SEM alteração (nada de truncar, recodificar ou aparar).
# IDs do estilo Google Jobs são JSON em base64 e passam de 300 caracteres (visto em teste: 459); 1024 cobre isso com folga
# e ainda barra entradas absurdas.
MAX_ID = 1024
MAX_TITULO, MAX_EMPRESA, MAX_LINK, MAX_DESCRICAO = 200, 120, 500, 8000


class ErroComparacao(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _msg_credenciais(provedor: str) -> str:
    quais = "OPENWEBNINJA_API_KEY (ou RAPIDAPI_KEY)" if provedor == "jsearch" else "ADZUNA_APP_ID e ADZUNA_APP_KEY"
    return f"A busca real está indisponível: faltam as credenciais do provedor de vagas ({quais}) no .env."


def _sem_controle(txt: str) -> bool:
    return not any(ord(c) < 32 and c not in "\n\r\t" for c in txt)


# ---------------------------------------------------------------- pesquisa para os seletores
def _validar_consulta(consulta: str, pais: str, paginas: int, max_consulta: int = MAX_CONSULTA, max_paginas: int = MAX_PAGINAS) -> tuple[str, str]:
    consulta = skills.limpar(consulta or "")
    if len(consulta) < MIN_CONSULTA:
        raise ErroComparacao(422, "Informe um cargo ou consulta para buscar vagas (por exemplo: Desenvolvedor Back-end).")
    if len(consulta) > max_consulta:
        raise ErroComparacao(422, f"A consulta pode ter no máximo {max_consulta} caracteres (atual: {len(consulta)}).")
    if not re.fullmatch(r"[a-z]{2}", pais or ""):
        raise ErroComparacao(422, "País inválido.")
    if not 1 <= paginas <= max_paginas:
        raise ErroComparacao(422, f"Escolha de 1 a {max_paginas} páginas.")
    return consulta, pais


def planejar(consulta: str, pais: str = "br", paginas: int = 1) -> dict:
    consulta, pais = _validar_consulta(consulta, pais, paginas)
    provedor, ok = jobs.provedor_status()
    return {"consulta": consulta, "paginas": paginas, "requisicoes_max": paginas, "usado": cache.usado(), "limite": cache.QUOTA,
            "provedor": provedor, "credenciais": ok, "cache_ttl_horas": cache.TTL // 3600}


def _resumo(v: dict) -> dict:
    d = v.get("descricao") or ""
    return {"id": v["id"], "titulo": v["titulo"], "empresa": v["empresa"], "local": v.get("local") or None,
            "link": _link_seguro(v.get("link")), "publicada_em": v.get("publicada_em"), "provedor": v.get("provedor"),
            "descricao_chars": len(d), "tem_descricao": bool(d.strip()), "descricao_resumo": bool(v.get("descricao_resumo")),
            "descricao_truncada": bool(v.get("descricao_truncada"))}


def _link_seguro(link):
    return link if isinstance(link, str) and link.lower().startswith(("http://", "https://")) else None


async def buscar(consulta: str, pais: str = "br", paginas: int = 1) -> dict:
    plano = planejar(consulta, pais, paginas)
    if not plano["credenciais"]:
        raise ErroComparacao(503, _msg_credenciais(plano["provedor"]))
    antes = cache.usado()
    try:
        vagas, info = await jobs.buscar_vagas(plano["consulta"], pais, paginas, 1, por_anuncio=True)
    except jobs.ErroVagas as e:
        raise ErroComparacao(e.status, e.msg)
    avisos = []
    if info["paginas_ok"] < info["paginas_total"]:
        avisos.append(f"Resultado parcial: {info['paginas_ok']} de {info['paginas_total']} páginas.")
    if any(v.get("descricao_resumo") for v in vagas):
        avisos.append("Este provedor costuma devolver só um trecho da descrição das vagas: a análise pode ficar incompleta.")
    return {"ref": {"consulta": plano["consulta"], "pais": pais, "paginas": paginas}, "vagas": [_resumo(v) for v in vagas],
            "requisicoes_feitas": max(0, cache.usado() - antes), "do_cache": info["do_cache"], "usado": cache.usado(),
            "limite": cache.QUOTA, "avisos": avisos, "estado": "ok" if vagas else "sem_vagas"}


# ---------------------------------------------------------------- seleção
def _validar_manual(sel: dict) -> dict:
    titulo, empresa = skills.limpar(sel.get("titulo") or ""), skills.limpar(sel.get("empresa") or "")
    desc, link = (sel.get("descricao") or "").strip(), (sel.get("link") or "").strip()
    if not titulo:
        raise ErroComparacao(422, "Informe o título da vaga inserida manualmente.")
    if len(titulo) > MAX_TITULO:
        raise ErroComparacao(422, f"O título pode ter no máximo {MAX_TITULO} caracteres (atual: {len(titulo)}).")
    if len(empresa) > MAX_EMPRESA:
        raise ErroComparacao(422, f"A empresa pode ter no máximo {MAX_EMPRESA} caracteres (atual: {len(empresa)}).")
    if not desc:
        raise ErroComparacao(422, "Cole a descrição da vaga inserida manualmente.")
    if len(desc) > MAX_DESCRICAO:
        raise ErroComparacao(422, f"A descrição pode ter no máximo {MAX_DESCRICAO} caracteres (atual: {len(desc)}).")
    if not (_sem_controle(titulo) and _sem_controle(empresa) and _sem_controle(desc)):
        raise ErroComparacao(422, "O texto contém caracteres de controle inválidos.")
    if link:
        if len(link) > MAX_LINK or not _link_seguro(link):
            raise ErroComparacao(422, f"O link deve começar com http:// ou https:// e ter até {MAX_LINK} caracteres. Ele só é exibido, nunca acessado.")
    h = hashlib.sha1(f"{titulo}\x00{empresa}\x00{desc}".encode("utf-8")).hexdigest()[:12]
    return {"id": f"manual:{h}", "origem": "manual", "provedor": None, "titulo": titulo, "empresa": empresa, "local": None,
            "link": link or None, "publicada_em": None, "descricao": desc, "obtida_em": _agora()}


def _validar_selecao(sel: dict, lado: str) -> dict:
    tipo = sel.get("tipo")
    if tipo == "manual":
        return {"tipo": "manual", "vaga": _validar_manual(sel)}
    if tipo != "busca":
        raise ErroComparacao(422, f"Vaga {lado}: tipo de seleção inválido.")
    try:
        bruto = sel.get("paginas")
        paginas = 1 if bruto is None else int(bruto)   # 0 não é "ausente": é inválido (e não vira 1 em silêncio)
    except (TypeError, ValueError):
        raise ErroComparacao(422, f"Vaga {lado}: número de páginas inválido.")
    consulta, pais = _validar_consulta(sel.get("consulta") or "", sel.get("pais") or "br", paginas, MAX_CONSULTA_SELECAO, MAX_PAGINAS_SELECAO)
    id_ = sel.get("id")
    if not isinstance(id_, str) or not id_.strip():
        raise ErroComparacao(422, f"Vaga {lado}: selecione um anúncio da lista de resultados (o identificador está ausente).")
    if len(id_) > MAX_ID:
        raise ErroComparacao(422, f"Vaga {lado}: o identificador do anúncio tem {len(id_)} caracteres e o limite é {MAX_ID}.")
    if any(ord(c) < 32 or ord(c) == 127 for c in id_):   # no ID nem quebra de linha ou tabulação é aceita
        raise ErroComparacao(422, f"Vaga {lado}: o identificador do anúncio contém caracteres de controle inválidos.")
    return {"tipo": "busca", "consulta": consulta, "pais": pais, "paginas": paginas, "id": id_}  # id exatamente como veio


def _chave_selecao(s: dict) -> tuple:
    return ("manual", s["vaga"]["id"]) if s["tipo"] == "manual" else ("busca", s["id"])


async def _carregar(s: dict, paginas_lidas: dict) -> dict:
    """Vaga da pesquisa, pelo cache de páginas; uma só leitura por (consulta, país, páginas) dentro da comparação."""
    k = (s["consulta"].lower(), s["pais"], s["paginas"])
    if k not in paginas_lidas:
        try:
            paginas_lidas[k] = await jobs.buscar_vagas(s["consulta"], s["pais"], s["paginas"], 1, por_anuncio=True)
        except jobs.ErroVagas as e:
            paginas_lidas[k] = e
    r = paginas_lidas[k]
    if isinstance(r, jobs.ErroVagas):
        raise ErroComparacao(r.status, r.msg)
    vagas, _ = r
    for v in vagas:
        if v["id"] == s["id"]:
            return {**v, "origem": "provedor", "obtida_em": _agora()}
    raise ErroComparacao(404, "Esta vaga não aparece mais nos resultados da consulta. Refaça a busca e selecione novamente.")


def _falha(s: dict, e: ErroComparacao) -> dict:
    return {"status": "falha_ao_carregar", "codigo": e.status, "motivo": e.msg, "limitacoes": [e.msg], "confianca_ausencia": "baixa",
            "identidade": {"id": s.get("id"), "origem": "provedor", "titulo": None, "empresa": None, "local": None, "link": None,
                           "provedor": None, "publicada_em": None, "obtida_em": None, "descricao_chars": 0}}


async def comparar_vagas(a: dict, b: dict, habilidades: list[str] | None = None) -> dict:
    sa, sb = _validar_selecao(a, "A"), _validar_selecao(b, "B")
    if _chave_selecao(sa) == _chave_selecao(sb):
        raise ErroComparacao(422, "As duas seleções se referem ao mesmo anúncio. Escolha duas vagas diferentes.")
    precisa_api = any(s["tipo"] == "busca" for s in (sa, sb))
    provedor, ok = jobs.provedor_status()
    if precisa_api and not ok:
        raise ErroComparacao(503, _msg_credenciais(provedor))

    antes = cache.usado()
    lidas: dict = {}
    vagas: dict[str, dict] = {}
    falhas: dict[str, dict] = {}
    for lado, s in (("a", sa), ("b", sb)):
        if s["tipo"] == "manual":
            vagas[lado] = s["vaga"]
            continue
        try:
            vagas[lado] = await _carregar(s, lidas)
        except ErroComparacao as e:
            falhas[lado] = _falha(s, e)
    if len(falhas) == 2:
        raise ErroComparacao(next(iter(falhas.values()))["codigo"], next(iter(falhas.values()))["motivo"])
    if len(vagas) == 2 and vagas["a"]["id"] == vagas["b"]["id"]:
        raise ErroComparacao(422, "As duas seleções se referem ao mesmo anúncio. Escolha duas vagas diferentes.")

    # extração: uma vez por vaga (o cache de extrações evita chamar a IA de novo para a mesma descrição)
    com_texto = [v for v in vagas.values() if (v.get("descricao") or "").strip()]
    extracoes = await extrair_por_vaga(com_texto) if com_texto else {}

    if habilidades is None:
        try:
            habilidades = perfil.obter_habilidades()["habilidades"]
        except perfil.ErroPerfil:
            habilidades = []
    chaves = {skills.chave(h) for h in habilidades}
    analises: dict[str, dict] = {}
    for lado in ("a", "b"):
        if lado in falhas:
            analises[lado] = falhas[lado]
            continue
        v = vagas[lado]
        try:
            analises[lado] = comparar.analisar_vaga(v, extracoes.get(v["id"]), chaves, bool(habilidades))
        except Exception as e:  # falha isolada: a outra vaga segue
            log.error("Falha ao analisar a vaga %s: %s", lado.upper(), type(e).__name__)
            analises[lado] = _falha(sa if lado == "a" else sb, ErroComparacao(500, "Falha ao analisar esta vaga."))

    avisos = []
    if falhas:
        lado = next(iter(falhas))
        avisos.append(f"Não foi possível carregar a vaga {lado.upper()}: {falhas[lado]['motivo']} A outra vaga foi analisada e preservada; a comparação não foi feita.")
        comp = {"disponivel": False, "motivo": "A comparação exige as duas vagas carregadas."}
    else:
        comp = comparar.comparar(analises["a"], analises["b"])
        if not comp["disponivel"]:
            avisos.append(comp["motivo"])
    sint = comparar.sintese(analises["a"], analises["b"], comp) if not falhas else None
    todo_cache = max(0, cache.usado() - antes) == 0 and bool(lidas)
    return {
        "estado": "parcial" if falhas or not comp["disponivel"] else "completa", "a": analises["a"], "b": analises["b"],
        "comparacao": comp, "sintese": sint, "avisos": avisos, "perfil_habilidades": len(habilidades),
        "requisicoes_feitas": max(0, cache.usado() - antes), "todo_do_cache": todo_cache, "cache_ttl_horas": cache.TTL // 3600,
        "usado": cache.usado(), "limite": cache.QUOTA,
    }
