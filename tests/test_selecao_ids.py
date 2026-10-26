"""Etapa 6 — seleção de vagas: identificadores longos preservados, limites coerentes com a origem das seleções e contagens para os gráficos."""
import re
from pathlib import Path

import pytest

from app import comparador, comparar, perfil, reversa, skills
from tests.falso_provedor import vaga

ID_459 = ("eyJqb2JfdGl0bGUiOiJTb2Z0d2FyZSBFbmdpbmVlciIsImNvbXBhbnlfbmFtZSI6IkV4YW1wbGUifQ" * 7)[:456]


def sel(ref, id_):
    return {"tipo": "busca", **ref, "id": id_}


def manual(titulo="Manual B"):
    return {"tipo": "manual", "titulo": titulo, "descricao": "Requisitos: Go, Rust. " + "Contexto da vaga com informações de apoio. " * 10}


def comparar_(client, a, b=None):
    return client.post("/comparar", json={"a": a, "b": b or manual()})


def prepara(provedor, vagas):
    provedor.resposta = lambda q, p: vagas if p == 1 else []


# ---------------- limites derivam das constantes de origem
def test_limites_da_selecao_derivam_das_constantes_que_geram_as_referencias():
    assert comparador.MAX_PAGINAS_SELECAO == reversa.MAX_PAGINAS
    pior_consulta = reversa.MAX_AREA + max(reversa.HABILIDADES_POR_CONSULTA.values()) * perfil.MAX_HABILIDADE + max(reversa.HABILIDADES_POR_CONSULTA.values())
    assert comparador.MAX_CONSULTA_SELECAO >= pior_consulta  # a maior consulta que a busca por habilidades pode gerar cabe na seleção
    assert comparador.MAX_ID == 1024 and comparador.MAX_CONSULTA == 80 and comparador.MAX_PAGINAS == 3  # a busca digitada em Comparar vagas segue com os limites menores


def test_limites_do_frontend_espelham_o_backend():
    html = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")
    lim = dict(re.findall(r"(\w+): (\d+)", re.search(r"const LIM = \{([^}]*)\}", html).group(1)))
    assert {k: int(v) for k, v in lim.items()} == {
        "titulo": comparador.MAX_TITULO, "empresa": comparador.MAX_EMPRESA, "link": comparador.MAX_LINK, "descricao": comparador.MAX_DESCRICAO,
        "id": comparador.MAX_ID, "consulta": comparador.MAX_CONSULTA_SELECAO, "paginas": comparador.MAX_PAGINAS_SELECAO}


# ---------------- 14/15 — IDs
def test_id_longo_legitimo_e_preservado_ate_a_resposta(client, provedor):
    prepara(provedor, [vaga(ID_459, "Dev Python", "Alfa", ["Python", "SQL", "Docker"])])
    b = client.post("/comparar/buscar", json={"consulta": "Dev Python"}).json()
    id_ = b["vagas"][0]["id"]
    assert id_ == "id:" + ID_459 and len(id_) == 459                    # o ID chega ao seletor sem alteração
    d = comparar_(client, sel(b["ref"], id_)).json()
    assert d["estado"] == "completa" and d["a"]["identidade"]["id"] == id_ and d["a"]["identidade"]["titulo"] == "Dev Python"


def test_id_no_limite_exato_passa_e_acima_dele_e_recusado_com_mensagem_clara(client, provedor):
    no_limite = "A" * (comparador.MAX_ID - 3)               # com o prefixo "id:" tem exatamente MAX_ID caracteres
    prepara(provedor, [vaga(no_limite, "Dev No Limite", "Alfa", ["Python"])])
    b = client.post("/comparar/buscar", json={"consulta": "Dev"}).json()
    assert len(b["vagas"][0]["id"]) == comparador.MAX_ID
    assert comparar_(client, sel(b["ref"], b["vagas"][0]["id"])).status_code == 200
    antes = len(provedor.chamadas)
    res = comparar_(client, sel(b["ref"], "x" * (comparador.MAX_ID + 1)))
    assert res.status_code == 422 and "1025 caracteres e o limite é 1024" in res.json()["detail"] and len(provedor.chamadas) == antes


@pytest.mark.parametrize("id_,trecho", [("", "ausente"), ("   ", "ausente"), (None, "ausente"), ("a\x00b", "controle"), ("a\nb", "controle")])
def test_ids_invalidos_sao_rejeitados(client, provedor, id_, trecho):
    ref = {"consulta": "Dev", "pais": "br", "paginas": 1}
    res = comparar_(client, {"tipo": "busca", **ref, "id": id_})
    assert res.status_code == 422 and trecho in res.json()["detail"] and provedor.chamadas == []


def test_id_e_usado_exatamente_como_veio_inclusive_com_espacos(client, provedor):
    prepara(provedor, [vaga(None, "Dev Com Espaços  Internos", "Alfa Beta", ["Python"], cidade="São Paulo")])    # sem job_id: id composto, com espaços
    b = client.post("/comparar/buscar", json={"consulta": "Dev"}).json()
    id_ = b["vagas"][0]["id"]
    assert " " in id_ and id_ == id_.strip()
    d = comparar_(client, sel(b["ref"], id_)).json()
    assert d["a"]["identidade"]["id"] == id_
    # o ID não é "consertado": uma variação (maiúsculas/espaços extras) é outro valor e não encontra a vaga
    parcial = comparar_(client, sel(b["ref"], id_.upper())).json()
    assert parcial["estado"] == "parcial" and parcial["a"]["status"] == "falha_ao_carregar"


# ---------------- defeito original: referências geradas por "Vagas por habilidades"
def test_selecao_vinda_da_busca_por_habilidades_com_consulta_longa_e_5_paginas(client, provedor):
    prepara(provedor, [vaga("h1", "Dev Python", "Alfa", ["Python", "SQL", "Docker"]), vaga("h2", "Dev Go", "Beta", ["Rust", "Perl", "Ruby"])])
    area = "Desenvolvimento Mobile Multiplataforma"
    habs = ["Gestão de Projetos Ágeis Escala", "Arquitetura de Microsserviços", "Engenharia de Confiabilidade"]
    r = client.post("/busca-habilidades", json={"habilidades": habs, "area": area, "paginas": 5}).json()
    ref = r["vagas"][0]["ref"]
    assert len(ref["consulta"]) > comparador.MAX_CONSULTA and ref["paginas"] == 5          # exatamente os valores que antes davam 422
    res = comparar_(client, sel(ref, r["vagas"][0]["id"]))
    assert res.status_code == 200, res.text
    assert res.json()["a"]["identidade"]["id"] == r["vagas"][0]["id"]


def test_consulta_da_selecao_no_limite_passa_e_acima_dele_e_recusada(client, provedor):
    prepara(provedor, [vaga("h1", "Dev Python", "Alfa", ["Python", "SQL", "Docker"])])
    ref = {"consulta": "x" * comparador.MAX_CONSULTA_SELECAO, "pais": "br", "paginas": comparador.MAX_PAGINAS_SELECAO}
    assert comparar_(client, sel(ref, "id:h1")).status_code == 200
    ruim = comparar_(client, sel({**ref, "consulta": "x" * (comparador.MAX_CONSULTA_SELECAO + 1)}, "id:h1"))
    assert ruim.status_code == 422 and "no máximo 184 caracteres (atual: 185)" in ruim.json()["detail"]
    for paginas in (0, 6):
        assert comparar_(client, sel({**ref, "paginas": paginas}, "id:h1")).status_code == 422
    assert comparar_(client, sel({**ref, "pais": "BRASIL"}, "id:h1")).status_code == 422


def test_busca_digitada_na_tela_comparar_mantem_os_limites_menores(client, provedor):
    assert client.post("/comparar/buscar", json={"consulta": "x" * 81}).status_code == 422
    assert client.post("/comparar/buscar", json={"consulta": "ok", "paginas": 4}).status_code == 422
    assert provedor.chamadas == []


def test_anuncio_nao_encontrado_preserva_a_outra_vaga_e_nao_apaga_selecao(client, provedor):
    prepara(provedor, [vaga("h1", "Dev Python", "Alfa", ["Python", "SQL", "Docker"])])
    ref = {"consulta": "Dev", "pais": "br", "paginas": 1}
    d = comparar_(client, sel(ref, "id:nao-existe"), sel(ref, "id:h1")).json()
    assert d["estado"] == "parcial" and d["a"]["status"] == "falha_ao_carregar" and d["b"]["status"] == "analisada"
    assert d["b"]["identidade"]["id"] == "id:h1" and d["a"]["identidade"]["id"] == "id:nao-existe"   # cada resultado no lado certo


# ---------------- contagens estruturadas que alimentam os gráficos
def analisa(id_, tec=(), dif=(), nc=()):
    desc = "Requisitos: " + ", ".join(tec) + ". " + "Contexto da vaga com informações de apoio. " * 8 + ("\nDiferenciais:\n" + ", ".join(dif) if dif else "")
    ext = {"tecnologias": list(tec) + list(nc), "diferenciais": list(dif), "soft_skills": [], "nivel": "nao_informado", "anos_experiencia_min": None}
    return comparar.analisar_vaga({"id": id_, "origem": "provedor", "provedor": "jsearch", "titulo": "Dev", "empresa": "E", "descricao": desc},
                                  {"extracao": ext, "metodo": "claude", "incompleta": False, "motivo": None}, set(), False)


def test_contagens_por_vaga_contam_habilidades_distintas():
    a = analisa("a", ["JS", "javascript", "JavaScript", "Docker"], ["Kafka", "Docker"])   # menções repetidas/aliases: 1 habilidade
    assert a["contagens"] == {"obrigatorios": 2, "diferenciais": 1, "nao_classificados": 0, "total": 3}   # Docker obrigatório vale como obrigatório
    assert len(a["requisitos"]["obrigatorios"]) == 2 and len(a["requisitos"]["diferenciais"]) == 1


def test_contagens_da_comparacao_somam_e_batem_com_as_listas():
    a, b = analisa("a", ["Python", "SQL"], ["Kafka"]), analisa("b", ["Python", "Go"], ["Kafka", "Terraform"])
    h = comparar.comparar(a, b)["habilidades"]
    c = h["contagens"]
    assert (c["comuns"], c["so_a"], c["so_b"]) == (len(h["comuns"]), len(h["so_a"]), len(h["so_b"])) == (2, 1, 2)
    assert c["total_distintas"] == c["comuns"] + c["so_a"] + c["so_b"] == 5       # categorias mutuamente exclusivas
    assert c["total_a"] == c["comuns"] + c["so_a"] == a["contagens"]["total"] and c["total_b"] == c["comuns"] + c["so_b"] == b["contagens"]["total"]


def test_contagem_zero_e_diferente_de_comparacao_indisponivel():
    vazia = analisa("v", [], [])
    assert vazia["contagens"]["total"] == 0 and vazia["status"] == "analisada"        # zero real (analisada, sem tecnologias)
    comp = comparar.comparar(vazia, analisa("b", ["Python"]))
    assert comp["habilidades"]["contagens"] == {"comuns": 0, "so_a": 0, "so_b": 1, "total_distintas": 1, "total_a": 0, "total_b": 1, "relacionadas": 0}
    sem = comparar.analisar_vaga({"id": "s", "titulo": "Dev", "empresa": "E", "descricao": ""}, None, set(), False)
    assert sem["status"] == "sem_descricao" and comparar.comparar(sem, vazia)["disponivel"] is False   # desconhecido != zero: nem há contagens


def test_nao_classificados_nao_viram_obrigatorios_nas_contagens():
    a = analisa("a", ["Python"], [], nc=[])
    ext = {"tecnologias": ["Python", "SQL"], "diferenciais": [], "soft_skills": [], "nivel": "nao_informado", "anos_experiencia_min": None}
    sem_marcador = comparar.analisar_vaga({"id": "m", "titulo": "Dev", "empresa": "E", "descricao": "Usamos Python e SQL no dia a dia do time. " * 8},
                                          {"extracao": ext, "metodo": "dicionario", "incompleta": False, "motivo": None}, set(), False)
    assert sem_marcador["contagens"] == {"obrigatorios": 0, "diferenciais": 0, "nao_classificados": 2, "total": 2}
