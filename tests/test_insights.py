from app import insights
from app.insights import MIN_AMOSTRA, gerar

CAMPOS = {"id", "nivel", "titulo", "texto", "acao"}


def valido(lista):
    for x in lista:
        assert set(x) == CAMPOS and x["nivel"] in ("destaque", "info", "alerta")
        assert x["acao"] is None or x["acao"]["destino"] in insights.DESTINOS


def test_min_amostra():
    assert MIN_AMOSTRA == 10


def test_tolerante_a_dados_invalidos():
    for t in ("chat", "habilidades", "evolucao", "comparar", "x", None):
        for r in (None, {}, [], "x", {"dados": 3}, {"comparacao": None, "niveis": []}, {"contagens": {"avaliadas": 2}, "lacunas": 7}):
            valido(gerar(t, r))


def test_chat_derivado_do_resultado():
    d = {"cargo": "dev", "vagas_analisadas": 4, "tecnologias": [{"nome": "Python", "vagas": 3, "percentual": 75}],
         "diferenciais": [], "niveis_detalhe": [{"nivel": "pleno", "vagas": 3, "percentual": 75}], "experiencia_mediana_anos": 3}
    r = gerar("chat", {"resposta": "", "dados": d})
    valido(r)
    ids = [x["id"] for x in r]
    assert "chat-amostra" in ids and "chat-top" in ids and "75%" in next(x for x in r if x["id"] == "chat-top")["texto"]
    assert "chat-amostra" not in [x["id"] for x in gerar("chat", {"dados": {**d, "vagas_analisadas": 12}})]
    assert gerar("chat", {"dados": {"vagas_analisadas": 0}}) == []


def test_habilidades_lacuna_e_sem_perfil():
    r = {"estado": "ok", "habilidades": [], "contagens": {"avaliadas": 12}, "vagas": [],
         "lacunas": {"itens": [{"nome": "SQL", "percentual": 50, "como_obrigatoria": 4, "como_diferencial": 2}]}}
    out = gerar("habilidades", r)
    valido(out)
    assert any(x["id"] == "hab-sem-perfil" for x in out)
    lac = next(x for x in out if x["id"] == "hab-lacuna")
    assert lac["acao"]["destino"] == "hab" and lac["acao"]["preencher"] == {"habilidades": ["SQL"]}
    assert gerar("habilidades", {"estado": "sem_vagas"})[0]["id"] == "hab-sem-vagas"


def test_evolucao_amostra_insuficiente_sem_conclusao_inventada():
    r = {"estado": "ok", "niveis": {"junior": {"analisada": 0, "analisadas": 2}, "pleno": {"analisadas": 1}, "senior": {"analisadas": 0}},
         "categorias": [], "perfil": {"disponivel": False, "transicoes": []}}
    out = gerar("evolucao", r)
    valido(out)
    assert [x["id"] for x in out] == ["evo-amostra", "evo-sem-perfil"]


def test_comparar():
    a = {"status": "analisada"}
    comp = {"disponivel": True, "habilidades": {"comuns": [{"nome": "Python"}], "so_a": [{"nome": "Go", "ausencia_confiavel": False}], "so_b": []},
            "obrigatorios": {"a_sem_equivalente_obrigatorio_em_b": [{"nome": "Go"}], "b_sem_equivalente_obrigatorio_em_a": []}, "senioridade": {"comparavel": False}}
    out = gerar("comparar", {"a": a, "b": a, "comparacao": comp, "perfil_habilidades": 0})
    valido(out)
    assert any(x["id"] == "cmp-especificas" and x["nivel"] == "alerta" for x in out)
    off = gerar("comparar", {"a": {"status": "falha_ao_carregar", "motivo": "m"}, "b": a, "comparacao": {"disponivel": False}})
    assert off[0]["id"] == "cmp-falha-a"
