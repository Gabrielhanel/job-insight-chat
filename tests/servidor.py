"""Sobe o uvicorn de verdade (processo separado) apontando para um SQLite temporário."""
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def servidor(caminho_db: str):
    porta = porta_livre()
    env = {k: v for k, v in os.environ.items() if k not in ("OPENWEBNINJA_API_KEY", "CHAVE_OPENROUTER", "RAPIDAPI_KEY")}
    env["CACHE_DB"] = caminho_db
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(porta), "--log-level", "warning"],
        cwd=RAIZ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{porta}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/status", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("servidor não subiu")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)
