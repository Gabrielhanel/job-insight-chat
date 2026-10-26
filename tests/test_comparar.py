"""Etapa 4 — regras puras da comparação de duas vagas (textos e extrações SINTÉTICOS)."""
import pytest

from app import compat, comparar as c, skills


def vaga(id_, titulo="Desenvolvedor", desc="", **extra):
    return {"id": id_, "origem": "provedor", "provedor": "jsearch", "titulo": titulo, "empresa": "Empresa", "local": "SP",
            "link": "https://exemplo.test/x", "publicada_em": None, "obtida_em": "2026-10-15T00:00:00+00:00", "descricao": desc, **extra}


def item(tec=(), dif=(), soft=(), metodo="claude", incompleta=False, motivo=None):
    return {"extracao": {"tecnologias": list(tec), "diferenciais": list(dif), "soft_skills": list(soft), "nivel": "nao_informado",
                         "anos_experiencia_min": None}, "metodo": metodo, "incompleta": incompleta, "motivo": motivo}


LONGA = " Atuação em times de produto digital, com foco em qualidade e entrega contínua de valor ao cliente final." * 4


def analisa(id_, tec=(), dif=(), titulo="Desenvolvedor", desc=None, perfil=(), **kw):
    desc = (("Requisitos: " + ", ".join(list(tec) + list(dif)) + "." + LONGA) if desc is None else desc)
    ch = {skills.chave(p) for p in perfil}
    return c.analisar_vaga(vaga(id_, titulo, desc), item(tec, dif, **kw), ch, bool(perfil))


def nomes(lista):
    return [i["nome"] for i in lista]


# ---------------- B1..B3 — comuns e específicas
def test_b1_b2_b3_comuns_e_especificas():
    a = analisa("a", ["React Native", "JavaScript", "Git"])
    b = analisa("b", ["JavaScript", "Python", "Git"])
    h = c.comparar(a, b)["habilidades"]
    assert sorted(nomes(h["comuns"])) == ["Git", "JavaScript"]
    assert nomes(h["so_a"]) == ["React Native"] and nomes(h["so_b"]) == ["Python"]


# ---------------- B4 — aliases
def test_b4_aliases_e_variacoes():
    a = analisa("a", ["JS", "NodeJS", "Postgres", "TS"])
    b = analisa("b", ["javascript", "Node.js", "PostgreSQL", "TypeScript"])
    h = c.comparar(a, b)["habilidades"]
    assert sorted(nomes(h["comuns"])) == ["JavaScript", "Node.js", "PostgreSQL", "TypeScript"]  # nome canônico legível
    assert h["so_a"] == [] and h["so_b"] == []


# ---------------- B5 — tecnologias distintas
@pytest.mark.parametrize("x,y", [("Java", "JavaScript"), ("React", "React Native"), ("C", "C++"), ("C++", "C#"), ("C", "C#"),
                                 ("SQL", "PostgreSQL"), ("HTML", "CSS"), (".NET", "ASP.NET"), ("TypeScript", "JavaScript")])
def test_b5_tecnologias_distintas_nao_sao_comuns(x, y):
    comp = c.comparar(analisa("a", [x]), analisa("b", [y]))
    assert comp["habilidades"]["comuns"] == []
    assert nomes(comp["habilidades"]["so_a"]) == [skills.canonizar(x)] and nomes(comp["habilidades"]["so_b"]) == [skills.canonizar(y)]


def test_b5_relacionadas_mas_distintas_sao_observacao_e_nao_comuns():
    comp = c.comparar(analisa("a", ["TypeScript", "React"]), analisa("b", ["JavaScript", "React Native"]))
    rel = {(r["a"], r["b"]) for r in comp["habilidades"]["relacionadas"]}
    assert ("TypeScript", "JavaScript") in rel and ("React", "React Native") in rel
    assert comp["habilidades"]["comuns"] == []
    assert all("motivo" in r and r["motivo"] for r in comp["habilidades"]["relacionadas"])


def test_b5_sem_relacao_conhecida_nao_aparece_como_relacionada():
    comp = c.comparar(analisa("a", ["Rust"]), analisa("b", ["Go"]))  # sem mapeamento: nada é inventado
    assert comp["habilidades"]["relacionadas"] == []


# ---------------- B6 — obrigatórios x diferenciais
def test_b6_obrigatorio_numa_e_desejavel_na_outra():
    a = analisa("a", ["Python", "Docker"])
    b = analisa("b", ["Python"], dif=["Docker", "Kafka"])
    comp = c.comparar(a, b)
    docker = next(i for i in comp["habilidades"]["comuns"] if i["nome"] == "Docker")
    assert (docker["a"], docker["b"], docker["mesma_classificacao"]) == ("obrigatoria", "diferencial", False)
    d = comp["obrigatorios"]["a_sem_equivalente_obrigatorio_em_b"]
    assert nomes(d) == ["Docker"] and d[0]["na_outra"] == "diferencial" and "desejável" in d[0]["texto"]
    assert nomes(comp["diferenciais"]["so_b"]) == [skills.canonizar("Kafka")] and comp["diferenciais"]["so_a"] == []
    assert "opcional" not in str(comp).lower()  # nunca se conclui que é "opcional"


def test_b6_classificacao_desconhecida_nao_vira_opcional():
    a = analisa("a", ["Python"], metodo="dicionario", desc="Python é a base do nosso dia a dia." + LONGA)  # sem marcadores
    assert [i["nome"] for i in a["requisitos"]["nao_classificados"]] == ["Python"] and a["requisitos"]["obrigatorios"] == []
    assert any("classificação dessas tecnologias é desconhecida" in x for x in a["limitacoes"])
    b = analisa("b", ["Python"])
    comp = c.comparar(a, b)
    dif = comp["obrigatorios"]["b_sem_equivalente_obrigatorio_em_a"]
    assert nomes(dif) == ["Python"] and dif[0]["na_outra"] == "nao_classificada" and "desconhecido" in dif[0]["texto"]
    assert next(i for i in comp["habilidades"]["comuns"] if i["nome"] == "Python")["a"] == "nao_classificada"


# ---------------- B7 — dado ausente != requisito ausente
def test_b7_ausencia_so_e_firme_quando_a_outra_analise_e_boa():
    a = analisa("a", ["Kafka", "Python"])
    boa = analisa("b", ["Python", "Go"])
    comp = c.comparar(a, boa)
    kafka = comp["habilidades"]["so_a"][0]
    assert kafka["nome"] == skills.canonizar("Kafka") and kafka["ausencia_confiavel"] is True
    assert comp["obrigatorios"]["a_sem_equivalente_obrigatorio_em_b"][0]["texto"] == "não identificada na descrição da outra vaga"
    curta = analisa("b", ["Python"], desc="Requisitos: Python.")  # descrição curta
    assert curta["confianca_ausencia"] == "baixa" and any("Descrição curta" in x for x in curta["limitacoes"])
    comp2 = c.comparar(a, curta)
    assert comp2["habilidades"]["so_a"][0]["ausencia_confiavel"] is False and comp2["confianca_ausencia"] == {"a": "alta", "b": "baixa"}
    s = c.sintese(a, curta, comp2)
    assert any("pode apenas ter sido omitida" in x for x in s["indisponivel"])
    texto = (str(comp2) + str(s)).lower()
    assert "exclusiv" not in texto and "não exige" not in texto and "nao exige" not in texto


def test_b7_ia_falhou_na_outra_vaga_baixa_a_confianca():
    ruim = analisa("b", ["Python"], metodo="dicionario", incompleta=True, motivo="A extração com IA falhou nesta vaga; usei o dicionário de palavras.")
    assert ruim["confianca_ausencia"] == "baixa" and "IA falhou" in " ".join(ruim["limitacoes"])


def test_b7_provedor_que_devolve_resumo_e_limitacao():
    v = vaga("a", desc="Requisitos: Python, SQL." + LONGA, descricao_resumo=True)
    a = c.analisar_vaga(v, item(["Python", "SQL"]), set(), False)
    assert a["confianca_ausencia"] == "baixa" and any("só um trecho da descrição" in x for x in a["limitacoes"])
    t = vaga("t", desc="x" * 100, descricao_truncada=True)
    assert any("truncada" in x for x in c.analisar_vaga(t, item(["Python"]), set(), False)["limitacoes"])


# ---------------- B8 — descrições curtas/ausentes/sem requisitos
def test_b8_sem_descricao_e_sem_analise_nao_comparam_requisitos():
    sem = c.analisar_vaga(vaga("s", desc=""), None, set(), False)
    assert sem["status"] == "sem_descricao" and sem["requisitos"] == {"obrigatorios": [], "diferenciais": [], "nao_classificados": []}
    assert sem["identidade"]["titulo"] == "Desenvolvedor"  # identificação preservada
    falha = c.analisar_vaga(vaga("f", desc="Texto qualquer " * 30), item_falho(), set(), False)
    assert falha["status"] == "sem_analise"
    ok = analisa("o", ["Python"])
    for x in (sem, falha):
        comp = c.comparar(ok, x)
        assert comp["disponivel"] is False and "exige a análise das duas vagas" in comp["motivo"]
        assert c.sintese(ok, x, comp)["incompleta"] is True


def item_falho():
    return {"extracao": None, "metodo": None, "incompleta": True, "motivo": "Não foi possível analisar esta vaga."}


def test_b8_descricao_sem_nenhuma_tecnologia():
    a = analisa("a", [], desc="Procuramos pessoa dedicada e comunicativa. " * 12, perfil=["Python"])
    assert a["status"] == "analisada" and any("Nenhuma tecnologia identificada" in x for x in a["limitacoes"]) and a["confianca_ausencia"] == "baixa"
    assert a["compatibilidade"]["disponivel"] is False and a["compatibilidade"]["compatibilidade"] is None


# ---------------- evidências / rastreabilidade
def test_cada_habilidade_traz_o_trecho_original():
    a = analisa("a", ["JS", "Docker"], desc="Requisitos: Experiência com JS e Docker em produção." + LONGA)
    ev = {i["nome"]: i["evidencia"] for i in a["requisitos"]["obrigatorios"]}
    assert "JS" in ev["JavaScript"] and "Docker" in ev["Docker"]  # o trecho é o texto original, não a forma canônica


def test_habilidade_sem_trecho_localizavel_e_declarada_assim():
    a = analisa("a", ["Kubernetes"], desc="Texto sem a palavra procurada. " * 15)
    assert a["requisitos"]["obrigatorios"][0]["evidencia"] is None


def test_responsabilidades_so_com_sustentacao_no_texto():
    desc = "Você fará code review, mentoria de colegas e definirá decisões técnicas. Haverá contato com stakeholders." + LONGA
    a = analisa("a", ["Python"], desc=desc)
    chaves = {r["chave"] for r in a["responsabilidades"]}
    assert {"revisao_codigo", "mentoria", "decisoes_tecnicas", "negocio"} <= chaves and "arquitetura" not in chaves
    assert all(r["evidencia"] for r in a["responsabilidades"])
    b = analisa("b", ["Python"], desc="Atuará com arquitetura de sistemas e code review." + LONGA)
    r = c.comparar(a, b)["responsabilidades"]
    assert [x["rotulo"] for x in r["comuns"]] == ["Revisão de código"]
    assert "Arquitetura" in [x["rotulo"] for x in r["so_b"]] and "Mentoria/orientação" in [x["rotulo"] for x in r["so_a"]]


def test_formacao_certificacoes_e_outros():
    a = analisa("a", ["AWS"], desc="Graduação em TI. Certificação AWS Certified Developer e ITIL. Inglês avançado. Regime CLT, trabalho remoto." + LONGA)
    assert [x["rotulo"] for x in a["formacao"]] == ["Ensino superior (graduação/bacharelado/tecnólogo)"]
    assert {x["rotulo"] for x in a["certificacoes"]} == {"AWS Certified", "ITIL"}
    assert {"Inglês (citado)", "Contratação CLT (citada)", "Trabalho remoto (citado)"} <= {x["rotulo"] for x in a["outros"]}
    generica = analisa("g", ["AWS"], desc="Valorizamos certificações da área." + LONGA)
    assert [x["rotulo"] for x in generica["certificacoes"]] == ["Certificações (citadas de forma genérica)"]
    nada = analisa("n", ["AWS"], desc="Sem nada disso." + LONGA)
    assert nada["formacao"] == [] and nada["certificacoes"] == [] and nada["outros"] == []  # nada é suposto


# ---------------- senioridade e experiência
def test_senioridade_e_experiencia_comparadas_quando_identificaveis():
    a = analisa("a", ["Python"], titulo="Desenvolvedor Pleno", desc="Requisitos: Python. 3 anos de experiência." + LONGA)
    b = analisa("b", ["Python"], titulo="Desenvolvedor Sênior", desc="Requisitos: Python. 5 a 7 anos de experiência." + LONGA)
    comp = c.comparar(a, b)
    assert comp["senioridade"]["comparavel"] and "Pleno" in comp["senioridade"]["texto"] and "Sênior" in comp["senioridade"]["texto"]
    assert comp["experiencia"]["comparavel"] and comp["experiencia"]["diferenca_anos"] == 2 and "diferença de 2 ano(s)" in comp["experiencia"]["texto"]
    s = c.sintese(a, b, comp)
    assert any("Níveis diferentes" in x for x in s["diferencas"]) and any("Experiência mínima" in x for x in s["diferencas"])


def test_senioridade_nao_inferida_por_quantidade_de_tecnologias():
    muitas = analisa("a", [f"Tec{i}" for i in range(30)] + ["Python", "Go", "Kafka", "AWS", "Docker", "Kubernetes"])
    assert muitas["senioridade"]["nivel"] == "nao_classificado"
    comp = c.comparar(muitas, analisa("b", ["Python"], titulo="Dev Sênior"))
    assert comp["senioridade"]["comparavel"] is False and "Nível não comparável" in comp["senioridade"]["texto"]


def test_experiencia_ausente_ou_ambigua_e_dita():
    a = analisa("a", ["Python"], desc="Requisitos: Python." + LONGA)
    b = analisa("b", ["Python"], desc="Requisitos: Python. 3 anos de experiência." + LONGA)
    comp = c.comparar(a, b)
    assert comp["experiencia"]["comparavel"] is False and "não identificada na(s) vaga(s) A" in comp["experiencia"]["texto"]
    amb = analisa("x", ["Python"], desc="2 anos de experiência em Python e 5 anos de experiência em AWS." + LONGA)
    assert "valores diferentes" in c.comparar(amb, b)["experiencia"]["texto"]


# ---------------- C — compatibilidade (mecanismo existente)
def test_c1_usa_exatamente_compat_avaliar():
    ext = {"tecnologias": ["JavaScript", "Java", "Docker"], "diferenciais": ["Kubernetes", "TypeScript"], "soft_skills": []}
    it = {"extracao": ext, "metodo": "claude", "incompleta": False, "motivo": None}
    a = c.analisar_vaga(vaga("a", desc="Requisitos." + LONGA), it, {skills.chave(x) for x in ("JS", "Docker", "TS")}, True)
    esperado = compat.avaliar(ext, {skills.chave(x) for x in ("JS", "Docker", "TS")})
    assert a["compatibilidade"]["compatibilidade"] == esperado["compatibilidade"] == 62.5
    for k in ("obrigatorios_correspondidos", "diferenciais_correspondidos", "correspondencias", "faltando_obrigatorios", "faltando_diferenciais", "confianca"):
        assert a["compatibilidade"][k] == esperado[k]


def test_c2_falha_no_calculo_de_uma_vaga_nao_afeta_a_outra(monkeypatch):
    original = compat.avaliar

    def quebra_se_boom(ext, chaves, descricao_curta=False):
        if "Boom" in ext["tecnologias"]:
            raise RuntimeError("falha simulada")
        return original(ext, chaves, descricao_curta)

    monkeypatch.setattr(compat, "avaliar", quebra_se_boom)
    a = analisa("a", ["Boom", "Python", "Docker"], perfil=["Python"])
    b = analisa("b", ["Python", "Docker", "Go"], perfil=["Python"])
    assert a["compatibilidade"] == {"disponivel": False, "motivo": "Falha ao calcular a compatibilidade desta vaga."}
    assert b["compatibilidade"]["disponivel"] is True and b["compatibilidade"]["compatibilidade"] is not None
    assert c.comparar(a, b)["disponivel"] is True  # a comparação de requisitos continua


def test_c3_amostra_pequena_preserva_o_comportamento_do_compat():
    a = analisa("a", ["Python"], perfil=["Python"])  # 1 requisito
    assert a["compatibilidade"]["compatibilidade"] == 100.0 and a["compatibilidade"]["confianca"] == "baixa" and a["compatibilidade"]["avisos"]
    curta = c.analisar_vaga(vaga("c", desc="Requisitos: Python, SQL, Docker."), item(["Python", "SQL", "Docker"]), {skills.chave("Python")}, True)
    assert curta["compatibilidade"]["confianca"] == "baixa" and any("curta" in x.lower() for x in curta["compatibilidade"]["avisos"])


def test_c4_dados_insuficientes_sem_pontuacao():
    a = analisa("a", [], desc="Sem tecnologias aqui. " * 20, perfil=["Python"])
    assert a["compatibilidade"]["disponivel"] is False and a["compatibilidade"]["compatibilidade"] is None and a["compatibilidade"]["estado"] == "dados_insuficientes"
    sem = c.analisar_vaga(vaga("s", desc=""), None, {skills.chave("Python")}, True)
    assert sem["compatibilidade"] == {"disponivel": False, "motivo": "Sem análise de requisitos para esta vaga."}


def test_c5_sem_perfil_a_comparacao_funciona():
    a, b = analisa("a", ["Python", "SQL"]), analisa("b", ["Python", "Go"])
    assert a["compatibilidade"] == {"disponivel": False, "motivo": "Nenhuma habilidade cadastrada no perfil."}
    assert c.comparar(a, b)["disponivel"] is True


def test_compat_avisa_quando_conta_sem_marcacao_como_obrigatoria():
    a = analisa("a", ["Python", "SQL", "Docker"], metodo="dicionario", desc="Usamos Python, SQL e Docker." + LONGA, perfil=["Python"])
    assert any("sem marcação explícita" in x for x in a["compatibilidade"]["avisos"])


# ---------------- síntese e neutralidade
def test_sintese_vem_do_resultado_estruturado_e_nao_escolhe_vencedora():
    a = analisa("a", ["Python", "Docker", "Kafka"], titulo="Dev Pleno", perfil=["Python"])
    b = analisa("b", ["Python", "Docker", "Go"], titulo="Dev Pleno", perfil=["Python", "Docker", "Go"])
    comp = c.comparar(a, b)
    s = c.sintese(a, b, comp)
    assert any("2 habilidade(s) em comum" in x for x in s["semelhancas"]) and any("mesmo nível" in x for x in s["semelhancas"])
    assert s["especificas"] == {"a": [skills.canonizar("Kafka")], "b": ["Go"]}
    assert "não indica qual vaga é melhor" in s["nota"]
    # nenhuma chave/ texto elege vencedora, mesmo com compatibilidades diferentes
    assert a["compatibilidade"]["compatibilidade"] != b["compatibilidade"]["compatibilidade"]
    blob = (str(s) + str(comp)).lower()
    assert "vencedor" not in blob and "melhor vaga" not in blob and "recomend" not in blob


def test_sintese_sem_nada_em_comum():
    s = c.sintese(*(lambda a, b: (a, b, c.comparar(a, b)))(analisa("a", ["Java"]), analisa("b", ["Rust"])))
    assert s["semelhancas"][0] == "Nenhuma habilidade técnica em comum foi identificada."


def test_isolamento_entre_vagas_nada_vaza_de_a_para_b():
    a = analisa("a", ["Kafka"], desc="Requisitos: Kafka." + LONGA)
    b = analisa("b", ["Go"], desc="Requisitos: Go." + LONGA)
    assert [i["nome"] for i in b["requisitos"]["obrigatorios"]] == ["Go"] and "Kafka" not in b["descricao"]
    assert a["identidade"]["id"] == "a" and b["identidade"]["id"] == "b"
