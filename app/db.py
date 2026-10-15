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
)


def _conexao() -> sqlite3.Connection:
    conexao = sqlite3.connect(DB)
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
