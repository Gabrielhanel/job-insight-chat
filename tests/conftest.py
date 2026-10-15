import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from app import cache, db, extract
from app.main import app


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """SQLite temporário: os testes nunca tocam o cache.db real."""
    caminho = str(tmp_path / "teste.db")
    monkeypatch.setattr(db, "DB", caminho)
    return caminho


@pytest.fixture
def client(banco):
    return TestClient(app)


@pytest.fixture
def banco_legado(banco):
    """Banco com as tabelas e linhas que já existiam antes do Perfil (sem as tabelas novas)."""
    c = sqlite3.connect(banco)
    c.execute("CREATE TABLE paginas (chave TEXT PRIMARY KEY, ts REAL, dados TEXT)")
    c.execute("CREATE TABLE uso (mes TEXT PRIMARY KEY, n INTEGER)")
    c.execute("CREATE TABLE vistas (consulta TEXT, vaga TEXT, PRIMARY KEY (consulta, vaga))")
    c.execute("CREATE TABLE progresso (consulta TEXT PRIMARY KEY, ultima_pagina INTEGER)")
    c.execute("INSERT INTO paginas VALUES ('k', 1.0, '[1,2]')")
    c.execute("INSERT INTO uso VALUES ('2026-10', 42)")
    c.execute("INSERT INTO vistas VALUES ('br|kotlin', 'v1')")
    c.execute("INSERT INTO progresso VALUES ('br|kotlin', 3)")
    c.commit()
    c.close()
    return banco


@pytest.fixture
def provedor(banco, monkeypatch):
    """Configura PROVEDOR=jsearch com chave FALSA e troca o transporte HTTP por um provedor simulado."""
    from tests.falso_provedor import Provedor

    p = Provedor()
    monkeypatch.setenv("PROVEDOR", "jsearch")
    monkeypatch.setenv("OPENWEBNINJA_API_KEY", "chave-de-teste")
    for k in ("RAPIDAPI_KEY", "ANTHROPIC_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(k, raising=False)
    original = httpx.AsyncClient

    class Falso(original):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(p.handler)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", Falso)
    monkeypatch.setattr(cache, "QUOTA", 200)
    extract.limpar_cache_extracao()
    yield p
    extract.limpar_cache_extracao()
