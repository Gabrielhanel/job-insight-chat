"""Grupo A — perfil e habilidades (persistência, duplicatas, separação das áreas)."""
import sqlite3

import pytest

from app import db, perfil
from tests.servidor import servidor
import httpx


def put_h(client, lista):
    return client.put("/habilidades", json={"habilidades": list(lista)})


def test_a1_recuperar_habilidades_salvas(client):
    assert client.get("/habilidades").json()["habilidades"] == []
    assert put_h(client, ["js", "React Native", "Gestão de Projetos"]).status_code == 200
    assert client.get("/habilidades").json()["habilidades"] == ["JavaScript", "React Native", "Gestão de projetos"]


def test_a2_adicionar_e_remover(client):
    put_h(client, ["Python", "SQL"])
    put_h(client, ["Python", "SQL", "Docker"])
    assert client.get("/habilidades").json()["habilidades"] == ["Python", "SQL", "Docker"]
    put_h(client, ["Python", "Docker"])
    assert client.get("/habilidades").json()["habilidades"] == ["Python", "Docker"]
    assert db.consultar("SELECT count(*) FROM perfil_habilidades")[0][0] == 2
    put_h(client, [])
    assert client.get("/habilidades").json()["habilidades"] == []


@pytest.mark.parametrize("lista", [["JavaScript", "js"], ["Python", " python "], ["Gestão", "GESTAO"], ["TS", "TypeScript"]])
def test_a3_duplicatas_incluindo_alias_sao_recusadas_sem_apagar(client, lista):
    put_h(client, ["Original"])
    r = put_h(client, lista)
    assert r.status_code == 422 and "repetida" in r.json()["detail"]
    assert client.get("/habilidades").json()["habilidades"] == ["Original"]


def test_a3_distintas_nao_sao_duplicatas(client):
    assert put_h(client, ["Java", "JavaScript", "React", "React Native", "C", "C++", "C#"]).status_code == 200


@pytest.mark.parametrize("corpo", [[" "], ["x" * (perfil.MAX_HABILIDADE + 1)], ["a\x00b"],
                                   [f"h{i}" for i in range(perfil.MAX_HABILIDADES + 1)]])
def test_validacoes_nao_apagam_dados(client, corpo):
    put_h(client, ["Original"])
    r = put_h(client, corpo)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert client.get("/habilidades").json()["habilidades"] == ["Original"]


def test_normalizar_endpoint(client):
    r = client.post("/habilidades/normalizar", json={"termo": "  nodejs "})
    assert r.json() == {"nome": "Node.js", "chave": "node.js"}
    assert client.post("/habilidades/normalizar", json={"termo": "  "}).status_code == 422
    assert client.post("/habilidades/normalizar", json={"termo": "x" * 41}).status_code == 422


def test_a4_areas_e_dados_do_perfil_ficam_intactos(client):
    client.put("/perfil", json={"nome": "Ana", "areas": ["Desenvolvimento Mobile", "Ciência de Dados"]})
    put_h(client, ["React Native"])
    p = client.get("/perfil").json()
    assert p["nome"] == "Ana" and p["areas"] == ["Desenvolvimento Mobile", "Ciência de Dados"]
    # e o contrário: salvar nome/áreas (Etapa 1) não mexe nas habilidades; áreas não viram habilidades
    client.put("/perfil", json={"nome": "Ana Souza", "areas": []})
    assert client.get("/habilidades").json()["habilidades"] == ["React Native"]
    assert "Desenvolvimento Mobile" not in client.get("/habilidades").json()["habilidades"]


def test_a4_banco_legado_preservado(client, banco_legado):
    put_h(client, ["Python"])
    c = sqlite3.connect(banco_legado)
    assert c.execute("SELECT n FROM uso").fetchone() == (42,)
    assert c.execute("SELECT count(*) FROM vistas").fetchone() == (1,)
    c.close()


def test_falha_de_persistencia_de_habilidades(client, banco):
    put_h(client, ["A", "B"])
    c = sqlite3.connect(banco)
    c.execute("CREATE TRIGGER falha BEFORE INSERT ON perfil_habilidades WHEN NEW.nome='Y' "
              "BEGIN SELECT RAISE(ABORT, 'falha simulada'); END")
    c.commit(); c.close()
    r = put_h(client, ["X", "Y"])
    assert r.status_code == 500 and "falha simulada" not in r.text
    assert client.get("/habilidades").json()["habilidades"] == ["A", "B"]  # rollback


def test_habilidades_persistem_apos_reinicio(tmp_path):
    dbp = str(tmp_path / "h.db")
    with servidor(dbp) as url:
        assert httpx.put(url + "/habilidades", json={"habilidades": ["js", "Python"]}).status_code == 200
    with servidor(dbp) as url:
        assert httpx.get(url + "/habilidades").json()["habilidades"] == ["JavaScript", "Python"]
