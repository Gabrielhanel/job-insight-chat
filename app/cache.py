"""Cache persistente das páginas de vagas e contador local de cota mensal."""
import json
import os
import time
from datetime import datetime, timezone

from app.db import consultar

TTL = int(os.getenv("CACHE_TTL_H", "24")) * 3600
QUOTA = int(os.getenv("QUOTA_MENSAL", "200"))


def pegar(chave: str):
    linhas = consultar("SELECT ts, dados FROM paginas WHERE chave=?", (chave,))
    if linhas and time.time() - linhas[0][0] < TTL:
        return json.loads(linhas[0][1])
    return None


def salvar(chave: str, dados) -> None:
    consultar("REPLACE INTO paginas VALUES (?,?,?)", (chave, time.time(), json.dumps(dados)))


def _mes() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usado() -> int:
    linhas = consultar("SELECT n FROM uso WHERE mes=?", (_mes(),))
    return linhas[0][0] if linhas else 0


def registrar(n: int = 1) -> None:
    """Conta uma requisição enviada à API (inclui tentativas com erro, por segurança)."""
    consultar("INSERT INTO uso VALUES (?,?) ON CONFLICT(mes) DO UPDATE SET n=n+?", (_mes(), n, n))
