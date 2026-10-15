"""Etapa 1 — Perfil: testes de API e persistência (A–F, H, I, J-backend, K)."""
import sqlite3

import pytest

from app import db, perfil


def salvar(client, nome="", areas=()):
    return client.put("/perfil", json={"nome": nome, "areas": list(areas)})


# --- Teste A — perfil vazio
def test_a_perfil_vazio(client):
    r = client.get("/perfil")
    assert r.status_code == 200
    d = r.json()
    assert d["existe"] is False
    assert d["nome"] == "" and d["areas"] == [] and d["atualizado_em"] is None


# --- Teste B — nome com acentos e caracteres especiais
def test_b_nome_com_acentos(client):
    nome = "  José D’Ávila-Çelik Ñandú  "
    r = salvar(client, nome)
    assert r.status_code == 200
    esperado = "José D’Ávila-Çelik Ñandú"
    assert r.json()["nome"] == esperado
    assert client.get("/perfil").json()["nome"] == esperado


# --- Teste C — várias áreas, em português, preservando grafia e ordem
def test_c_varias_areas(client):
    areas = ["Desenvolvimento Mobile", "Ciência de Dados", "Engenharia de Dados", "UX/UI Design", "Segurança & Privacidade"]
    assert salvar(client, "Ana", areas).status_code == 200
    assert client.get("/perfil").json()["areas"] == areas


# --- Teste D — duplicatas (maiúsculas/minúsculas e espaços), sem apagar o que já existia
@pytest.mark.parametrize("repetida", ["ciência de dados", "CIÊNCIA DE DADOS", "  Ciência   de  Dados "])
def test_d_duplicatas_rejeitadas(client, repetida):
    salvar(client, "Ana", ["Ciência de Dados"])
    r = salvar(client, "Outro", ["Ciência de Dados", repetida])
    assert r.status_code == 422
    assert "repetida" in r.json()["detail"]
    atual = client.get("/perfil").json()
    assert atual["nome"] == "Ana" and atual["areas"] == ["Ciência de Dados"]


def test_d_acento_diferente_nao_e_duplicata(client):
    assert salvar(client, "", ["Ciencia", "Ciência"]).status_code == 200


# --- Teste E — remoção
def test_e_remocao(client):
    salvar(client, "Ana", ["A", "B", "C"])
    assert salvar(client, "Ana", ["A", "C"]).status_code == 200
    assert client.get("/perfil").json()["areas"] == ["A", "C"]
    n = db.consultar("SELECT count(*) FROM perfil_areas")[0][0]
    assert n == 2


# --- Teste F — atualização sem duplicar registros
def test_f_atualizacao(client):
    salvar(client, "Ana", ["Back-end", "IA"])
    salvar(client, "Ana Souza", ["IA", "Cloud Computing", "Mobile"])
    d = client.get("/perfil").json()
    assert d["nome"] == "Ana Souza"
    assert d["areas"] == ["IA", "Cloud Computing", "Mobile"]
    assert db.consultar("SELECT count(*) FROM perfil")[0][0] == 1
    assert db.consultar("SELECT count(*) FROM perfil_areas")[0][0] == 3


def test_f_ordem_e_data_de_atualizacao(client):
    r = salvar(client, "Ana", ["Z", "A", "M"])
    assert r.json()["areas"] == ["Z", "A", "M"]
    assert r.json()["atualizado_em"]


def test_nome_vazio_e_valido_e_lista_vazia_limpa_areas(client):
    salvar(client, "Ana", ["A"])
    r = salvar(client, "", [])
    assert r.status_code == 200
    d = client.get("/perfil").json()
    assert d["existe"] is True and d["nome"] == "" and d["areas"] == []


# --- Teste H — valores inválidos não apagam dados anteriores
def casos_invalidos():
    return [
        ("nome longo", {"nome": "x" * (perfil.MAX_NOME + 1), "areas": []}),
        ("area vazia", {"nome": "ok", "areas": ["A", "   "]}),
        ("area longa", {"nome": "ok", "areas": ["y" * (perfil.MAX_AREA + 1)]}),
        ("muitas areas", {"nome": "ok", "areas": [f"a{i}" for i in range(perfil.MAX_AREAS + 1)]}),
        ("controle no nome", {"nome": "ab\x00c", "areas": []}),
        ("controle na area", {"nome": "ok", "areas": ["a\x07b"]}),
    ]


@pytest.mark.parametrize("rotulo,corpo", casos_invalidos(), ids=[c[0] for c in casos_invalidos()])
def test_h_invalidos_nao_apagam_dados(client, rotulo, corpo):
    salvar(client, "Original", ["Mobile", "IA"])
    r = client.put("/perfil", json=corpo)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]
    d = client.get("/perfil").json()
    assert d["nome"] == "Original" and d["areas"] == ["Mobile", "IA"]


def test_h_nome_apenas_espacos_vira_vazio(client):
    r = salvar(client, "     ", ["A"])
    assert r.status_code == 200 and r.json()["nome"] == ""


def test_h_limites_exatos_sao_aceitos(client):
    r = salvar(client, "n" * perfil.MAX_NOME, ["a" * perfil.MAX_AREA] + [f"x{i}" for i in range(perfil.MAX_AREAS - 1)])
    assert r.status_code == 200


def test_h_corpo_malformado_nao_altera_perfil(client):
    salvar(client, "Original", ["A"])
    assert client.put("/perfil", json={"nome": "x", "areas": "não é lista"}).status_code == 422
    assert client.get("/perfil").json()["areas"] == ["A"]


# --- Teste I (backend) — falha de persistência: erro genérico, sem vazar detalhes, dados antigos intactos
def test_i_falha_de_persistencia(client, monkeypatch):
    salvar(client, "Original", ["A", "B"])

    def quebrar(*a, **k):
        raise sqlite3.OperationalError("database is locked: /caminho/interno/cache.db")

    with monkeypatch.context() as m:
        m.setattr(db, "transacao", quebrar)
        r = salvar(client, "Novo", ["Z"])
    assert r.status_code == 500
    assert "cache.db" not in r.text and "locked" not in r.text
    d = client.get("/perfil").json()
    assert d["nome"] == "Original" and d["areas"] == ["A", "B"]


def test_i_falha_no_meio_da_gravacao_faz_rollback(client, banco):
    salvar(client, "Original", ["A", "B"])
    # Um gatilho faz o INSERT da 2ª área falhar depois de o nome, o DELETE e a 1ª área já terem sido executados.
    c = sqlite3.connect(banco)
    c.execute(
        "CREATE TRIGGER falha BEFORE INSERT ON perfil_areas WHEN NEW.nome='Y' "
        "BEGIN SELECT RAISE(ABORT, 'falha simulada'); END"
    )
    c.commit()
    c.close()
    r = salvar(client, "Novo", ["X", "Y"])
    assert r.status_code == 500 and "falha simulada" not in r.text
    d = client.get("/perfil").json()
    assert d["nome"] == "Original" and d["areas"] == ["A", "B"]  # nada ficou pela metade


def test_i_falha_na_leitura(client, monkeypatch):
    def quebrar(*a, **k):
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(db, "consultar", quebrar)
    r = client.get("/perfil")
    assert r.status_code == 500 and isinstance(r.json()["detail"], str)


# --- Teste J (backend) — texto parecido com HTML é guardado e devolvido como texto puro
def test_j_html_e_tratado_como_texto(client):
    xss = '<img src=x onerror=alert(1)>'
    sql = "Robert'); DROP TABLE perfil;--"
    assert salvar(client, "<script>alert(1)</script>", [xss, sql]).status_code == 200
    d = client.get("/perfil").json()
    assert d["nome"] == "<script>alert(1)</script>"
    assert d["areas"] == [xss, sql]
    assert db.consultar("SELECT count(*) FROM perfil")[0][0] == 1  # tabela segue existindo (SQL parametrizado)


def test_dados_do_perfil_nao_vao_para_o_log(client, caplog, monkeypatch):
    def quebrar(*a, **k):
        raise sqlite3.OperationalError("falha")

    salvar(client, "x")
    monkeypatch.setattr(db, "transacao", quebrar)
    with caplog.at_level("DEBUG", logger="vagas"):
        salvar(client, "SegredoNome123", ["SegredoArea456"])
    assert "SegredoNome123" not in caplog.text and "SegredoArea456" not in caplog.text


# --- Teste K (parte backend) — compatibilidade com o banco existente e rotas antigas
def test_k_banco_legado_preservado(client, banco_legado):
    assert client.get("/perfil").json()["existe"] is False  # aplicação funciona sem perfil
    salvar(client, "Ana", ["IA"])
    c = sqlite3.connect(banco_legado)
    assert c.execute("SELECT dados FROM paginas WHERE chave='k'").fetchone() == ("[1,2]",)
    assert c.execute("SELECT n FROM uso WHERE mes='2026-10'").fetchone() == (42,)
    assert c.execute("SELECT count(*) FROM vistas").fetchone() == (1,)
    assert c.execute("SELECT ultima_pagina FROM progresso").fetchone() == (3,)
    c.close()


def test_k_rotas_existentes_continuam(client, monkeypatch):
    r = client.get("/")
    assert r.status_code == 200 and "Perfil" in r.text
    s = client.get("/status")
    assert s.status_code == 200 and {"usado", "limite", "extracao"} <= set(s.json())
    # /chat continua exigindo vagas: sem chave de API devolve erro tratado (não 500 de perfil)
    for k in ("OPENWEBNINJA_API_KEY", "RAPIDAPI_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert client.post("/chat", json={"mensagem": "qa"}).status_code != 404


def test_k_perfil_nao_exige_chaves_externas(client, monkeypatch):
    for k in ("OPENWEBNINJA_API_KEY", "CHAVE_OPENROUTER", "RAPIDAPI_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert salvar(client, "Ana", ["IA"]).status_code == 200
    assert client.get("/perfil").status_code == 200
