"""Acesso ao SQLite compartilhado: cache de páginas, cota mensal e histórico de vagas."""
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

DB = os.getenv("CACHE_DB", str(Path(__file__).resolve().parent.parent / "cache.db"))

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS paginas (chave TEXT PRIMARY KEY, ts REAL, dados TEXT)",
    "CREATE TABLE IF NOT EXISTS uso (mes TEXT PRIMARY KEY, n INTEGER)",
    "CREATE TABLE IF NOT EXISTS vistas (consulta TEXT, vaga TEXT, PRIMARY KEY (consulta, vaga))",
    "CREATE TABLE IF NOT EXISTS progresso (consulta TEXT PRIMARY KEY, ultima_pagina INTEGER)",
    # Perfil local (sem contas): uma única linha (id=1) + uma linha por área de conhecimento.
    "CREATE TABLE IF NOT EXISTS perfil (id INTEGER PRIMARY KEY CHECK (id = 1), "
    "nome TEXT NOT NULL DEFAULT '', atualizado_em TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS perfil_areas (chave TEXT PRIMARY KEY, nome TEXT NOT NULL, ordem INTEGER NOT NULL)",
    # Habilidades ficam separadas das áreas de conhecimento (Etapa 2). chave = identidade canônica.
    "CREATE TABLE IF NOT EXISTS perfil_habilidades (chave TEXT PRIMARY KEY, nome TEXT NOT NULL, ordem INTEGER NOT NULL)",
    # Sessões (Etapa 7): o id é um valor aleatório independente do título. Datas em ISO UTC (microssegundos) para ordenar.
    "CREATE TABLE IF NOT EXISTS sessoes (id TEXT PRIMARY KEY, titulo TEXT NOT NULL, titulo_manual INTEGER NOT NULL DEFAULT 0, "
    "criada_em TEXT NOT NULL, atualizada_em TEXT NOT NULL)",
    # Uma linha por análise feita na sessão. seq = ordem cronológica determinística; uid = id do evento do navegador (evita duplicar
    # cliques repetidos sem impedir que o usuário repita uma consulta de propósito: cada ação deliberada gera um uid novo).
    "CREATE TABLE IF NOT EXISTS interacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, sessao_id TEXT NOT NULL REFERENCES sessoes(id) ON DELETE CASCADE, "
    "seq INTEGER NOT NULL, uid TEXT, tipo TEXT NOT NULL, consulta TEXT NOT NULL, parametros TEXT NOT NULL, resultado TEXT, "
    "status TEXT NOT NULL, resumo TEXT NOT NULL DEFAULT '', criada_em TEXT NOT NULL, UNIQUE (sessao_id, seq), UNIQUE (sessao_id, uid))",
    "CREATE INDEX IF NOT EXISTS ix_interacoes_sessao ON interacoes (sessao_id, seq)",
    "CREATE INDEX IF NOT EXISTS ix_sessoes_atualizada ON sessoes (atualizada_em)",
)


def _conexao() -> sqlite3.Connection:
    conexao = sqlite3.connect(DB)
    conexao.execute("PRAGMA foreign_keys = ON")  # interações só existem dentro de uma sessão válida
    for ddl in _SCHEMA:
        conexao.execute(ddl)
    return conexao


def consultar(sql: str, args: tuple = ()) -> list[tuple]:
    with closing(_conexao()) as conexao:
        linhas = conexao.execute(sql, args).fetchall()
        conexao.commit()
        return linhas


def consultar_varios(sql: str, lista_args: list[tuple]) -> None:
    with closing(_conexao()) as conexao:
        conexao.executemany(sql, lista_args)
        conexao.commit()


@contextmanager
def transacao():
    """Uma conexão com commit/rollback atômico, para gravações que tocam mais de uma linha ou tabela."""
    with closing(_conexao()) as conexao:
        try:
            conexao.execute("BEGIN IMMEDIATE")  # serializa gravações concorrentes
            yield conexao
            conexao.commit()
        except BaseException:
            conexao.rollback()
            raise
