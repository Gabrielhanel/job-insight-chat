"""Acesso ao SQLite compartilhado: cache de páginas, cota mensal e histórico de vagas."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

DB = os.getenv("CACHE_DB", str(Path(__file__).resolve().parent.parent / "cache.db"))

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS paginas (chave TEXT PRIMARY KEY, ts REAL, dados TEXT)",
    "CREATE TABLE IF NOT EXISTS uso (mes TEXT PRIMARY KEY, n INTEGER)",
    "CREATE TABLE IF NOT EXISTS vistas (consulta TEXT, vaga TEXT, PRIMARY KEY (consulta, vaga))",
    "CREATE TABLE IF NOT EXISTS progresso (consulta TEXT PRIMARY KEY, ultima_pagina INTEGER)",
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
