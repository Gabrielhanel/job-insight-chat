"""Etapa 5 — dados que alimentam os gráficos: campos aditivos, consistência com o texto e casos vazios/extremos."""
import re

import pytest

from app import aggregate, evolucao
from tests.falso_provedor import FILLER, vaga


def ext(nivel="nao_informado", tec=(), soft=(), dif=()):
    return {"tecnologias": list(tec), "diferenciais": list(dif), "soft_skills": list(soft), "nivel": nivel, "anos_experiencia_min": None}


def test_niveis_detalhe_soma_o_total_e_preserva_os_campos_existentes():
    es = [ext("junior"), ext("junior"), ext("pleno"), ext("senior"), ext("nao_informado"), ext("nao_informado"), ext("nao_informado"), ext("lead")]
    r = aggregate.agregar(es)
    assert r["niveis"] == {"junior": 2, "pleno": 1, "senior": 1, "nao_informado": 3, "lead": 1}  # campo existente intacto
    det = r["niveis_detalhe"]
    assert [d["nivel"] for d in det] == ["junior", "pleno", "senior", "lead", "nao_informado"]  # ordem lógica, não alfabética
    assert sum(d["vagas"] for d in det) == r["vagas_analisadas"] == 8
    assert {d["nivel"]: d["percentual"] for d in det} == {"junior": 25, "pleno": 12, "senior": 12, "lead": 12, "nao_informado": 38}  # round(100*c/n)


def test_agregar_vazio_continua_igual():
    assert aggregate.agregar([]) == {"vagas_analisadas": 0}


def test_percentual_do_ranking_e_proporcao_de_vagas_nao_de_ocorrencias():
    es = [ext(tec=["Python", "SQL"]) for _ in range(17)] + [ext(tec=["Go"]) for _ in range(10)]
    r = aggregate.agregar(es)
    py = next(i for i in r["tecnologias"] if i["nome"] == "Python")
    assert (py["vagas"], py["percentual"]) == (17, 63)  # 17 de 27 vagas ≈ 63% (e não 17/soma das ocorrências)


def test_chat_devolve_niveis_detalhe_e_os_numeros_batem_com_o_texto(client, provedor):
    def desc(i):
        return f"Requisitos: JavaScript, React{', TypeScript' if i < 3 else ''}. Boa comunicação e trabalho em equipe.{FILLER}"
    provedor.resposta = lambda q, p: [vaga(f"g{i}", f"Dev {['Júnior', 'Pleno', 'Sênior', 'Pleno'][i % 4]} {i}", f"Emp{i}", descricao=desc(i)) for i in range(8)] if p == 1 else []
    r = client.post("/chat", json={"mensagem": "grafico teste", "paginas": 1})
    d = r.json()["dados"]
    assert r.status_code == 200 and d["niveis_detalhe"] and sum(x["vagas"] for x in d["niveis_detalhe"]) == d["vagas_analisadas"] == 8
    linhas = {n: (int(p), int(v)) for n, p, v in re.findall(r"- (.+?): (\d+)% \((\d+) vagas\)", r.json()["resposta"])}
    for i in d["tecnologias"][:10]:
        assert linhas[i["nome"]] == (i["percentual"], i["vagas"])  # o texto e os dados que alimentam os gráficos são os mesmos números


def jobs_evolucao(n=(10, 10, 4)):
    def resp(q, p):
        nv = "junior" if "júnior" in q else ("pleno" if "pleno" in q else "senior")
        rot = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior"}[nv]
        if p != 1:
            return []
        out = [vaga(f"{nv}-{i}", f"Desenvolvedor React Native {rot}", f"E{nv}{i}", ["React Native", "JavaScript"]) for i in range(n[("junior", "pleno", "senior").index(nv)])]
        if nv == "junior":
            out += [vaga("c1", "Desenvolvedor React Native Júnior/Pleno", "X", ["React Native"]), vaga("n1", "Desenvolvedor React Native", "Y", ["React Native"]),
                    vaga("e1", "Estagiário React Native", "Z", ["React Native"]), vaga("j1", "Desenvolvedor Java Sênior", "W", ["Java"])]
        return out
    return resp


def test_distribuicao_da_analise_por_senioridade_soma_o_total(client, provedor):
    provedor.resposta = jobs_evolucao()
    d = client.post("/evolucao", json={"cargo": "Desenvolvedor React Native", "paginas": 1}).json()
    dist = {x["chave"]: x for x in d["distribuicao"]}
    assert sum(x["vagas"] for x in d["distribuicao"]) == d["contagens"]["unicas"] == 28
    assert {k: v["vagas"] for k, v in dist.items()} == {"junior": 10, "pleno": 10, "senior": 4, "estagio": 1, "nao_classificada": 2, "fora_do_contexto": 1}
    assert dist["junior"]["percentual"] == round(100 * 10 / 28, 1) and dist["junior"]["rotulo"] == "Júnior"
    assert all(x["vagas"] > 0 for x in d["distribuicao"])  # categorias vazias não entram


def test_distribuicao_vazia_sem_vagas(client, provedor):
    provedor.resposta = lambda q, p: []
    d = client.post("/evolucao", json={"cargo": "Desenvolvedor React Native"}).json()
    assert d["estado"] == "sem_vagas" and d["distribuicao"] == []


def test_distribuicao_unitaria():
    assert evolucao.distribuicao_classificacao({"unicas": 0}, {}) == []
