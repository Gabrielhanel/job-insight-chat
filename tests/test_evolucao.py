"""Etapa 3 — integração: coleta por nível, classificação, rankings e estados (provedor SIMULADO, dados SINTÉTICOS)."""
import asyncio

import pytest

from app import cache, db, evolucao, extract
from tests.falso_provedor import vaga

ROT = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior"}


def nivel_da_consulta(query):
    q = query.lower()
    return "junior" if "júnior" in q or "junior" in q else ("pleno" if "pleno" in q or "mid-level" in q else "senior")


def jobs_sinteticos(n_por_nivel=(10, 10, 10)):
    """n vagas por nível, todas 'React Native'. TypeScript: 2/4/8 de 10; Git: 10/7/3; JavaScript: todas."""
    cfg = {"junior": dict(ts=2, git=10), "pleno": dict(ts=4, git=7), "senior": dict(ts=8, git=3)}

    def resposta(query, page):
        nv = nivel_da_consulta(query)
        if page != 1:
            return []
        n = n_por_nivel[("junior", "pleno", "senior").index(nv)]
        out = []
        for i in range(n):
            obrig = ["React Native", "JavaScript"] + (["TypeScript"] if i < cfg[nv]["ts"] else []) + (["Git"] if i < cfg[nv]["git"] else [])
            out.append(vaga(f"{nv}-{i}", f"Desenvolvedor React Native {ROT[nv]}", f"Empresa {nv}{i}", obrig, ["Docker"] if i < 2 else []))
        return out
    return resposta


def analisar(client, cargo="Desenvolvedor React Native", paginas=1, **extra):
    return client.post("/evolucao", json={"cargo": cargo, "paginas": paginas, **extra})


# ---------------- plano e coleta (E1)
def test_plano_tres_consultas_um_por_nivel_sem_chamar_o_provedor(client, provedor):
    r = client.post("/evolucao/plano", json={"cargo": "Desenvolvedor React Native", "paginas": 2})
    d = r.json()
    assert r.status_code == 200 and provedor.chamadas == []
    assert [c["texto"] for c in d["consultas"]] == ["Desenvolvedor React Native júnior", "Desenvolvedor React Native pleno", "Desenvolvedor React Native sênior"]
    assert d["requisicoes_max"] == 6 and d["cache_ttl_horas"] == 24


def test_plano_usa_termos_em_ingles_fora_do_brasil(client, provedor):
    d = client.post("/evolucao/plano", json={"cargo": "React Native Developer", "pais": "us"}).json()
    assert [c["texto"].split()[-1] for c in d["consultas"]] == ["junior", "mid-level", "senior"]
    assert not any("associate" in c["texto"].lower() for c in d["consultas"])


@pytest.mark.parametrize("corpo", [{"cargo": ""}, {"cargo": " a "}, {"cargo": "x" * 81}, {"cargo": "ok", "paginas": 4}])
def test_validacao_do_cargo_e_das_paginas(client, provedor, corpo):
    assert client.post("/evolucao", json=corpo).status_code == 422 and provedor.chamadas == []


def test_e1_requisicoes_limitadas_e_paginas_pedidas(client, provedor):
    provedor.resposta = jobs_sinteticos()
    d = analisar(client, paginas=2).json()
    assert len(provedor.chamadas) == 6 and d["requisicoes_feitas"] == 6  # 3 níveis x 2 páginas, nada além
    assert sorted({c["query"] for c in provedor.chamadas}) == sorted(c["texto"] for c in d["consultas"])


def test_e1_cota_esgotada_preserva_o_que_ja_veio(client, provedor, monkeypatch):
    provedor.resposta = jobs_sinteticos()
    monkeypatch.setattr(cache, "QUOTA", 2)  # só a consulta júnior (2 páginas) cabe
    r = analisar(client, paginas=2)
    d = r.json()
    assert r.status_code == 200 and len(provedor.chamadas) == 2
    assert d["status_consultas"] == {"junior": "ok", "pleno": "falhou", "senior": "nao_consultada"}
    assert d["niveis"]["junior"]["analisadas"] == 10 and d["niveis"]["pleno"]["cobertura"] == "sem_dados"
    assert any("falhou" in a for a in d["avisos"]) and any("não realizadas por limite de cota" in a for a in d["avisos"])


def test_e1_cota_zerada(client, provedor, monkeypatch):
    monkeypatch.setattr(cache, "QUOTA", 0)
    r = analisar(client)
    assert r.status_code == 429 and "Cota" in r.json()["detail"] and provedor.chamadas == []


# ---------------- cache (E2)
def test_e2_cache_reaproveitado_e_identificado(client, provedor):
    provedor.resposta = jobs_sinteticos()
    d1 = analisar(client).json()
    assert d1["requisicoes_feitas"] == 3 and d1["todo_do_cache"] is False
    d2 = analisar(client, cargo="desenvolvedor react native").json()  # caixa diferente, mesma consulta
    assert len(provedor.chamadas) == 3 and d2["requisicoes_feitas"] == 0 and d2["todo_do_cache"] is True
    assert any("vindos do cache" in a for a in d2["avisos"])
    analisar(client, cargo="Desenvolvedor Kotlin")
    assert len(provedor.chamadas) == 6  # outro cargo não reutiliza páginas


def test_e2_repetir_analise_nao_duplica_resultados(client, provedor):
    provedor.resposta = jobs_sinteticos()
    a, b = analisar(client).json(), analisar(client).json()
    assert a["contagens"] == b["contagens"] and len(a["vagas"]) == len(b["vagas"]) == 30
    assert a["niveis"] == b["niveis"]


# ---------------- falhas (E3) e inicialização (E4)
def test_e3_credenciais_ausentes(client, provedor, monkeypatch):
    monkeypatch.delenv("OPENWEBNINJA_API_KEY")
    r = analisar(client)
    assert r.status_code == 503 and "OPENWEBNINJA_API_KEY" in r.json()["detail"] and "chave-de-teste" not in r.text and provedor.chamadas == []


@pytest.mark.parametrize("status,esperado", [(401, 502), (429, 429)])
def test_e3_erros_do_provedor(client, provedor, status, esperado):
    provedor.status = status
    r = analisar(client)
    assert r.status_code == esperado and isinstance(r.json()["detail"], str) and "chave-de-teste" not in r.text


def test_e3_falha_de_um_nivel_nao_derruba_os_outros(client, provedor):
    provedor.resposta = jobs_sinteticos()
    provedor.falha = lambda p: 401 if "pleno" in p["query"] else None
    d = analisar(client).json()
    assert d["status_consultas"] == {"junior": "ok", "pleno": "falhou", "senior": "ok"}
    assert d["niveis"]["junior"]["analisadas"] == 10 and d["niveis"]["senior"]["analisadas"] == 10 and d["niveis"]["pleno"]["cobertura"] == "sem_dados"


def test_e4_nenhuma_chamada_externa_na_inicializacao(client, provedor):
    for rota in ("/", "/status", "/perfil", "/habilidades"):
        assert client.get(rota).status_code == 200
    assert provedor.chamadas == []


# ---------------- classificação a partir das evidências, não da consulta
def test_nivel_vem_da_vaga_e_nao_da_consulta(client, provedor):
    def resp(q, p):
        if nivel_da_consulta(q) == "junior" and p == 1:
            return [vaga("x1", "Desenvolvedor React Native Sênior", "A", ["React Native"]), vaga("x2", "Desenvolvedor React Native Júnior", "B", ["React Native"])]
        return []
    provedor.resposta = resp
    d = analisar(client).json()
    v = {x["id"]: x for x in d["vagas"]}
    assert v["id:x1"]["nivel"] == "senior" and v["id:x1"]["encontrada_nas_consultas"] == ["junior"]
    assert d["niveis"]["senior"]["coletadas"] == 1 and d["niveis"]["junior"]["coletadas"] == 1


def test_dedup_entre_consultas_e_vagas_nao_classificadas_preservadas(client, provedor):
    def resp(q, p):
        if p != 1:
            return []
        return [vaga("igual", "Desenvolvedor React Native Pleno", "A", ["React Native", "JavaScript"]),  # volta nas 3 consultas
                vaga(f"conf-{nivel_da_consulta(q)}", "Desenvolvedor React Native Júnior/Pleno", "B", ["React Native"])]
    provedor.resposta = resp
    d = analisar(client).json()
    assert d["contagens"]["unicas"] == 4 and [x["id"] for x in d["vagas"]].count("id:igual") == 1
    assert d["contagens"]["nao_classificadas"] == {"total": 3, "conflitante": 3, "informacao_insuficiente": 0}
    assert all("conflitantes" in x["motivo"] for x in d["vagas"] if x["nivel"] == "nao_classificado")
    assert d["niveis"]["pleno"]["coletadas"] == 1  # conflitantes não distorcem os 3 níveis


def test_outros_niveis_ficam_fora_dos_percentuais(client, provedor):
    def resp(q, p):
        if p != 1 or nivel_da_consulta(q) != "pleno":
            return []
        return [vaga("e", "Estagiário React Native", "A", ["React Native", "JavaScript"]), vaga("l", "Tech Lead React Native", "B", ["React Native", "Kotlin"]),
                vaga("s", "Arquiteto React Native", "C", ["React Native"]), vaga("p", "Dev React Native Pleno", "D", ["React Native", "JavaScript"])]
    provedor.resposta = resp
    d = analisar(client).json()
    assert d["contagens"]["outros"] == {"estagio": 1, "lideranca": 1, "especialista": 1}
    assert d["contagens"]["principais"] == 1 and d["niveis"]["pleno"]["analisadas"] == 1
    assert all(h["nome"] != "Kotlin" for h in d["habilidades"])  # requisito de vaga de liderança não entra no ranking pleno


# ---------------- contexto
def test_vagas_fora_do_contexto_sao_excluidas_dos_calculos_e_avisadas(client, provedor):
    def resp(q, p):
        if p != 1 or nivel_da_consulta(q) != "senior":
            return []
        return [vaga("ok", "Dev React Native Sênior", "A", ["React Native", "TypeScript"]), vaga("java", "Desenvolvedor Java Sênior", "B", ["Java", "Spring"])]
    provedor.resposta = resp
    d = analisar(client).json()
    java = next(x for x in d["vagas"] if x["id"] == "id:java")
    assert java["fora_do_contexto"] is True and java["nivel"] == "senior"
    assert d["contagens"]["fora_do_contexto"] == 1 and d["niveis"]["senior"]["analisadas"] == 1
    assert all(h["nome"] != "Java" for h in d["habilidades"]) and any("deixadas fora dos cálculos" in a for a in d["avisos"])
    assert d["contexto"] == {"tecnologias": ["React Native"], "verificavel": True}  # "React" não vira contexto: React Native é mais específico


def test_contexto_sem_tecnologia_reconhecida_avisa_a_limitacao(client, provedor):
    provedor.resposta = lambda q, p: [vaga(f"g{nivel_da_consulta(q)}", "Analista Genérico Pleno", "A", ["Python"])] if p == 1 else []
    d = analisar(client, cargo="Analista Genérico").json()
    assert d["contexto"]["verificavel"] is False and d["contagens"]["fora_do_contexto"] == 0
    assert any("não tem tecnologia reconhecida" in a for a in d["avisos"])


# ---------------- extração e normalização (B)
def test_b_percentuais_diferencas_e_categorias_ponta_a_ponta(client, provedor):
    provedor.resposta = jobs_sinteticos()
    d = analisar(client).json()
    ts = next(h for h in d["habilidades"] if h["nome"] == "TypeScript")
    assert [ts["niveis"][n]["pct"] for n in ("junior", "pleno", "senior")] == [20.0, 40.0, 80.0]
    assert ts["diferenca_pp"] == {"junior_pleno": 20.0, "pleno_senior": 40.0, "junior_senior": 60.0}
    js = next(h for h in d["habilidades"] if h["nome"] == "JavaScript")
    assert [js["niveis"][n]["pct"] for n in ("junior", "pleno", "senior")] == [100.0, 100.0, 100.0]
    dk = next(h for h in d["habilidades"] if h["nome"] == "Docker")
    assert dk["niveis"]["junior"]["diferencial"] == 2 and dk["niveis"]["junior"]["obrigatoria"] == 0  # B4: diferencial != obrigatório
    por_id = {c["id"]: c for c in d["categorias"]}
    assert "JavaScript" in [i["nome"] for i in por_id["comuns"]["itens"]]
    assert "TypeScript" in [i["nome"] for i in por_id["ganham_pleno_senior"]["itens"]]
    assert "Git" in [i["nome"] for i in por_id["diminuem_pleno_senior"]["itens"]]
    assert d["comparacao_confiavel"] is True and all(d["niveis"][n]["cobertura"] == "adequada" for n in ("junior", "pleno", "senior"))
    assert d["contagens"]["coletadas" if "coletadas" in d["contagens"] else "unicas"] == 30


def test_b1_b2_aliases_e_tecnologias_distintas(client, provedor):
    def resp(q, p):
        if p != 1 or nivel_da_consulta(q) != "pleno":
            return []
        return [vaga("a", "Dev React Native Pleno", "A", descricao="Requisitos: React Native, JS, NodeJS, Postgres e Java.\n" + "Atuação em squads de produto. " * 12),
                vaga("b", "Dev React Native Pleno", "B", descricao="Requisitos: React Native, JavaScript, Node.js e PostgreSQL.\n" + "Atuação em squads de produto. " * 12)]
    provedor.resposta = resp
    d = analisar(client).json()
    t = {h["nome"]: h["niveis"]["pleno"]["vagas"] for h in d["habilidades"]}
    assert t["JavaScript"] == 2 and t["Node.js"] == 2 and t["PostgreSQL"] == 2  # JS/JavaScript, NodeJS/Node.js, Postgres/PostgreSQL unificados
    assert t["Java"] == 1 and t["Java"] != t["JavaScript"] and "React" in t and "React Native" in t  # distintos


def test_b3_habilidade_repetida_na_descricao_conta_uma_vez(client, provedor):
    desc = "Requisitos: JavaScript, js, Javascript, JavaScript, React Native.\n" + "JavaScript é central aqui. " * 20
    provedor.resposta = lambda q, p: [vaga("r", "Dev React Native Pleno", "A", descricao=desc)] if p == 1 and nivel_da_consulta(q) == "pleno" else []
    d = analisar(client).json()
    assert next(h for h in d["habilidades"] if h["nome"] == "JavaScript")["niveis"]["pleno"]["vagas"] == 1


def test_b5_descricao_incompleta_sem_requisitos_nao_vira_zero_nem_inventa(client, provedor):
    def resp(q, p):
        if p != 1 or nivel_da_consulta(q) != "pleno":
            return []
        return [vaga("vazia", "Dev React Native Pleno", "A", descricao="Vaga para pessoa dedicada."), vaga("ok", "Dev React Native Pleno", "B", ["React Native", "TypeScript"])]
    provedor.resposta = resp
    d = analisar(client).json()
    assert d["niveis"]["pleno"]["coletadas"] == 2 and d["niveis"]["pleno"]["analisadas"] == 2
    ts = next(h for h in d["habilidades"] if h["nome"] == "TypeScript")["niveis"]["pleno"]
    assert ts["vagas"] == 1 and ts["pct"] == 50.0  # a vaga sem requisitos continua no denominador, como vaga sem menção


def test_b4_sem_marcador_explicito_nada_e_afirmado_como_obrigatorio():
    ob, dif, nc = evolucao.categorizar_requisitos({"tecnologias": ["Python", "SQL"], "diferenciais": ["Docker"]},
                                                  "Trabalhamos com Python e SQL no dia a dia.", "dicionario")
    assert ob == {} and set(nc.values()) == {"Python", "SQL"} and set(dif.values()) == {"Docker"}
    ob, dif, nc = evolucao.categorizar_requisitos({"tecnologias": ["Python"], "diferenciais": []}, "Requisitos: Python.", "dicionario")
    assert set(ob.values()) == {"Python"} and nc == {}
    ob, dif, nc = evolucao.categorizar_requisitos({"tecnologias": ["Python"], "diferenciais": []}, "Texto sem marcador.", "claude")
    assert set(ob.values()) == {"Python"} and nc == {}  # com IA vale a divisão que ela devolveu
    ob, dif, nc = evolucao.categorizar_requisitos({"tecnologias": ["JS", "javascript"], "diferenciais": ["JavaScript", "Go"]}, "Requisitos. Diferencial: Go", "dicionario")
    assert list(ob.values()) == ["JavaScript"] and list(dif.values()) == ["Go"]


def test_b4_sem_marcador_vira_nao_classificada_na_saida(client, provedor):
    provedor.resposta = lambda q, p: [vaga("m", "Dev React Native Pleno", "A", descricao="Usamos React Native e TypeScript diariamente. " * 8)] if p == 1 and nivel_da_consulta(q) == "pleno" else []
    d = analisar(client).json()
    ts = next(h for h in d["habilidades"] if h["nome"] == "TypeScript")["niveis"]["pleno"]
    assert (ts["vagas"], ts["obrigatoria"], ts["nao_classificada"]) == (1, 0, 1)


def test_b6_extracao_parcial_da_ia_mantem_cada_vaga_com_seus_requisitos(client, provedor, monkeypatch):
    def resp(q, p):
        if p != 1 or nivel_da_consulta(q) != "pleno":
            return []
        return [vaga(f"j{i}", "Dev React Native Pleno", f"E{i}", ["React Native", "Ruby", "Perl"]) for i in (1, 2, 3)]
    provedor.resposta = resp
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    por_id = {"j1": ["Python"], "j2": None, "j3": ["Rust"]}

    async def fake(v):
        k = v["id"].split(":")[-1]
        await asyncio.sleep({"j1": 0.05, "j2": 0.0, "j3": 0.02}[k])  # ordem de término != ordem de entrada
        return None if por_id[k] is None else {"tecnologias": ["React Native"] + por_id[k], "diferenciais": [], "soft_skills": [], "nivel": "pleno", "anos_experiencia_min": None}
    monkeypatch.setattr(extract, "extrair", fake)
    d = analisar(client).json()
    t = {h["nome"]: h["niveis"]["pleno"]["vagas"] for h in d["habilidades"]}
    assert t["Python"] == 1 and t["Rust"] == 1 and t["Ruby"] == 1 and t["Perl"] == 1  # Ruby/Perl só da j2 (dicionário), nada trocado de lugar
    assert d["contagens"]["analise_incompleta"] == 1 and d["niveis"]["pleno"]["analise_incompleta"] == 1
    assert any("IA falhou" in a or "análise incompleta" in a for a in d["avisos"])
    j2 = next(x for x in d["vagas"] if x["id"] == "id:j2")
    assert j2["analise_incompleta"] is True


# ---------------- perfil (D5/D6) ponta a ponta
def test_d6_funciona_sem_perfil_e_d5_com_perfil(client, provedor):
    provedor.resposta = jobs_sinteticos()
    sem = analisar(client).json()
    assert sem["perfil"]["disponivel"] is False and sem["perfil_habilidades"] == 0 and sem["categorias"]
    client.put("/habilidades", json={"habilidades": ["js", "Git"]})
    com = analisar(client).json()
    jp = next(t for t in com["perfil"]["transicoes"] if t["para"] == "pleno")
    nomes = [i["nome"] for i in jp["itens"]]
    assert "JavaScript" not in nomes and "Git" not in nomes and "TypeScript" in nomes
    ts = next(i for i in jp["itens"] if i["nome"] == "TypeScript")
    assert (ts["vagas"], ts["analisadas"], ts["pct"], ts["obrigatoria"], ts["diferenca_pp"]) == (4, 10, 40.0, 4, 20.0)
    assert "Não cadastrada no perfil." in ts["explicacao"] and "desconhec" not in str(com["perfil"]).lower()
    assert next(h for h in com["rankings"]["pleno"] if h["nome"] == "TypeScript")["vagas"] == 4  # perfil não altera os rankings
    forcado = analisar(client, habilidades=["Rust"]).json()  # lista enviada na requisição prevalece sobre a salva
    assert forcado["perfil_habilidades"] == 1


# ---------------- estados de amostra e vagas
def test_ausencia_de_vagas_num_dos_niveis(client, provedor):
    provedor.resposta = lambda q, p: jobs_sinteticos()(q, p) if nivel_da_consulta(q) != "senior" else []
    d = analisar(client).json()
    assert d["niveis"]["senior"]["cobertura"] == "sem_dados" and d["comparacao_confiavel"] is False
    assert any("Nenhuma vaga sênior" in a for a in d["avisos"])
    assert {c["id"]: c for c in d["categorias"]}["ganham_pleno_senior"]["disponivel"] is False


def test_quantidade_insuficiente_sinaliza_baixa_cobertura(client, provedor):
    provedor.resposta = jobs_sinteticos((10, 6, 2))
    d = analisar(client).json()
    assert [d["niveis"][n]["cobertura"] for n in ("junior", "pleno", "senior")] == ["adequada", "baixa", "insuficiente"]
    assert d["comparacao_confiavel"] is False
    assert any("Cobertura baixa" in a and "pleno" in a for a in d["avisos"]) and any("Cobertura insuficiente" in a for a in d["avisos"])
    assert {c["id"]: c for c in d["categorias"]}["ganham_junior_pleno"]["firmeza"] == "indicativa"
    assert d["niveis"]["senior"]["analisadas"] == 2 and d["rankings"]["senior"]  # dado descritivo continua visível


def test_sem_vagas_e_sem_classificadas(client, provedor):
    provedor.resposta = lambda q, p: []
    d = analisar(client).json()
    assert d["estado"] == "sem_vagas" and d["vagas"] == [] and d["comparacao_confiavel"] is False
    provedor.resposta = lambda q, p: [vaga(f"n{nivel_da_consulta(q)}", "Desenvolvedor React Native", "A", ["React Native"])] if p == 1 else []
    d = analisar(client, cargo="Desenvolvedor React Native e Mobile").json()
    assert d["estado"] == "sem_classificadas" and d["contagens"]["nao_classificadas"]["informacao_insuficiente"] == 3 and d["contagens"]["principais"] == 0
    assert any("Mais da metade das vagas não indica o nível" in a for a in d["avisos"])


# ---------------- regressão e escopo (E6/E7)
def test_e6_buscas_anteriores_continuam_funcionando(client, provedor):
    desc = "Requisitos: Python, Docker, SQL e AWS. " + "Atuação em squads de produto digital com foco em qualidade. " * 4
    provedor.resposta = lambda q, p: [vaga(f"t-{q}-{p}-{i}", f"Dev {i}", f"Emp{i}", descricao=desc) for i in range(3)]
    assert client.post("/chat", json={"mensagem": "desenvolvedor python", "paginas": 1}).status_code == 200
    prog = db.consultar("SELECT consulta, ultima_pagina FROM progresso")
    provedor.resposta = jobs_sinteticos()
    analisar(client, paginas=2)
    assert db.consultar("SELECT consulta, ultima_pagina FROM progresso") == prog  # análise por senioridade não mexe no histórico
    assert client.post("/busca-habilidades", json={"habilidades": ["Python", "SQL"]}).status_code == 200
    assert client.get("/status").json()["usado"] == cache.usado()


def test_e7_nada_de_etapas_futuras(client):
    # Etapa 5 introduziu gráficos nativos (CSS/SVG); continuam proibidos bibliotecas/canvas/CDN, rotas de sessão/histórico e novo sistema de temas
    from pathlib import Path
    for rota in ("/conversas", "/historico", "/graficos"):  # "/sessoes" é da Etapa 7  # "/comparar" é da Etapa 4 e passou a existir
        assert client.get(rota).status_code == 404 and client.post(rota, json={}).status_code == 404
    html = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8").lower()
    assert "<canvas" not in html and not any(w in html for w in ("chart.js", "d3.js", "plotly", "echarts", "apexcharts", "<svg"))
    assert "data-tema" in html and "prefers-color-scheme" not in html  # Etapa 8: tema por atributo data-tema (claro por padrão)
    assert "data-theme" not in html


def test_e7_resposta_nao_traz_dados_de_comparacao_individual(client, provedor):
    provedor.resposta = jobs_sinteticos()
    d = analisar(client).json()
    assert not any(k in d for k in ("comparacao_entre_vagas", "vaga_a", "vaga_b", "graficos", "sessao"))


def test_privacidade_so_consulta_vai_ao_provedor(client, provedor):
    provedor.resposta = jobs_sinteticos()
    client.put("/perfil", json={"nome": "Nome Secreto Da Pessoa", "areas": ["Area Secreta Y"]})
    client.put("/habilidades", json={"habilidades": ["Habilidade Secreta Z"]})
    analisar(client)
    enviado = str(provedor.chamadas)
    assert "Secret" not in enviado and set(provedor.chamadas[0]) <= {"query", "page", "num_pages", "country", "date_posted"}
