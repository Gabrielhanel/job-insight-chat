"""Teste G — o perfil sobrevive ao encerramento e à nova inicialização do servidor (processos reais)."""
import httpx

from tests.servidor import servidor


def test_g_persistencia_apos_reinicio(tmp_path):
    db = str(tmp_path / "reinicio.db")
    areas = ["Desenvolvimento Mobile", "Ciência de Dados", "Cibersegurança"]

    with servidor(db) as url:  # 1ª execução
        assert httpx.get(url + "/perfil").json()["existe"] is False
        r = httpx.put(url + "/perfil", json={"nome": "Gabriel Hanel", "areas": areas})
        assert r.status_code == 200

    with servidor(db) as url:  # processo novo, mesmo arquivo SQLite
        d = httpx.get(url + "/perfil").json()
        assert d["existe"] is True
        assert d["nome"] == "Gabriel Hanel"
        assert d["areas"] == areas

        httpx.put(url + "/perfil", json={"nome": "Gabriel", "areas": areas[:2]})

    with servidor(db) as url:  # a alteração também persiste
        d = httpx.get(url + "/perfil").json()
        assert d["nome"] == "Gabriel" and d["areas"] == areas[:2]
