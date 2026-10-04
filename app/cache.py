import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB = os.getenv("CACHE_DB", str(Path(__file__).resolve().parent.parent / "cache.db"))
TTL = int(os.getenv("CACHE_TTL_H", "24")) * 3600
QUOTA = int(os.getenv("QUOTA_MENSAL", "200"))


def _q(sql: str, args: tuple = (), fetch: bool = False):
    with closing(sqlite3.connect(DB)) as c:
        c.execute("CREATE TABLE IF NOT EXISTS paginas (chave TEXT PRIMARY KEY, ts REAL, dados TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS uso (mes TEXT PRIMARY KEY, n INTEGER)")
        cur = c.execute(sql, args)
        r = cur.fetchone() if fetch else None
        c.commit()
        return r


def pegar(chave: str):
    r = _q("SELECT ts, dados FROM paginas WHERE chave=?", (chave,), fetch=True)
    return json.loads(r[1]) if r and time.time() - r[0] < TTL else None


def salvar(chave: str, dados) -> None:
    _q("REPLACE INTO paginas VALUES (?,?,?)", (chave, time.time(), json.dumps(dados)))


def _mes() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usado() -> int:
    r = _q("SELECT n FROM uso WHERE mes=?", (_mes(),), fetch=True)
    return r[0] if r else 0


def registrar(n: int = 1) -> None:
    """Conta uma requisição enviada à API (inclui tentativas com erro, por segurança)."""
    _q("INSERT INTO uso VALUES (?,?) ON CONFLICT(mes) DO UPDATE SET n=n+?", (_mes(), n, n))
