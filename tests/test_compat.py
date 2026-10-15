"""Grupos D/E — compatibilidade, dados insuficientes e priorização (código puro, sem I/O)."""
import pytest

from app import compat, skills


def chaves(*nomes):
    return {skills.chave(n) for n in nomes}


# Vaga DE TESTE (não é dado de mercado): 3 obrigatórios + 2 diferenciais
EXT = {"tecnologias": ["JavaScript", "Java", "Docker"], "diferenciais": ["Kubernetes", "TypeScript"],
       "soft_skills": ["Comunicação"], "nivel": "pleno", "anos_experiencia_min": 3}


def test_e1_formula_com_lista_conhecida():
    a = compat.avaliar(EXT, chaves("JavaScript", "Docker", "TypeScript"))
    # 100 × (2·2 + 1) / (2·3 + 2) = 62,5
    assert a["compatibilidade"] == 62.5
    assert (a["obrigatorios_correspondidos"], a["obrigatorios_total"]) == (2, 3)
    assert (a["diferenciais_correspondidos"], a["diferenciais_total"]) == (1, 2)
    assert a["requisitos_total"] == 5 and a["estado"] == "avaliada" and a["confianca"] == "normal"
    assert a["correspondencias"] == ["JavaScript", "Docker", "TypeScript"]
    assert a["faltando_obrigatorios"] == ["Java"] and a["faltando_diferenciais"] == ["Kubernetes"]


def test_e2_requisito_ausente_reduz_cobertura():
    cheio = compat.avaliar(EXT, chaves("JavaScript", "Java", "Docker", "Kubernetes", "TypeScript"))
    menos = compat.avaliar(EXT, chaves("JavaScript", "Java", "Docker", "Kubernetes"))
    assert cheio["compatibilidade"] == 100.0 and menos["compatibilidade"] < 100.0


def test_e3_limites_0_a_100():
    assert compat.avaliar(EXT, set())["compatibilidade"] == 0.0
    assert compat.avaliar(EXT, chaves("JS", "Java", "Docker", "Kubernetes", "TS"))["compatibilidade"] == 100.0
    for perfil in (set(), chaves("Java"), chaves("Docker", "TS")):
        assert 0 <= compat.avaliar(EXT, perfil)["compatibilidade"] <= 100


def test_perfil_so_com_o_que_a_vaga_pede_nao_vira_100_se_a_vaga_pede_mais():
    a = compat.avaliar({"tecnologias": ["Python", "SQL", "Docker"], "diferenciais": []}, chaves("Python"))
    assert a["compatibilidade"] == pytest.approx(33.3, abs=0.1) and a["compatibilidade"] != 100


def test_e4_dados_insuficientes_sem_pontuacao_artificial():
    a = compat.avaliar({"tecnologias": [], "diferenciais": [], "soft_skills": ["Comunicação"]}, chaves("Python"))
    assert a["estado"] == "dados_insuficientes" and a["compatibilidade"] is None and a["confianca"] is None
    assert a["avisos"]
    s = compat.avaliar(None, chaves("Python"))
    assert s["estado"] == "sem_analise" and s["compatibilidade"] is None


def test_poucos_requisitos_marcam_confianca_baixa_e_descricao_curta_avisa():
    a = compat.avaliar({"tecnologias": ["Python"], "diferenciais": []}, chaves("Python"))
    assert a["compatibilidade"] == 100.0 and a["confianca"] == "baixa" and a["avisos"]
    b = compat.avaliar(EXT, chaves("Java"), descricao_curta=True)
    assert b["confianca"] == "baixa" and any("curta" in x.lower() for x in b["avisos"])


def test_e6_obrigatorio_pesa_mais_que_diferencial():
    ext = {"tecnologias": ["Python"], "diferenciais": ["Docker"]}
    com_obrig = compat.avaliar(ext, chaves("Python"))["compatibilidade"]
    com_dif = compat.avaliar(ext, chaves("Docker"))["compatibilidade"]
    assert (com_obrig, com_dif) == (66.7, 33.3)


def test_e7_d4_habilidade_conta_uma_vez_por_vaga():
    ext = {"tecnologias": ["JS", "javascript", "JavaScript", "Docker"], "diferenciais": ["Javascript", "Kubernetes"]}
    a = compat.avaliar(ext, chaves("JavaScript"))
    assert a["obrigatorios_total"] == 2 and a["diferenciais_total"] == 1  # JS aparece 4x, vale 1 (como obrigatório)
    assert a["compatibilidade"] == pytest.approx(100 * 2 / (4 + 1), abs=0.1)


def test_d5_obrigatorios_e_diferenciais_ficam_separados():
    a = compat.avaliar(EXT, set())
    assert a["faltando_obrigatorios"] == ["JavaScript", "Java", "Docker"]
    assert a["faltando_diferenciais"] == ["Kubernetes", "TypeScript"]


def aval(titulo, obrig, dif, perfil, id=None):
    a = compat.avaliar({"tecnologias": obrig, "diferenciais": dif}, chaves(*perfil))
    return {"id": id or titulo, "titulo": titulo, **a}


def test_e5_priorizacao_por_frequencia_e_obrigatoriedade():
    vagas = [
        aval("v1", ["TypeScript", "Docker", "AWS"], ["Kubernetes"], ["Python"]),
        aval("v2", ["TypeScript", "Docker"], ["Kubernetes", "Terraform"], ["Python"]),
        aval("v3", ["TypeScript"], ["Docker", "Kubernetes"], ["Python"]),
        aval("v4", ["Python"], ["Terraform"], ["Python"]),
    ]
    r = compat.priorizar_lacunas(vagas)
    assert r["base"] == 4
    ordem = [i["nome"] for i in r["itens"]]
    assert ordem == ["TypeScript", "Docker", "Kubernetes", "Terraform", "AWS"]
    ts = r["itens"][0]
    assert (ts["vagas"], ts["percentual"], ts["como_obrigatoria"], ts["como_diferencial"]) == (3, 75, 3, 0)
    dk = r["itens"][1]
    assert (dk["vagas"], dk["como_obrigatoria"], dk["como_diferencial"]) == (3, 2, 1)  # empate em vagas: mais obrigatória vence
    assert "Python" not in ordem  # já está no perfil


def test_priorizacao_desempate_estavel_e_ignora_vagas_sem_requisitos():
    vagas = [aval("a", ["Zeta", "Alfa"], [], []), compat.avaliar({"tecnologias": [], "diferenciais": []}, set()) | {"id": "x", "titulo": "x"}]
    r = compat.priorizar_lacunas(vagas)
    assert r["base"] == 1 and [i["nome"] for i in r["itens"]] == ["Alfa", "Zeta"]


def test_e8_rotulo_e_sobre_cadastro_nao_sobre_conhecimento():
    a = compat.avaliar(EXT, set())
    assert "faltando_obrigatorios" in a and not any("desconhec" in k or "nao_sabe" in k for k in a)


def test_ordenacao_por_grupos_sem_nota_artificial():
    vs = [
        aval("baixa-conf-100", ["Python"], [], ["Python"]),                 # 100%, mas só 1 requisito
        aval("normal-50", ["A", "B", "C"], [], ["A"]),                       # 33%
        aval("normal-90", ["A", "B", "C"], ["D"], ["A", "B", "C"]),          # 87,5%
        {"id": "ins", "titulo": "ins", **compat.avaliar({"tecnologias": [], "diferenciais": []}, set())},
        {"id": "sem", "titulo": "sem", **compat.avaliar(None, set())},
    ]
    assert [v["id"] for v in compat.ordenar(vs)] == ["normal-90", "normal-50", "baixa-conf-100", "ins", "sem"]


def test_ordenacao_desempate_por_obrigatorios_correspondidos():
    c1 = aval("c1", ["A", "B"], ["C"], ["A"])                    # 2/5 = 40%, 1 obrigatório correspondido
    c2 = aval("c2", ["A"], ["D", "E", "F"], ["D", "E"])          # 2/5 = 40%, 0 obrigatórios correspondidos
    assert c1["compatibilidade"] == c2["compatibilidade"] == 40.0
    assert c1["confianca"] == c2["confianca"] == "normal"
    assert [v["id"] for v in compat.ordenar([c2, c1])] == ["c1", "c2"]
    assert [v["id"] for v in compat.ordenar([c1, c2])] == ["c1", "c2"]  # independe da ordem de entrada
