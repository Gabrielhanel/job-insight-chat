"""Etapa 3 — Grupos C/D: frequências, diferenças em p.p., amostras pequenas e perfil (dados SINTÉTICOS de teste)."""
from app import comparativo as c
from app import skills

N = skills.canonizar  # mesmos nomes/chaves que o pipeline real produz


def vaga(i, nivel, obrig=(), dif=(), nc=(), analisada=True, origem="explicita", anos=None, resp=(), incompleta=False):
    mk = lambda xs: {skills.chave(x): N(x) for x in xs}
    return {"id": i, "nivel": nivel, "analisada": analisada, "origem": origem, "obrig": mk(obrig), "dif": mk(dif), "nc": mk(nc),
            "anos": anos, "resp": set(resp), "incompleta": incompleta}


def grupo(nivel, n, base, extras=None, dif_extras=None):
    """n vagas do nível; cada habilidade de `extras` (nome -> em quantas vagas, as primeiras) como obrigatória."""
    extras, dif_extras = extras or {}, dif_extras or {}
    return [vaga(f"{nivel}{i}", nivel, list(base) + [k for k, q in extras.items() if i < q], [k for k, q in dif_extras.items() if i < q]) for i in range(n)]


def get(res, nome):
    return next(h for h in res["habilidades"] if h["nome"] == N(nome))


def cat(res, cid):
    return {x["id"]: x for x in res["categorias"]}[cid]


def nomes(res, cid):
    return [i["nome"] for i in cat(res, cid)["itens"]]


# C1 / C2 — denominadores corretos; coletadas x analisadas
def test_c1_c2_denominador_e_analisadas():
    vs = grupo("junior", 8, ["JS"], {"TS": 2}) + [vaga("x", "junior", analisada=False), vaga("y", "junior", analisada=False)]
    r = c.calcular(vs)
    j = r["niveis"]["junior"]
    assert (j["coletadas"], j["analisadas"], j["sem_analise"]) == (10, 8, 2)  # vaga sem extração NÃO conta como "zero requisitos"
    assert get(r, "TS")["niveis"]["junior"]["pct"] == 25.0  # 2/8 e não 2/10
    assert get(r, "JS")["niveis"]["junior"]["pct"] == 100.0


def test_c2_analise_incompleta_e_contada():
    r = c.calcular(grupo("junior", 3, ["JS"]) + [vaga("z", "junior", ["JS"], incompleta=True)])
    assert r["niveis"]["junior"]["analise_incompleta"] == 1 and r["niveis"]["junior"]["analisadas"] == 4


# C3 / C4 — tamanhos de amostra diferentes; diferença em pontos percentuais
def test_c3_c4_percentuais_e_pontos_percentuais():
    vs = grupo("junior", 10, ["JS"], {"TS": 2}) + grupo("pleno", 40, ["JS"], {"TS": 18}) + grupo("senior", 20, ["JS"], {"TS": 15})
    ts = get(c.calcular(vs), "TS")
    assert [ts["niveis"][n]["pct"] for n in c.NIVEIS] == [20.0, 45.0, 75.0]  # contagens 2/18/15 não são comparáveis; % são
    assert ts["diferenca_pp"] == {"junior_pleno": 25.0, "pleno_senior": 30.0, "junior_senior": 55.0}
    assert ts["niveis"]["pleno"]["vagas"] == 18  # a contagem bruta continua disponível


def test_c4_um_decimal_e_diferenca_em_pp():
    vs = grupo("junior", 3, ["A"], {"B": 1}) + grupo("pleno", 7, ["A"], {"B": 5})
    b = get(c.calcular(vs), "B")
    assert b["niveis"]["junior"]["pct"] == 33.3 and b["niveis"]["pleno"]["pct"] == 71.4
    assert b["diferenca_pp"]["junior_pleno"] == 38.1


def test_percentual_de_obrigatoria_e_de_diferencial_usam_o_mesmo_denominador():
    r = c.calcular(grupo("junior", 10, ["JS"], {"TS": 3}, {"Docker": 2}))
    assert get(r, "TS")["niveis"]["junior"]["pct_obrigatoria"] == 30.0 and get(r, "Docker")["niveis"]["junior"]["pct_diferencial"] == 20.0


# C7 — nível sem dados
def test_c7_categoria_sem_dados():
    r = c.calcular(grupo("junior", 10, ["JS"]) + grupo("pleno", 10, ["JS"]))
    s = r["niveis"]["senior"]
    assert (s["coletadas"], s["analisadas"], s["cobertura"]) == (0, 0, "sem_dados")
    js = get(r, "JS")
    assert js["niveis"]["senior"]["pct"] is None and js["diferenca_pp"]["pleno_senior"] is None
    assert cat(r, "ganham_pleno_senior")["disponivel"] is False and "Sênior: 0 vaga(s)" in cat(r, "ganham_pleno_senior")["motivo"]
    assert cat(r, "comuns")["disponivel"] is False and r["rankings"]["senior"] == []


# C6 — poucas vagas: mostra o dado, sinaliza, sem conclusão firme
def test_c6_amostra_pequena_nao_gera_conclusao_firme():
    r = c.calcular(grupo("junior", 4, ["JS"]) + grupo("pleno", 4, ["JS"], {"TS": 4}))
    assert r["niveis"]["junior"]["cobertura"] == r["niveis"]["pleno"]["cobertura"] == "baixa"
    assert cat(r, "ganham_junior_pleno")["disponivel"] and cat(r, "ganham_junior_pleno")["firmeza"] == "indicativa"
    assert get(r, "TS")["niveis"]["pleno"]["pct"] == 100.0  # o dado não é escondido
    pouco = c.calcular(grupo("junior", 2, ["JS"]) + grupo("pleno", 10, ["JS"]))
    assert pouco["niveis"]["junior"]["cobertura"] == "insuficiente" and cat(pouco, "ganham_junior_pleno")["disponivel"] is False
    ok = c.calcular(grupo("junior", 10, ["JS"]) + grupo("pleno", 10, ["JS"], {"TS": 10}))
    assert cat(ok, "ganham_junior_pleno")["firmeza"] == "adequada"


def test_cobertura_limiares():
    assert [c.cobertura(n) for n in (0, 1, 2, 3, 9, 10, 25)] == ["sem_dados", "insuficiente", "insuficiente", "baixa", "baixa", "adequada", "adequada"]


# B3 — uma habilidade conta uma vez por vaga e por categoria
def test_b3_sem_contagem_inflada():
    r = c.calcular([vaga("a", "junior", obrig=["JS"], dif=["JS", "Docker"], nc=["JS", "Docker"])])
    js = get(r, "JS")["niveis"]["junior"]
    assert js["vagas"] == 1 and (js["obrigatoria"], js["diferencial"], js["nao_classificada"]) == (1, 0, 0)  # obrigatória vence
    dk = get(r, "Docker")["niveis"]["junior"]
    assert dk["vagas"] == 1 and (dk["obrigatoria"], dk["diferencial"], dk["nao_classificada"]) == (0, 1, 0)


def test_habilidades_pouco_citadas_ficam_fora_da_tabela_em_amostras_grandes():
    r = c.calcular(grupo("junior", 10, ["JS"], {"Rara": 1}))
    assert N("Rara") not in [h["nome"] for h in r["habilidades"]]  # 1 menção em 10 vagas
    pequeno = c.calcular(grupo("junior", 3, ["JS"], {"Rara": 1}))
    assert N("Rara") in [h["nome"] for h in pequeno["habilidades"]]  # amostra pequena: nada é escondido


# D1..D4 — categorias comparativas
def cenario():
    return (
        grupo("junior", 10, ["JS", "Git"], {"TS": 2, "jQuery": 6}, {"Docker": 1})
        + grupo("pleno", 10, ["JS", "Git"], {"TS": 4, "Redux": 5}, {"Docker": 2})
        + grupo("senior", 10, ["JS"], {"TS": 8, "Redux": 6, "AWS": 7}, {"Docker": 3})
    )


def test_d1_comuns_e_estaveis():
    r = c.calcular(cenario())
    assert nomes(r, "comuns") == [N("JS")] and nomes(r, "estaveis") == [N("JS")]  # Git some no sênior; TS varia muito


def test_d2_mais_frequentes_em_um_nivel():
    r = c.calcular(cenario())
    assert nomes(r, "mais_frequentes_junior") == [N("jQuery")]  # Git: 100% júnior mas 100% no pleno: não é "mais frequente em júnior"
    assert nomes(r, "caracteristicas_senior") == [N("AWS"), N("TS")]
    assert cat(r, "caracteristicas_senior")["itens"][0]["diferenca_pp"] == 70.0 and cat(r, "caracteristicas_senior")["firmeza"] == "adequada"


def test_d3_diferencas_entre_niveis_e_ordenacao_por_magnitude():
    r = c.calcular(cenario())
    assert nomes(r, "ganham_junior_pleno") == [N("Redux"), N("TS")]  # +50 e +20 p.p.
    assert nomes(r, "ganham_pleno_senior") == [N("AWS"), N("TS")]  # +70 e +40
    assert nomes(r, "diminuem_junior_pleno") == [N("jQuery")] and nomes(r, "diminuem_pleno_senior") == [N("Git")]
    assert [i["diferenca_pp"] for i in cat(r, "ganham_junior_pleno")["itens"]] == [50.0, 20.0]
    docker = get(r, "Docker")  # +10 p.p.: abaixo do limiar, fica fora das categorias mas na tabela
    assert docker["diferenca_pp"]["junior_pleno"] == 10.0 and N("Docker") not in nomes(r, "ganham_junior_pleno")


def test_d2_nenhuma_afirmacao_de_exclusividade():
    r = c.calcular(cenario())
    for x in r["categorias"]:
        assert "exclusiv" not in (x["titulo"] + x["descricao"]).lower()


def test_d4_obrigatoriedade_e_recorrencia_sao_coisas_diferentes():
    r = c.calcular(cenario())
    redux = next(i for i in cat(r, "ganham_junior_pleno")["itens"] if i["nome"] == N("Redux"))
    assert redux["obrigatoria_destino"] == 5 and redux["diferencial_destino"] == 0
    dk = get(r, "Docker")["niveis"]["senior"]
    assert dk["vagas"] == 3 and dk["obrigatoria"] == 0 and dk["diferencial"] == 3  # frequente (30%) mas só como diferencial


def test_c5_desempate_prioriza_obrigatoria_e_depois_nome():
    vs = grupo("junior", 10, ["A"]) + grupo("pleno", 10, ["A"], {"Xobr": 5}, {"Ydif": 5})
    itens = cat(c.calcular(vs), "ganham_junior_pleno")["itens"]
    assert [i["nome"] for i in itens] == ["Xobr", "Ydif"]  # mesma diferença (+50): a obrigatória vem antes


def test_c5_ranking_por_nivel_ordem():
    r = c.calcular(grupo("junior", 10, ["A", "B"], {"C": 5}, {"D": 5}))
    assert [x["nome"] for x in r["rankings"]["junior"]] == ["A", "B", "C", "D"]  # vagas, depois obrigatórias, depois diferenciais, depois nome


def test_nao_classificadas_nao_entram_como_obrigatorias():
    r = c.calcular([vaga(f"n{i}", "junior", nc=["JS"]) for i in range(3)])
    js = get(r, "JS")["niveis"]["junior"]
    assert js["vagas"] == 3 and js["nao_classificada"] == 3 and js["obrigatoria"] == 0 and js["pct_obrigatoria"] == 0.0


# Experiência e responsabilidades — só vagas de nível explícito; sem mediana com poucos dados
def test_experiencia_mediana_so_com_dados_suficientes():
    vs = [vaga(f"j{i}", "junior", ["A"], anos=a) for i, a in enumerate([1, 1, 2, 2, 3])] + [vaga("p1", "pleno", ["A"], anos=3), vaga("p2", "pleno", ["A"])]
    exp = c.calcular(vs)["experiencia"]
    assert exp["junior"]["mediana"] == 2 and exp["junior"]["com_informacao"] == 5 and exp["junior"]["valores"] is None
    assert exp["pleno"]["mediana"] is None and exp["pleno"]["valores"] == [3] and exp["pleno"]["base"] == 2  # poucos dados: sem mediana
    assert exp["senior"]["base"] == 0 and exp["senior"]["minimo"] is None


def test_experiencia_e_responsabilidades_ignoram_nivel_inferido():
    vs = [vaga("a", "senior", ["A"], anos=8, resp=["mentoria"], origem="inferida"), vaga("b", "senior", ["A"], anos=6, resp=[], origem="explicita")]
    r = c.calcular(vs)
    assert r["experiencia"]["senior"]["base"] == 1 and r["responsabilidades"]["base"]["senior"] == 1
    mentoria = next(i for i in r["responsabilidades"]["itens"] if i["chave"] == "mentoria")
    assert mentoria["niveis"]["senior"] == {"vagas": 0, "pct": 0.0} and mentoria["niveis"]["junior"] == {"vagas": 0, "pct": None}


# D5 / D6 — perfil
def test_d5_perfil_relaciona_requisitos_do_proximo_nivel_sem_afirmar_desconhecimento():
    r = c.calcular(cenario(), ["JavaScript", "Git"])
    assert r["perfil"]["disponivel"] is True
    jp = next(t for t in r["perfil"]["transicoes"] if t["para"] == "pleno")
    por_nome = {i["nome"]: i for i in jp["itens"]}
    assert N("JS") not in por_nome and N("Git") not in por_nome and jp["ja_no_perfil"] == 2  # já cadastradas
    ts = por_nome[N("TS")]
    assert (ts["vagas"], ts["analisadas"], ts["pct"], ts["obrigatoria"], ts["diferencial"], ts["diferenca_pp"]) == (4, 10, 40.0, 4, 0, 20.0)
    assert ts["nao_cadastrada_no_perfil"] is True and "Não cadastrada no perfil." in ts["explicacao"]
    assert "20 p.p." in ts["explicacao"] or "+20 p.p." in ts["explicacao"]
    texto = str(r["perfil"]).lower()
    assert "desconhec" not in texto and "não sabe" not in texto and "nao sabe" not in texto
    assert [i["nome"] for i in jp["itens"]] == [N("Redux"), N("TS"), N("Docker")]  # por % no nível de destino (50, 40, 20)


def test_d5_habilidade_do_perfil_com_alias_e_reconhecida():
    r = c.calcular(cenario(), ["js", "TS"])  # aliases
    jp = next(t for t in r["perfil"]["transicoes"] if t["para"] == "pleno")
    assert N("JS") not in [i["nome"] for i in jp["itens"]] and N("TS") not in [i["nome"] for i in jp["itens"]]


def test_d6_sem_perfil_a_analise_funciona():
    for perfil in (None, []):
        r = c.calcular(cenario(), perfil)
        assert r["perfil"] == {"disponivel": False, "transicoes": []}
        assert r["habilidades"] and r["categorias"] and r["rankings"]["pleno"]


def test_perfil_nivel_de_destino_sem_dados_nao_inventa_recomendacao():
    r = c.calcular(grupo("junior", 10, ["JS"]), ["Python"])
    ps = next(t for t in r["perfil"]["transicoes"] if t["para"] == "senior")
    assert ps["itens"] == [] and ps["cobertura_destino"] == "sem_dados"
