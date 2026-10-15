"""Grupos C/D/F — busca reversa com provedor SIMULADO (nenhuma chamada real a APIs externas)."""
import asyncio

import pytest

from app import cache, extract, reversa
from tests.falso_provedor import vaga


def buscar(client, habilidades, paginas=1, area=None):
    return client.post("/busca-habilidades", json={"habilidades": habilidades, "paginas": paginas, "area": area})


def jobs_padrao(query, page):
    return [
        vaga(f"{query}-{page}-1", "Dev Pleno", "Empresa A", ["Python", "Docker", "SQL"], ["Kubernetes"]),
        vaga(f"{query}-{page}-2", "Dev Pleno", "Empresa B", ["Python", "AWS"], ["Terraform", "Docker"]),
    ]


# ---------------- C1/C2/C8 — consultas
def test_c1_consultas_validas(client, provedor):
    p = reversa.planejar(["Python", "SQL", "React", "Docker"], area="Desenvolvimento Back-end", paginas=2)
    assert 1 <= len(p["consultas"]) <= reversa.MAX_CONSULTAS
    for c in p["consultas"]:
        assert c["texto"].startswith("Desenvolvimento Back-end ")
        assert 1 <= len(c["habilidades"]) <= 3
    assert sorted(h for c in p["consultas"] for h in c["habilidades"]) == ["Docker", "Python", "React", "SQL"]
    assert p["requisicoes_max"] == len(p["consultas"]) * 2


def test_c1_ordem_das_habilidades_nao_muda_a_consulta(client, provedor):
    a = reversa.planejar(["Python", "SQL", "React", "Docker", "Kotlin"])
    b = reversa.planejar(["Kotlin", "Docker", "react", "sql", "PYTHON"])
    assert [c["texto"] for c in a["consultas"]] == [c["texto"] for c in b["consultas"]]


def test_c2_respeita_o_provedor_configurado(client, provedor, monkeypatch):
    sk = ["Python", "SQL", "React", "Docker", "Kotlin", "Java"]
    assert max(len(c["habilidades"]) for c in reversa.planejar(sk)["consultas"]) == 3
    monkeypatch.setenv("PROVEDOR", "adzuna")
    p = reversa.planejar(sk)
    assert p["provedor"] == "adzuna" and max(len(c["habilidades"]) for c in p["consultas"]) == 2
    assert len(p["habilidades_na_busca"]) == 4 and len(p["habilidades_fora_da_busca"]) == 2


def test_c8_nunca_uma_requisicao_por_habilidade(client, provedor):
    provedor.resposta = jobs_padrao
    muitas = [f"Tecnologia{i}" for i in range(25)] + ["Python", "React"]
    r = buscar(client, muitas, paginas=2)
    assert r.status_code == 200
    assert len(provedor.chamadas) <= reversa.MAX_CONSULTAS * 2
    assert len(r.json()["consultas"]) <= reversa.MAX_CONSULTAS
    assert r.json()["habilidades_fora_da_busca"]  # as que não couberam são informadas


def test_plano_nao_chama_o_provedor_e_exige_habilidade(client, provedor):
    r = client.post("/busca-habilidades/plano", json={"habilidades": ["Python"], "paginas": 3})
    assert r.status_code == 200 and r.json()["requisicoes_max"] == 3 and provedor.chamadas == []
    vazio = client.post("/busca-habilidades/plano", json={"habilidades": []})
    assert vazio.status_code == 422 and "Informe ao menos uma habilidade" in vazio.json()["detail"]


# ---------------- A5 — perfil vazio, habilidades vindas direto da tela
def test_a5_busca_com_habilidades_da_tela_e_perfil_vazio(client, provedor):
    provedor.resposta = jobs_padrao
    assert client.get("/habilidades").json()["habilidades"] == []
    r = buscar(client, ["python", "Docker"])
    assert r.status_code == 200 and r.json()["estado"] == "ok" and r.json()["vagas"]


def test_a5_sem_habilidades_em_lugar_nenhum_explica_o_que_informar(client, provedor):
    r = client.post("/busca-habilidades", json={})
    assert r.status_code == 422 and "habilidade" in r.json()["detail"] and provedor.chamadas == []


def test_busca_usa_habilidades_salvas_quando_nao_enviadas(client, provedor):
    provedor.resposta = jobs_padrao
    client.put("/habilidades", json={"habilidades": ["Python", "SQL"]})
    r = client.post("/busca-habilidades", json={})
    assert r.status_code == 200 and r.json()["habilidades"] == ["Python", "SQL"]


# ---------------- C3 — páginas e cota
def test_c3_cota_esgotada_no_meio_vira_resultado_parcial(client, provedor, monkeypatch):
    provedor.resposta = jobs_padrao
    monkeypatch.setattr(cache, "QUOTA", 1)
    r = buscar(client, ["Python", "SQL"], paginas=2)
    assert r.status_code == 200
    d = r.json()
    assert len(provedor.chamadas) == 1 and cache.usado() == 1
    assert any("parcial" in a.lower() for a in d["avisos"]) and d["vagas"]
    assert d["pode_carregar_mais"] is True and d["requisicoes_feitas"] == 1


def test_c3_cota_zerada_devolve_mensagem_e_nao_chama(client, provedor, monkeypatch):
    monkeypatch.setattr(cache, "QUOTA", 0)
    r = buscar(client, ["Python"])
    assert r.status_code == 429 and "Cota" in r.json()["detail"] and provedor.chamadas == []


def test_c3_limite_de_paginas(client, provedor):
    assert buscar(client, ["Python"], paginas=reversa.MAX_PAGINAS + 1).status_code == 422
    provedor.resposta = jobs_padrao
    d = buscar(client, ["Python"], paginas=reversa.MAX_PAGINAS).json()
    assert d["pode_carregar_mais"] is False and d["max_paginas"] == reversa.MAX_PAGINAS


# ---------------- C4/C5 — cache
def test_c4_cache_reaproveitado_e_carregar_mais_so_paga_a_pagina_nova(client, provedor):
    provedor.resposta = jobs_padrao
    d1 = buscar(client, ["Python", "SQL"], paginas=1).json()
    assert len(provedor.chamadas) == 1 and d1["requisicoes_feitas"] == 1
    d2 = buscar(client, ["Python", "SQL"], paginas=1).json()
    assert len(provedor.chamadas) == 1 and d2["requisicoes_feitas"] == 0 and d2["do_cache"] == 1
    d3 = buscar(client, ["Python", "SQL"], paginas=2).json()  # "carregar mais": só a página 2 vai ao provedor
    assert len(provedor.chamadas) == 2 and d3["requisicoes_feitas"] == 1
    assert d3["contagens"]["unicas"] > d1["contagens"]["unicas"]


def test_c5_pesquisas_diferentes_nao_reaproveitam_resultado(client, provedor):
    provedor.resposta = jobs_padrao
    a = buscar(client, ["Python", "SQL"]).json()
    b = buscar(client, ["Kotlin", "Android"]).json()
    assert len(provedor.chamadas) == 2
    assert {v["id"] for v in a["vagas"]}.isdisjoint({v["id"] for v in b["vagas"]})


def test_c5_mesma_busca_com_habilidades_em_outra_ordem_reaproveita(client, provedor):
    provedor.resposta = jobs_padrao
    buscar(client, ["Python", "SQL", "Docker"])
    buscar(client, ["docker", "PYTHON", "sql"])
    assert len(provedor.chamadas) == 1


def test_c5_area_diferente_e_consulta_diferente(client, provedor):
    provedor.resposta = jobs_padrao
    buscar(client, ["Python"], area="Ciência de Dados")
    buscar(client, ["Python"], area="Engenharia de Dados")
    assert len(provedor.chamadas) == 2


# ---------------- C6 — deduplicação
def test_c6_dedup_sem_eliminar_anuncios_legitimos(client, provedor):
    provedor.resposta = lambda q, p: [
        vaga("id1", "Dev Backend", "Alfa", ["Python"]),
        vaga("id1", "Dev Backend", "Alfa", ["Python"]),                    # mesmo anúncio repetido: some
        vaga("id2", "Dev Backend", "Beta", ["Python"]),                    # mesmo título, outra empresa: fica
        vaga("id3", "Dev Backend", "Alfa", ["Python"], cidade="Recife"),   # mesmo título+empresa, outra vaga (id): fica
        vaga(None, "Dev Mobile", "Gama", ["Kotlin"], cidade="Porto Alegre"),
        vaga(None, "Dev Mobile", "Gama", ["Kotlin"], cidade="Curitiba"),   # sem id, local diferente: fica
        vaga(None, "Dev Mobile", "Gama", ["Kotlin"], cidade="Curitiba"),   # sem id, repetida: some
    ]
    d = buscar(client, ["Python", "Kotlin"]).json()
    assert d["contagens"]["retornadas"] == 7 and d["contagens"]["unicas"] == 5
    assert sorted((v["titulo"], v["empresa"], v["local"]) for v in d["vagas"]).count(("Dev Backend", "Alfa", "São Paulo, SP, BR")) == 1


def test_c6_mesma_vaga_vinda_de_duas_consultas_conta_uma_vez(client, provedor):
    provedor.resposta = lambda q, p: [vaga("compartilhada", "Dev", "Alfa", ["Python", "React"]), vaga(f"so-{q}", "Dev", "Beta", ["SQL"])]
    d = buscar(client, ["Python", "React", "SQL", "Docker"]).json()
    assert len(d["consultas"]) == 2
    assert [v["id"] for v in d["vagas"]].count("id:compartilhada") == 1


# ---------------- C7 — páginas vazias / resultados insuficientes
def test_c7_nenhuma_vaga_nao_entra_em_ciclo_e_explica(client, provedor):
    provedor.resposta = lambda q, p: []
    d = buscar(client, ["Python", "SQL"], paginas=3).json()
    assert d["estado"] == "sem_vagas" and d["vagas"] == [] and d["contagens"]["retornadas"] == 0
    assert len(provedor.chamadas) == 3  # exatamente as páginas pedidas, nada além
    assert d["lacunas"]["itens"] == []


def test_c7_descricao_curta_vira_dados_insuficientes_nao_nota_baixa(client, provedor):
    provedor.resposta = lambda q, p: [vaga("curta", descricao="Vaga de dev."), vaga("ok", obrigatorios=["Python", "SQL", "Docker"])]
    d = buscar(client, ["Python"]).json()
    por_id = {v["id"]: v for v in d["vagas"]}
    assert por_id["id:curta"]["estado"] == "dados_insuficientes" and por_id["id:curta"]["compatibilidade"] is None
    assert d["contagens"]["dados_insuficientes"] == 1 and d["contagens"]["avaliadas"] == 1
    assert d["vagas"][-1]["id"] == "id:curta"  # sem nota: vai para o fim, sem posição por pontuação artificial
    assert d["lacunas"]["base"] == 1  # só vagas avaliadas entram na base de frequência


# ---------------- Resultado completo e transparência
def test_resultado_explica_a_pontuacao(client, provedor):
    provedor.resposta = lambda q, p: [vaga("v1", "Dev", "Alfa", ["JavaScript", "Java", "Docker"], ["Kubernetes", "TypeScript"])]
    d = buscar(client, ["JS", "Docker", "TS"]).json()
    v = d["vagas"][0]
    assert v["compatibilidade"] == 62.5 and v["requisitos_total"] == 5
    assert v["obrigatorios_correspondidos"] == 2 and v["diferenciais_correspondidos"] == 1
    assert v["correspondencias"] == ["JavaScript", "Docker", "TypeScript"]
    assert v["faltando_obrigatorios"] == ["Java"] and v["faltando_diferenciais"] == ["Kubernetes"]
    assert v["local"] == "São Paulo, SP, BR" and v["link"] == "https://exemplo.test/vaga"
    lac = {i["nome"]: i for i in d["lacunas"]["itens"]}
    assert lac["Java"]["como_obrigatoria"] == 1 and lac["Kubernetes"]["como_diferencial"] == 1 and lac["Java"]["percentual"] == 100


def test_f2_links_somente_http_https(client, provedor):
    provedor.resposta = lambda q, p: [
        vaga("a", obrigatorios=["Python", "SQL", "Docker"], link="javascript:alert(1)"),
        vaga("b", obrigatorios=["Python", "SQL", "Docker"], link="https://ok.test/x?y=1"),
        vaga("c", obrigatorios=["Python", "SQL", "Docker"], link=None),
    ]
    links = {v["id"]: v["link"] for v in buscar(client, ["Python"]).json()["vagas"]}
    assert links == {"id:a": None, "id:b": "https://ok.test/x?y=1", "id:c": None}


# ---------------- D — extração por vaga
def fake_extrair_factory(falhar=()):
    async def fake(v):
        # tempos diferentes para a ordem de conclusão ser diferente da ordem de entrada
        await asyncio.sleep({"j1": 0.05, "j2": 0.0, "j3": 0.02}.get(v["id"].split(":")[-1], 0))
        if v["id"].split(":")[-1] in falhar:
            return None
        return {"tecnologias": {"j1": ["Python"], "j2": ["Kotlin"], "j3": ["Rust"]}[v["id"].split(":")[-1]],
                "diferenciais": [], "soft_skills": [], "nivel": "pleno", "anos_experiencia_min": None}
    return fake


def _tres_vagas(q, p):
    return [vaga(j, f"Vaga {j}", "E", obrigatorios=["Go", "Perl", "Lua"]) for j in ("j1", "j2", "j3")]


def test_d1_extracao_parcial_nao_desalinha_vagas(client, provedor, monkeypatch):
    provedor.resposta = _tres_vagas
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    monkeypatch.setattr(extract, "extrair", fake_extrair_factory(falhar={"j2"}))  # só a j2 falha
    d = buscar(client, ["Python", "Kotlin", "Rust"]).json()
    v = {x["titulo"]: x for x in d["vagas"]}
    assert v["Vaga j1"]["correspondencias"] == ["Python"] and v["Vaga j1"]["metodo"] == "claude"
    assert v["Vaga j3"]["correspondencias"] == ["Rust"] and v["Vaga j3"]["metodo"] == "claude"
    # j2: falha da IA -> dicionário só para ela (Go/Perl/Lua da descrição), marcada como incompleta
    assert v["Vaga j2"]["metodo"] == "dicionario" and v["Vaga j2"]["analise_incompleta"] is True
    assert "Kotlin" not in v["Vaga j2"]["correspondencias"]  # nada herdado da extração de outra vaga
    assert any("IA falhou" in a for a in v["Vaga j2"]["avisos"])
    assert d["contagens"]["analise_incompleta"] == 1


def test_d2_falha_total_da_ia_cai_no_dicionario_por_vaga(client, provedor, monkeypatch):
    provedor.resposta = _tres_vagas
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    monkeypatch.setattr(extract, "extrair", fake_extrair_factory(falhar={"j1", "j2", "j3"}))
    d = buscar(client, ["Go"]).json()
    assert all(v["metodo"] == "dicionario" and v["analise_incompleta"] for v in d["vagas"])
    assert all(v["requisitos_total"] > 0 for v in d["vagas"])


def test_d2_resultado_invalido_da_ia_e_tratado_como_falha(client, provedor, monkeypatch):
    provedor.resposta = lambda q, p: [vaga("j1", "Vaga j1", "E", obrigatorios=["Go", "Perl", "Lua"])]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")

    async def lixo(v):
        return "isso não é um dict"

    monkeypatch.setattr(extract, "extrair", lixo)
    d = buscar(client, ["Go"]).json()
    assert d["vagas"][0]["metodo"] == "dicionario" and d["vagas"][0]["analise_incompleta"]


def test_d3_nao_inventa_requisitos(client, provedor):
    provedor.resposta = lambda q, p: [vaga("x", descricao="Procuramos alguém muito dedicado e proativo. " * 10)]
    v = buscar(client, ["Python"]).json()["vagas"][0]
    assert v["requisitos_total"] == 0 and v["estado"] == "dados_insuficientes" and v["compatibilidade"] is None
    assert v["faltando_obrigatorios"] == [] and v["correspondencias"] == []


def test_extracao_dicionario_sem_ia_nao_e_marcada_incompleta(client, provedor):
    provedor.resposta = lambda q, p: [vaga("x", obrigatorios=["Python", "SQL", "Docker"])]
    v = buscar(client, ["Python"]).json()["vagas"][0]
    assert v["metodo"] == "dicionario" and v["analise_incompleta"] is False


def test_d4_cache_de_extracao_evita_nova_chamada_a_ia(client, provedor, monkeypatch):
    provedor.resposta = _tres_vagas
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    n = {"c": 0}
    base = fake_extrair_factory()

    async def contando(v):
        n["c"] += 1
        return await base(v)

    monkeypatch.setattr(extract, "extrair", contando)
    buscar(client, ["Python"], paginas=1)
    buscar(client, ["Python"], paginas=1)
    assert n["c"] == 3


# ---------------- F3 — erros de API e credenciais
def test_f3_credenciais_ausentes(client, provedor, monkeypatch):
    monkeypatch.delenv("OPENWEBNINJA_API_KEY")
    r = buscar(client, ["Python"])
    assert r.status_code == 503 and "OPENWEBNINJA_API_KEY" in r.json()["detail"] and "indisponível" in r.json()["detail"]
    assert provedor.chamadas == [] and "chave-de-teste" not in r.text


@pytest.mark.parametrize("status,esperado", [(401, 502), (403, 502), (429, 429), (503, 502)])
def test_f3_erros_do_provedor_viram_mensagens_tratadas(client, provedor, monkeypatch, status, esperado):
    async def sem_espera(*a, **k):
        return None

    monkeypatch.setattr(asyncio, "sleep", sem_espera)
    provedor.status = status
    r = buscar(client, ["Python"])
    assert r.status_code == esperado and isinstance(r.json()["detail"], str)
    assert "chave-de-teste" not in r.text


def test_f3_falha_de_uma_consulta_nao_derruba_a_outra(client, provedor):
    provedor.resposta = jobs_padrao
    provedor.falha = lambda params: 401 if "Python" in params["query"] else None  # só a consulta com Python falha
    d = buscar(client, ["Python", "React", "SQL", "Docker"]).json()
    assert d["estado"] == "ok" and d["vagas"]
    assert any("falhou" in a and "recusou a chave" in a for a in d["avisos"])
    assert "chave-de-teste" not in str(d)


def test_f3_todas_as_consultas_falham_devolve_erro(client, provedor):
    provedor.falha = lambda params: 401
    r = buscar(client, ["Python", "React", "SQL", "Docker"])
    assert r.status_code == 502 and "recusou a chave" in r.json()["detail"]


# ---------------- F5/F6 — separação da busca tradicional e do histórico
def test_f5_busca_tradicional_continua_e_nao_mistura_historico(client, provedor):
    desc = "Requisitos: Python, Docker, SQL e AWS. " + "Atuação em squads de produto digital com foco em qualidade. " * 4
    provedor.resposta = lambda q, p: [vaga(f"t-{q}-{p}-{i}", f"Dev {i}", f"Emp{i}", descricao=desc) for i in range(3)]
    antes = client.post("/chat", json={"mensagem": "desenvolvedor python", "paginas": 1})
    assert antes.status_code == 200 and "Python" in antes.json()["resposta"]
    from app import db
    prog = db.consultar("SELECT consulta, ultima_pagina FROM progresso")
    vistas = db.consultar("SELECT count(*) FROM vistas")[0][0]
    buscar(client, ["Python", "SQL"], paginas=2)
    buscar(client, ["Python", "SQL"], paginas=3)
    assert db.consultar("SELECT consulta, ultima_pagina FROM progresso") == prog  # busca por habilidades não mexe nisso
    assert db.consultar("SELECT count(*) FROM vistas")[0][0] == vistas
    # e o contrário: nova busca por cargo não altera o resultado da busca por habilidades
    client.post("/chat", json={"mensagem": "desenvolvedor python", "paginas": 1, "apenas_novas": True})
    again = buscar(client, ["Python", "SQL"], paginas=2).json()
    assert again["requisicoes_feitas"] == 0 and again["estado"] == "ok"


def test_f6_cota_unica_compartilhada(client, provedor):
    provedor.resposta = jobs_padrao
    client.post("/chat", json={"mensagem": "qa", "paginas": 1})
    usado = cache.usado()
    buscar(client, ["Go", "Rust"], paginas=1)
    assert cache.usado() == usado + 1 == client.get("/status").json()["usado"]


def test_privacidade_so_consulta_vai_ao_provedor(client, provedor):
    provedor.resposta = jobs_padrao
    client.put("/perfil", json={"nome": "Nome Secreto Da Pessoa", "areas": ["Area Secreta Y"]})
    buscar(client, ["Python", "SQL"])
    enviado = str(provedor.chamadas)
    assert "Nome Secreto" not in enviado and "Area Secreta" not in enviado
    assert set(provedor.chamadas[0]) <= {"query", "page", "num_pages", "country", "date_posted"}
