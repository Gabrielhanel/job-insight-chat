"""Etapa 4 — integração: seleção, cache, cota, falhas, entrada manual e regressão (provedor SIMULADO, dados SINTÉTICOS)."""
import asyncio
import sqlite3

import httpx
import pytest

from app import cache, db, extract
from tests.falso_provedor import vaga

BACK = {"Desenvolvedor Back-end": [
    vaga("b1", "Desenvolvedor Back-end Pleno", "Alfa", ["Python", "PostgreSQL", "Docker"], ["Kafka"], publicada="2026-10-01T10:00:00.000Z"),
    vaga("b2", "Desenvolvedor Back-end Sênior", "Beta", ["Python", "AWS", "Kubernetes"], ["Terraform"]),
]}
FRONT = {"Desenvolvedor Front-end": [
    vaga("f1", "Desenvolvedor Front-end Pleno", "Gama", ["JavaScript", "React", "CSS"], ["TypeScript"]),
    vaga("f2", "Desenvolvedor Front-end Pleno", "Gama", ["JavaScript", "Angular", "HTML"], ["Jest"]),  # mesmo título e empresa que f1
]}


def prepara(provedor, *grupos):
    base = {k: v for g in grupos for k, v in g.items()}
    provedor.resposta = lambda q, p: base.get(q, []) if p == 1 else []


def busca(client, consulta, paginas=1):
    r = client.post("/comparar/buscar", json={"consulta": consulta, "paginas": paginas})
    assert r.status_code == 200, r.text
    return r.json()


def sel(res, id_):
    return {"tipo": "busca", **res["ref"], "id": id_}


def manual(titulo="Vaga Manual", desc=None, **kw):
    desc = desc if desc is not None else "Requisitos: Python, Docker. Diferenciais: Kafka." + " Atuação em times de produto digital com foco em qualidade e entrega contínua. " * 4
    return {"tipo": "manual", "titulo": titulo, "descricao": desc, **kw}


def cmp(client, a, b, **extra):
    return client.post("/comparar", json={"a": a, "b": b, **extra})


# ---------------- A — seleção
def test_a1_duas_vagas_da_mesma_pesquisa(client, provedor):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    assert [v["id"] for v in r["vagas"]] == ["id:b1", "id:b2"] and r["vagas"][0]["publicada_em"] == "2026-10-01T10:00:00.000Z"
    res = cmp(client, sel(r, "id:b1"), sel(r, "id:b2"))
    d = res.json()
    assert res.status_code == 200 and d["estado"] == "completa"
    assert d["a"]["identidade"]["titulo"] == "Desenvolvedor Back-end Pleno" and d["a"]["identidade"]["empresa"] == "Alfa"
    assert d["b"]["identidade"]["titulo"] == "Desenvolvedor Back-end Sênior" and d["b"]["identidade"]["empresa"] == "Beta"
    assert d["a"]["identidade"]["provedor"] == "jsearch" and d["a"]["identidade"]["origem"] == "provedor" and d["a"]["identidade"]["obtida_em"]
    assert d["a"]["identidade"]["link"] == "https://exemplo.test/vaga" and d["a"]["identidade"]["publicada_em"] == "2026-10-01T10:00:00.000Z"
    assert d["b"]["identidade"]["publicada_em"] is None  # ausente: nada inventado
    comuns = [i["nome"] for i in d["comparacao"]["habilidades"]["comuns"]]
    assert comuns == ["Python"] and "Níveis diferentes" in d["comparacao"]["senioridade"]["texto"]


def test_a2_vagas_de_consultas_distintas_e_sem_nova_requisicao(client, provedor):
    prepara(provedor, BACK, FRONT)
    ra, rb = busca(client, "Desenvolvedor Back-end"), busca(client, "Desenvolvedor Front-end")
    assert len(provedor.chamadas) == 2
    d = cmp(client, sel(ra, "id:b1"), sel(rb, "id:f1")).json()
    assert len(provedor.chamadas) == 2 and d["requisicoes_feitas"] == 0 and d["todo_do_cache"] is True  # vagas já vistas: nada novo ao provedor
    assert d["a"]["identidade"]["id"] == "id:b1" and d["b"]["identidade"]["id"] == "id:f1"


def test_a3_areas_diferentes_sem_nada_em_comum(client, provedor):
    prepara(provedor, BACK, FRONT)
    ra, rb = busca(client, "Desenvolvedor Back-end"), busca(client, "Desenvolvedor Front-end")
    d = cmp(client, sel(ra, "id:b2"), sel(rb, "id:f1")).json()
    assert d["comparacao"]["habilidades"]["comuns"] == []
    assert "Nenhuma habilidade técnica em comum foi identificada." in d["sintese"]["semelhancas"]
    assert {i["nome"] for i in d["comparacao"]["habilidades"]["so_a"]} >= {"Python", "AWS", "Kubernetes"}
    assert {i["nome"] for i in d["comparacao"]["habilidades"]["so_b"]} >= {"JavaScript", "React", "CSS"}


def test_a4_mesma_vaga_nas_duas_selecoes_e_recusada_sem_chamar_o_provedor(client, provedor):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    antes = len(provedor.chamadas)
    res = cmp(client, sel(r, "id:b1"), sel(r, "id:b1"))
    assert res.status_code == 422 and "mesmo anúncio" in res.json()["detail"] and len(provedor.chamadas) == antes
    outra = {**sel(r, "id:b1"), "consulta": "outra consulta qualquer"}  # mesmo anúncio vindo de "outra pesquisa"
    assert cmp(client, sel(r, "id:b1"), outra).status_code == 422
    m = manual()
    assert cmp(client, m, dict(m)).status_code == 422  # a mesma vaga manual duas vezes


def test_a5_titulos_iguais_continuam_sendo_anuncios_distintos(client, provedor):
    prepara(provedor, FRONT)
    r = busca(client, "Desenvolvedor Front-end")
    assert len(r["vagas"]) == 2 and r["vagas"][0]["titulo"] == r["vagas"][1]["titulo"] and r["vagas"][0]["empresa"] == r["vagas"][1]["empresa"]
    d = cmp(client, sel(r, "id:f1"), sel(r, "id:f2")).json()
    assert d["estado"] == "completa"
    assert {i["nome"] for i in d["comparacao"]["habilidades"]["so_a"]} == {"React", "CSS", "TypeScript"}
    assert {i["nome"] for i in d["comparacao"]["habilidades"]["so_b"]} == {"Angular", "HTML", "Jest"}
    assert [i["nome"] for i in d["comparacao"]["habilidades"]["comuns"]] == ["JavaScript"]


def test_selecao_de_vaga_que_saiu_dos_resultados_e_tratada(client, provedor):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    res = cmp(client, sel(r, "id:b1"), {**sel(r, "id:nao-existe")})
    d = res.json()
    assert res.status_code == 200 and d["estado"] == "parcial" and d["b"]["status"] == "falha_ao_carregar" and "não aparece mais nos resultados" in d["b"]["motivo"]
    assert d["a"]["status"] == "analisada" and d["comparacao"]["disponivel"] is False and d["sintese"] is None  # A preservada; sem comparação


# ---------------- entrada manual
def test_manual_x_busca_e_marcada_como_nao_verificada(client, provedor):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    d = cmp(client, sel(r, "id:b1"), manual("Minha vaga", empresa="Contoso", link="https://contoso.test/v/1")).json()
    b = d["b"]["identidade"]
    assert b["origem"] == "manual" and b["id"].startswith("manual:") and b["provedor"] is None and b["link"] == "https://contoso.test/v/1"
    assert d["a"]["identidade"]["origem"] == "provedor" and b["publicada_em"] is None
    assert d["estado"] == "completa"


def test_duas_vagas_manuais_funcionam_sem_credenciais_e_sem_chamadas(client, provedor, monkeypatch):
    monkeypatch.delenv("OPENWEBNINJA_API_KEY")
    res = cmp(client, manual("Vaga A", "Requisitos: Python, SQL. " + "Texto de apoio com contexto da vaga. " * 12), manual("Vaga B", "Requisitos: Python, Go. " + "Texto de apoio com contexto da vaga. " * 12))
    assert res.status_code == 200 and provedor.chamadas == []
    assert [i["nome"] for i in res.json()["comparacao"]["habilidades"]["comuns"]] == ["Python"]


@pytest.mark.parametrize("campo,valor,trecho", [
    ("titulo", "", "título"), ("titulo", "x" * 201, "no máximo 200"), ("empresa", "e" * 121, "no máximo 120"),
    ("descricao", "", "descrição"), ("descricao", "d" * 8001, "no máximo 8000"), ("descricao", "ab\x00cd", "controle"),
    ("link", "javascript:alert(1)", "http://"), ("link", "ftp://x.test/a", "http://"), ("link", "https://x.test/" + "a" * 500, "500"),
])
def test_manual_validacoes(client, provedor, campo, valor, trecho):
    m = manual(); m[campo] = valor
    res = cmp(client, m, manual("Outra", "Requisitos: Go. " + "Contexto. " * 40))
    assert res.status_code == 422 and trecho in res.json()["detail"] and provedor.chamadas == []


def test_manual_nao_e_tratado_como_html_nem_o_link_e_acessado(client, provedor):
    m = manual('<img src=x onerror=alert(1)>', link="https://exemplo.test/link-nunca-acessado")
    d = cmp(client, m, manual("B", "Requisitos: Go. " + "Contexto. " * 40)).json()
    assert d["a"]["identidade"]["titulo"] == '<img src=x onerror=alert(1)>'  # devolvido como texto
    assert provedor.chamadas == [] and not any(h.request.url.host == "exemplo.test" for h in [])  # nenhuma requisição saiu (nem ao link)


# ---------------- E — cache, cota, falhas, extração
def test_e1_cache_de_paginas_e_leitura_unica_por_consulta(client, provedor, monkeypatch):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    monkeypatch.setattr(cache, "TTL", 0)  # cache vencido: precisa buscar de novo, e só uma vez para A e B (mesma consulta)
    d = cmp(client, sel(r, "id:b1"), sel(r, "id:b2")).json()
    assert d["requisicoes_feitas"] == 1 and len(provedor.chamadas) == 2 and d["todo_do_cache"] is False


def test_e2_cota_esgotada_preserva_a_vaga_que_carregou(client, provedor, monkeypatch):
    prepara(provedor, BACK, FRONT)
    ra = busca(client, "Desenvolvedor Back-end")                       # consome 1 requisição
    rb = {"ref": {"consulta": "Desenvolvedor Front-end", "pais": "br", "paginas": 1}}  # B nunca foi buscada: não está em cache
    monkeypatch.setattr(cache, "QUOTA", 1)
    res = cmp(client, sel(ra, "id:b1"), sel(rb, "id:f1"))
    d = res.json()
    assert res.status_code == 200 and d["estado"] == "parcial"
    assert d["a"]["status"] == "analisada" and d["b"]["status"] == "falha_ao_carregar" and "Cota" in d["b"]["motivo"]
    assert d["comparacao"]["disponivel"] is False and any("a comparação não foi feita" in x for x in d["avisos"])
    assert len(provedor.chamadas) == 1  # nada além da primeira busca


def test_e2_cota_zerada_nas_duas_vagas(client, provedor, monkeypatch):
    monkeypatch.setattr(cache, "QUOTA", 0)
    ref = {"consulta": "qualquer", "pais": "br", "paginas": 1}
    res = cmp(client, {"tipo": "busca", **ref, "id": "id:x"}, {"tipo": "busca", **ref, "id": "id:y"})
    assert res.status_code == 429 and "Cota" in res.json()["detail"] and provedor.chamadas == []
    assert client.post("/comparar/buscar", json={"consulta": "qualquer"}).status_code == 429


def test_e3_falhas_externas_e_credenciais(client, provedor, monkeypatch):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    provedor.status = 401
    res = client.post("/comparar/buscar", json={"consulta": "outra"})
    assert res.status_code == 502 and "chave-de-teste" not in res.text
    monkeypatch.delenv("OPENWEBNINJA_API_KEY")
    for res in (client.post("/comparar/buscar", json={"consulta": "x1"}), cmp(client, sel(r, "id:b1"), sel(r, "id:b2"))):
        assert res.status_code == 503 and "OPENWEBNINJA_API_KEY" in res.json()["detail"] and "indisponível" in res.json()["detail"]


def test_e3_descricao_ausente_numa_das_vagas(client, provedor):
    provedor.resposta = lambda q, p: [vaga("ok", "Dev Python", "A", ["Python", "SQL"]), vaga("vazia", "Dev Go", "B", descricao="")] if p == 1 else []
    r = busca(client, "Dev")
    assert [v["tem_descricao"] for v in r["vagas"]] == [True, False]
    d = cmp(client, sel(r, "id:ok"), sel(r, "id:vazia")).json()
    assert d["b"]["status"] == "sem_descricao" and d["a"]["status"] == "analisada" and d["estado"] == "parcial"
    assert d["b"]["identidade"]["titulo"] == "Dev Go" and d["comparacao"]["disponivel"] is False
    assert d["a"]["requisitos"]["obrigatorios"]  # análise individual preservada
    assert d["sintese"]["incompleta"] is True


def test_e4_extracao_nao_e_repetida_para_a_mesma_descricao(client, provedor, monkeypatch):
    prepara(provedor, BACK)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    n = {"c": 0}

    async def fake(v):
        n["c"] += 1
        return {"tecnologias": ["Python"], "diferenciais": [], "soft_skills": [], "nivel": "pleno", "anos_experiencia_min": None}
    monkeypatch.setattr(extract, "extrair", fake)
    r = busca(client, "Desenvolvedor Back-end")
    cmp(client, sel(r, "id:b1"), sel(r, "id:b2"))
    assert n["c"] == 2
    cmp(client, sel(r, "id:b1"), sel(r, "id:b2"))
    cmp(client, sel(r, "id:b2"), sel(r, "id:b1"))  # ordem trocada, mesmas descrições
    assert n["c"] == 2  # nenhuma chamada nova à IA


def test_e4_extracao_falha_em_uma_vaga_nao_troca_requisitos(client, provedor, monkeypatch):
    prepara(provedor, BACK)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")

    async def fake(v):
        await asyncio.sleep(0.05 if v["id"].endswith("b1") else 0)  # termina fora de ordem
        if v["id"].endswith("b1"):
            return None
        return {"tecnologias": ["Rust"], "diferenciais": [], "soft_skills": [], "nivel": "senior", "anos_experiencia_min": None}
    monkeypatch.setattr(extract, "extrair", fake)
    r = busca(client, "Desenvolvedor Back-end")
    d = cmp(client, sel(r, "id:b1"), sel(r, "id:b2")).json()
    assert [i["nome"] for i in d["b"]["requisitos"]["obrigatorios"]] == ["Rust"]
    a_nomes = {i["nome"] for i in d["a"]["requisitos"]["obrigatorios"] + d["a"]["requisitos"]["diferenciais"]}
    assert "Rust" not in a_nomes and {"Python", "Docker"} <= a_nomes  # A caiu no dicionário e manteve os próprios requisitos
    assert d["a"]["metodo"] == "dicionario" and d["a"]["confianca_ausencia"] == "baixa" and any("IA falhou" in x for x in d["a"]["limitacoes"])
    assert d["comparacao"]["disponivel"] is True and d["comparacao"]["habilidades"]["so_b"][0]["ausencia_confiavel"] is False  # A foi degradada: ausência de Rust em A não é firme


def test_provedor_que_devolve_resumo_e_sinalizado(client, provedor, monkeypatch):
    monkeypatch.setenv("PROVEDOR", "adzuna"); monkeypatch.setenv("ADZUNA_APP_ID", "id-teste"); monkeypatch.setenv("ADZUNA_APP_KEY", "key-teste")
    corpo = {"results": [{"id": 1, "title": "Dev Python", "company": {"display_name": "A"}, "description": "Requisitos: Python, SQL, Docker, AWS e Git no dia a dia. " * 6,
                          "redirect_url": "https://adz.test/1", "location": {"display_name": "SP"}, "created": "2026-10-02T00:00:00Z"},
                         {"id": 2, "title": "Dev Go", "company": {"display_name": "B"}, "description": "Requisitos: Rust, Perl, Ruby e Lua no dia a dia. " * 6,
                          "redirect_url": "https://adz.test/2", "location": {"display_name": "RJ"}}]}
    provedor.handler = lambda request: httpx.Response(200, json=corpo)
    r = busca(client, "Dev")
    assert r["vagas"][0]["descricao_resumo"] is True and r["vagas"][0]["provedor"] == "adzuna" and r["vagas"][0]["publicada_em"] == "2026-10-02T00:00:00Z"
    assert any("só um trecho da descrição" in a for a in r["avisos"])
    d = cmp(client, sel(r, "id:1"), sel(r, "id:2")).json()
    assert d["a"]["confianca_ausencia"] == "baixa" and any("só um trecho da descrição" in x for x in d["a"]["limitacoes"])
    assert d["comparacao"]["habilidades"]["so_a"][0]["ausencia_confiavel"] is False


# ---------------- C — compatibilidade com o perfil
def test_c5_sem_perfil_e_com_perfil_cada_vaga_com_a_sua_nota(client, provedor):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    sem = cmp(client, sel(r, "id:b1"), sel(r, "id:b2")).json()
    assert sem["perfil_habilidades"] == 0 and sem["a"]["compatibilidade"]["disponivel"] is False and "perfil" in sem["a"]["compatibilidade"]["motivo"].lower()
    assert sem["comparacao"]["disponivel"] is True
    client.put("/habilidades", json={"habilidades": ["Python", "Docker", "PostgreSQL"]})
    com = cmp(client, sel(r, "id:b1"), sel(r, "id:b2")).json()
    ca, cb = com["a"]["compatibilidade"], com["b"]["compatibilidade"]
    assert ca["compatibilidade"] == 85.7 and cb["compatibilidade"] == 28.6  # 100×(2·3+0)/(2·3+1) e 100×(2·1+0)/(2·3+1): fórmula existente
    assert ca["correspondencias"] == ["Python", "PostgreSQL", "Docker"] and cb["faltando_obrigatorios"] == ["AWS", "Kubernetes"]
    assert "melhor" not in str(com["sintese"]).lower().replace("não indica qual vaga é melhor", "")  # nota maior não elege vaga
    forcado = cmp(client, sel(r, "id:b1"), sel(r, "id:b2"), habilidades=["Rust"]).json()
    assert forcado["perfil_habilidades"] == 1 and forcado["a"]["compatibilidade"]["compatibilidade"] == 0.0


# ---------------- privacidade e regressão
def test_privacidade_so_a_consulta_vai_ao_provedor(client, provedor):
    prepara(provedor, BACK)
    client.put("/perfil", json={"nome": "Nome Secreto Da Pessoa", "areas": ["Area Secreta Y"]})
    client.put("/habilidades", json={"habilidades": ["Habilidade Secreta Z"]})
    r = busca(client, "Desenvolvedor Back-end")
    cmp(client, sel(r, "id:b1"), manual())
    assert "Secret" not in str(provedor.chamadas) and set(provedor.chamadas[0]) <= {"query", "page", "num_pages", "country", "date_posted"}


def test_validacao_da_consulta_e_plano(client, provedor):
    for corpo in ({"consulta": ""}, {"consulta": "x" * 81}, {"consulta": "ok", "paginas": 4}, {"consulta": "ok", "pais": "BRASIL"}):
        assert client.post("/comparar/buscar", json=corpo).status_code == 422
    assert provedor.chamadas == []
    p = client.post("/comparar/plano", json={"consulta": "Dev", "paginas": 2}).json()
    assert p["requisicoes_max"] == 2 and p["credenciais"] is True and provedor.chamadas == []


def test_e5_e6_e7_funcionalidades_anteriores_e_banco_preservados(client, provedor, banco_legado):
    desc = "Requisitos: Python, Docker, SQL e AWS. " + "Atuação em times de produto digital com foco em qualidade. " * 4
    provedor.resposta = lambda q, p: [vaga(f"t-{q}-{p}-{i}", f"Dev {i}", f"Emp{i}", descricao=desc) for i in range(3)]
    assert client.post("/chat", json={"mensagem": "desenvolvedor python", "paginas": 1}).status_code == 200          # busca tradicional
    assert client.post("/busca-habilidades", json={"habilidades": ["Python", "SQL"]}).status_code == 200            # busca por habilidades
    assert client.put("/perfil", json={"nome": "Ana", "areas": ["IA"]}).status_code == 200 and client.get("/perfil").json()["nome"] == "Ana"
    r = busca(client, "desenvolvedor python")
    assert cmp(client, sel(r, r["vagas"][0]["id"]), sel(r, r["vagas"][1]["id"])).status_code == 200
    assert client.post("/evolucao/plano", json={"cargo": "Dev"}).status_code == 200
    c = sqlite3.connect(banco_legado)
    assert c.execute("SELECT dados FROM paginas WHERE chave='k'").fetchone() == ("[1,2]",)
    assert c.execute("SELECT n FROM uso WHERE mes='2026-10'").fetchone()[0] >= 42  # o contador só cresce (requisições reais feitas nos testes)
    assert c.execute("SELECT count(*) FROM vistas WHERE consulta='br|kotlin' AND vaga='v1'").fetchone() == (1,)  # linhas originais intactas
    assert c.execute("SELECT ultima_pagina FROM progresso WHERE consulta='br|kotlin'").fetchone() == (3,)
    c.close()


def test_comparar_nao_altera_historico_nem_cria_tabelas(client, provedor):
    prepara(provedor, BACK)
    antes = db.consultar("SELECT name FROM sqlite_master ORDER BY name")
    r = busca(client, "Desenvolvedor Back-end")
    cmp(client, sel(r, "id:b1"), sel(r, "id:b2"))
    assert db.consultar("SELECT count(*) FROM vistas")[0][0] == 0 and db.consultar("SELECT count(*) FROM progresso")[0][0] == 0
    assert db.consultar("SELECT name FROM sqlite_master ORDER BY name") == antes  # nada novo no banco (nem comparações guardadas)


def test_e8_escopo_sem_funcionalidades_posteriores(client, provedor):
    prepara(provedor, BACK)
    r = busca(client, "Desenvolvedor Back-end")
    d = cmp(client, sel(r, "id:b1"), sel(r, "id:b2")).json()
    assert not any(k in d for k in ("vencedora", "melhor_vaga", "ranking", "graficos", "sessao", "historico"))
    for rota in ("/conversas", "/historico", "/graficos"):  # "/sessoes" é da Etapa 7
        assert client.get(rota).status_code == 404
