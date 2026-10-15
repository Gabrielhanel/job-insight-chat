"""Perfil local do usuário: nome e áreas de conhecimento, persistidos no SQLite."""
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from app import db, skills

log = logging.getLogger("vagas")

MAX_NOME = 100
MAX_AREA = 60
MAX_AREAS = 30
MAX_HABILIDADE = 40
MAX_HABILIDADES = 60


class ErroPerfil(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _limpar(texto: str) -> str:
    """NFC + espaços internos colapsados + bordas aparadas. Mantém acentos e a grafia do usuário."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", texto)).strip()


def _chave(area: str) -> str:
    return area.casefold()  # só ignora maiúsculas/minúsculas; acentos continuam distintos


def _tem_controle(texto: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in texto)


def validar(nome: str, areas: list[str]) -> tuple[str, list[str]]:
    """Valida e normaliza a entrada. Levanta ErroPerfil (422) na primeira violação, sem gravar nada."""
    nome_limpo = _limpar(nome)
    if _tem_controle(nome_limpo):
        raise ErroPerfil(422, "O nome contém caracteres inválidos.")
    if len(nome_limpo) > MAX_NOME:
        raise ErroPerfil(422, f"O nome pode ter no máximo {MAX_NOME} caracteres (atual: {len(nome_limpo)}).")

    if len(areas) > MAX_AREAS:
        raise ErroPerfil(422, f"Você pode cadastrar no máximo {MAX_AREAS} áreas de conhecimento.")
    vistas: set[str] = set()
    limpas: list[str] = []
    for bruta in areas:
        area = _limpar(bruta)
        if not area:
            raise ErroPerfil(422, "Uma área de conhecimento não pode ficar vazia.")
        if _tem_controle(area):
            raise ErroPerfil(422, "Uma área de conhecimento contém caracteres inválidos.")
        if len(area) > MAX_AREA:
            raise ErroPerfil(422, f"Cada área pode ter no máximo {MAX_AREA} caracteres: “{area[:20]}…” tem {len(area)}.")
        if _chave(area) in vistas:
            raise ErroPerfil(422, f"A área “{area}” está repetida.")
        vistas.add(_chave(area))
        limpas.append(area)
    return nome_limpo, limpas


def _resposta(nome: str, areas: list[str], atualizado_em: str | None) -> dict:
    return {
        "existe": atualizado_em is not None,
        "nome": nome,
        "areas": areas,
        "atualizado_em": atualizado_em,
        "limites": {"nome": MAX_NOME, "area": MAX_AREA, "max_areas": MAX_AREAS},
    }


def obter() -> dict:
    try:
        cabecalho = db.consultar("SELECT nome, atualizado_em FROM perfil WHERE id=1")
        areas = db.consultar("SELECT nome FROM perfil_areas ORDER BY ordem")
    except sqlite3.Error as e:
        log.error("Falha ao ler o perfil: %s", type(e).__name__)
        raise ErroPerfil(500, "Não foi possível carregar o perfil. Tente novamente.")
    nome, quando = cabecalho[0] if cabecalho else ("", None)
    return _resposta(nome, [a[0] for a in areas], quando)


def salvar(nome: str, areas: list[str]) -> dict:
    nome, areas = validar(nome, areas)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with db.transacao() as c:  # tudo ou nada: uma falha no meio não deixa perfil pela metade
            c.execute(
                "INSERT INTO perfil (id, nome, atualizado_em) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, atualizado_em=excluded.atualizado_em",
                (nome, agora),
            )
            c.execute("DELETE FROM perfil_areas")
            c.executemany(
                "INSERT INTO perfil_areas (chave, nome, ordem) VALUES (?, ?, ?)",
                [(_chave(a), a, i) for i, a in enumerate(areas)],
            )
    except sqlite3.Error as e:
        log.error("Falha ao salvar o perfil: %s", type(e).__name__)  # sem dados do usuário no log
        raise ErroPerfil(500, "Não foi possível salvar o perfil. Seus dados continuam no formulário; tente novamente.")
    return _resposta(nome, areas, agora)


# ---------------------------------------------------------------------------------------------
# Habilidades (Etapa 2) — lista própria, separada das áreas de conhecimento.
# ---------------------------------------------------------------------------------------------
def _limites_habilidades() -> dict:
    return {"habilidade": MAX_HABILIDADE, "max_habilidades": MAX_HABILIDADES}


def normalizar_habilidade(termo: str) -> dict:
    """Valida um termo e devolve {nome canônico legível, chave de comparação}. Não grava nada."""
    limpo = skills.limpar(termo)
    if not limpo:
        raise ErroPerfil(422, "Digite o nome de uma habilidade.")
    if _tem_controle(limpo):
        raise ErroPerfil(422, "A habilidade contém caracteres inválidos.")
    if len(limpo) > MAX_HABILIDADE:
        raise ErroPerfil(422, f"Cada habilidade pode ter no máximo {MAX_HABILIDADE} caracteres (atual: {len(limpo)}).")
    nome = skills.canonizar(limpo)
    return {"nome": nome, "chave": skills.chave(nome)}


def validar_habilidades(lista: list[str]) -> list[tuple[str, str]]:
    """[(chave, nome canônico)] na ordem recebida. Duplicatas (inclusive por alias: JS e JavaScript) são recusadas."""
    if len(lista) > MAX_HABILIDADES:
        raise ErroPerfil(422, f"Você pode cadastrar no máximo {MAX_HABILIDADES} habilidades.")
    vistas: dict[str, str] = {}
    for bruta in lista:
        h = normalizar_habilidade(bruta)
        if h["chave"] in vistas:
            raise ErroPerfil(422, f"A habilidade “{h['nome']}” está repetida.")
        vistas[h["chave"]] = h["nome"]
    return list(vistas.items())


def _resposta_habilidades(nomes: list[str]) -> dict:
    return {"habilidades": nomes, "limites": _limites_habilidades()}


def obter_habilidades() -> dict:
    try:
        linhas = db.consultar("SELECT nome FROM perfil_habilidades ORDER BY ordem")
    except sqlite3.Error as e:
        log.error("Falha ao ler as habilidades: %s", type(e).__name__)
        raise ErroPerfil(500, "Não foi possível carregar as habilidades. Tente novamente.")
    return _resposta_habilidades([l[0] for l in linhas])


def salvar_habilidades(lista: list[str]) -> dict:
    itens = validar_habilidades(lista)
    try:
        with db.transacao() as c:  # não toca em perfil/perfil_areas
            c.execute("DELETE FROM perfil_habilidades")
            c.executemany(
                "INSERT INTO perfil_habilidades (chave, nome, ordem) VALUES (?, ?, ?)",
                [(k, n, i) for i, (k, n) in enumerate(itens)],
            )
    except sqlite3.Error as e:
        log.error("Falha ao salvar as habilidades: %s", type(e).__name__)
        raise ErroPerfil(500, "Não foi possível salvar as habilidades. Elas continuam na tela; tente novamente.")
    return _resposta_habilidades([n for _, n in itens])
