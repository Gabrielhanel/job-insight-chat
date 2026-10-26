"""Etapa 7 — sessões e histórico persistente (SQLite temporário; provedor SIMULADO; dados SINTÉTICOS)."""
import json
import re
import sqlite3
import time

import pytest

from app import cache, db, sessoes
from tests.falso_provedor import FILLER, vaga
from tests.servidor import servidor
import httpx

DESC = "Requisitos: Python, Docker, SQL e AWS. " + "Atuação em times de produto digital com foco em qualidade. " * 4


def nova(client, titulo=None):
    r = client.post("/sessoes", json={"titulo": titulo} if titulo else {})
    assert r.status_code == 201, r.text
    return r.json()


def chat(client, sid, msg="desenvolvedor python", uid=None, **extra):
    corpo = {"mensagem": msg, "paginas": 1, "sessao_id": sid, **extra}
    if uid:
        corpo["interacao_uid"] = uid
    return client.post("/chat", json=corpo)


def prepara(provedor):
    provedor.resposta = lambda q, p: [vaga(f"v-{q}-{p}-{i}", f"Dev {i}", f"Emp{i}", descricao=DESC) for i in range(3)] if p == 1 else []


def abrir(client, sid):
    return client.get(f"/sessoes/{sid}").json()


# ---------------- Grupo A — sessões
def test_a1_criar_sessao_confirmada_pelo_backend(client):
    s = nova(client)
    assert re.fullmatch(r"[0-9a-f]{32}", s["id"]) and s["titulo"] == "Nova conversa" and s["total_interacoes"] == 0
    assert s["criada_em"] == s["atualizada_em"]
    assert db.consultar("SELECT count(*) FROM sessoes")[0][0] == 1           # realmente gravada


def test_a2_a3_listar_e_abrir(client):
    a, b = nova(client), nova(client)
    lista = client.get("/sessoes").json()["sessoes"]
    assert {x["id"] for x in lista} == {a["id"], b["id"]}
    d = abrir(client, a["id"])
    assert d["sessao"]["id"] == a["id"] and d["interacoes"] == []


def test_a4_a5_a6_alternar_continuar_e_criar_sem_apagar(client, provedor):
    prepara(provedor)
    a, b = nova(client), nova(client)
    chat(client, a["id"], "python senior")
    chat(client, b["id"], "kotlin android")
    chat(client, a["id"], "python pleno")                                      # continua a sessão A depois de usar a B
    da, db_ = abrir(client, a["id"]), abrir(client, b["id"])
    assert [i["consulta"] for i in da["interacoes"]] == ["python senior", "python pleno"] and [i["seq"] for i in da["interacoes"]] == [1, 2]
    assert [i["consulta"] for i in db_["interacoes"]] == ["kotlin android"]
    c = nova(client)                                                           # criar uma terceira não apaga nada
    assert len(client.get("/sessoes").json()["sessoes"]) == 3 and abrir(client, a["id"])["sessao"]["total_interacoes"] == 2 and c["id"] not in (a["id"], b["id"])


def test_a7_ordem_por_atividade_recente(client, provedor):
    prepara(provedor)
    a, b, c = nova(client), nova(client), nova(client)
    ids = lambda: [x["id"] for x in client.get("/sessoes").json()["sessoes"]]
    assert ids() == [c["id"], b["id"], a["id"]]                                # sem atividade: a mais nova primeiro
    chat(client, a["id"])
    assert ids() == [a["id"], c["id"], b["id"]]                                # atividade em A a traz para o topo
    chat(client, b["id"])
    assert ids()[:2] == [b["id"], a["id"]]


def test_a8_id_independe_do_titulo(client, provedor):
    prepara(provedor)
    a, b = nova(client, "Mesmo título"), nova(client, "Mesmo título")          # títulos iguais continuam sessões distintas
    assert a["id"] != b["id"]
    chat(client, a["id"])
    r = client.patch(f"/sessoes/{a['id']}", json={"titulo": "Outro nome qualquer"})
    assert r.status_code == 200 and r.json()["id"] == a["id"] and r.json()["titulo"] == "Outro nome qualquer"
    d = abrir(client, a["id"])
    assert d["sessao"]["titulo"] == "Outro nome qualquer" and len(d["interacoes"]) == 1      # mesma identidade e registros
    assert abrir(client, b["id"])["interacoes"] == []


def test_titulo_automatico_manual_e_padrao(client, provedor):
    prepara(provedor)
    s = nova(client)
    assert s["titulo"] == "Nova conversa"                                      # sem conteúdo: nome neutro
    chat(client, s["id"], "  desenvolvedor   python   sênior ")
    assert abrir(client, s["id"])["sessao"]["titulo"] == "desenvolvedor python sênior"         # da 1ª consulta, sem IA
    chat(client, s["id"], "outra consulta")
    assert abrir(client, s["id"])["sessao"]["titulo"] == "desenvolvedor python sênior"         # não muda depois
    longo = nova(client)
    chat(client, longo["id"], "x" * 200)
    t = abrir(client, longo["id"])["sessao"]["titulo"]
    assert len(t) == sessoes.MAX_TITULO and t.endswith("…")
    manual = nova(client, "Minha pesquisa")
    chat(client, manual["id"], "qualquer coisa")
    assert abrir(client, manual["id"])["sessao"]["titulo"] == "Minha pesquisa"               # título dado pela pessoa é preservado


@pytest.mark.parametrize("titulo", ["", "   ", "x" * (sessoes.MAX_TITULO + 1)])
def test_renomear_invalido_nao_altera(client, titulo):
    s = nova(client, "Original")
    assert client.patch(f"/sessoes/{s['id']}", json={"titulo": titulo}).status_code == 422
    assert abrir(client, s["id"])["sessao"]["titulo"] == "Original"


# ---------------- Grupo B — interações e resultados
def test_b9_b10_b11_registra_na_ordem_e_guarda_o_resultado_estruturado(client, provedor):
    prepara(provedor)
    s = nova(client)
    r1 = chat(client, s["id"], "desenvolvedor python").json()
    assert r1["salvo"] is True and r1["interacao"]["seq"] == 1 and r1["interacao"]["sessao_id"] == s["id"] and r1["interacao"]["tipo"] == "chat"
    r2 = client.post("/busca-habilidades", json={"habilidades": ["Python", "SQL"], "sessao_id": s["id"]}).json()
    r3 = client.post("/evolucao", json={"cargo": "Desenvolvedor Python", "paginas": 1, "sessao_id": s["id"]}).json()
    assert [r["interacao"]["seq"] for r in (r1, r2, r3)] == [1, 2, 3] and r2["interacao"]["tipo"] == "habilidades" and r3["interacao"]["tipo"] == "evolucao"
    d = abrir(client, s["id"])
    assert [i["tipo"] for i in d["interacoes"]] == ["chat", "habilidades", "evolucao"]
    ext = lambda r: {k: v for k, v in r.items() if k not in ("interacao", "salvo", "insights")}
    assert d["interacoes"][0]["resultado"] == ext(r1)                           # o mesmo resultado que a interface exibiu, inclusive texto
    assert d["interacoes"][0]["resultado"]["resposta"].startswith("Analisei 3 vagas")
    assert d["interacoes"][1]["resultado"] == ext(r2) and d["interacoes"][2]["resultado"] == ext(r3)
    assert d["interacoes"][0]["parametros"] == {"mensagem": "desenvolvedor python", "pais": "br", "paginas": 1, "apenas_novas": False}
    assert d["interacoes"][1]["parametros"]["habilidades"] == ["Python", "SQL"]          # parâmetros efetivos (não "usar o perfil")


def test_b12_dados_dos_graficos_ficam_salvos_para_reconstruir(client, provedor):
    prepara(provedor)
    s = nova(client)
    chat(client, s["id"])
    client.post("/evolucao", json={"cargo": "Desenvolvedor Python", "paginas": 1, "sessao_id": s["id"]})
    a, b = [vaga("x1", "Dev Pleno", "A", ["Python", "SQL"]), vaga("x2", "Dev Sênior", "B", ["Python", "AWS", "Docker"])]
    provedor.resposta = lambda q, p: [a, b] if p == 1 else []
    bu = client.post("/comparar/buscar", json={"consulta": "Dev"}).json()
    cmp = client.post("/comparar", json={"a": {"tipo": "busca", **bu["ref"], "id": "id:x1"}, "b": {"tipo": "busca", **bu["ref"], "id": "id:x2"}, "sessao_id": s["id"]}).json()
    d = abrir(client, s["id"])
    chat_r, evo_r, cmp_r = (i["resultado"] for i in d["interacoes"])
    assert chat_r["dados"]["niveis_detalhe"] and chat_r["dados"]["tecnologias"]                      # barras do chat
    assert evo_r["distribuicao"] and evo_r["niveis"] and "habilidades" in evo_r                      # rosca e barras agrupadas da evolução
    assert cmp_r["comparacao"]["habilidades"]["contagens"] == cmp["comparacao"]["habilidades"]["contagens"] and cmp_r["a"]["contagens"]   # comparação


def test_b13_reabrir_nao_chama_o_provedor_nem_gasta_cota_nem_exige_credenciais(client, provedor, monkeypatch):
    prepara(provedor)
    s = nova(client)
    chat(client, s["id"])
    chamadas, usado = len(provedor.chamadas), cache.usado()
    monkeypatch.delenv("OPENWEBNINJA_API_KEY")                                   # sem credenciais: abrir continua funcionando
    for _ in range(3):
        assert abrir(client, s["id"])["interacoes"][0]["resultado"]["dados"]["vagas_analisadas"] == 3
    assert client.get("/sessoes").status_code == 200
    assert len(provedor.chamadas) == chamadas and cache.usado() == usado


def test_b14_resultados_parciais_incompletos_e_grandes(client, provedor, monkeypatch):
    prepara(provedor)
    s = nova(client)
    provedor.resposta = lambda q, p: [vaga("ok", "Dev A", "A", ["Python", "SQL"]), vaga("vazia", "Dev B", "B", descricao="")] if p == 1 else []
    bu = client.post("/comparar/buscar", json={"consulta": "Dev"}).json()
    sel = lambda i: {"tipo": "busca", **bu["ref"], "id": i}
    r = client.post("/comparar", json={"a": sel("id:ok"), "b": sel("id:vazia"), "sessao_id": s["id"]}).json()
    assert r["estado"] == "parcial"
    i = abrir(client, s["id"])["interacoes"][0]
    assert i["status"] == "parcial" and i["resultado"]["b"]["status"] == "sem_descricao" and i["resultado"]["a"]["requisitos"]["obrigatorios"]    # parcial preservado como parcial
    # resultado maior que o limite: a consulta fica registrada, o resultado não
    with monkeypatch.context() as mp:
        mp.setattr(sessoes, "MAX_RESULTADO_BYTES", 100)
        m = chat(client, s["id"], "outra").json()
    assert m["salvo"] is True and m["interacao"]["resultado_guardado"] is False
    g = abrir(client, s["id"])["interacoes"][1]
    assert g["resultado"] is None and g["resultado_disponivel"] is False and "grande demais" in g["aviso"] and g["consulta"] == "outra"
    # registro corrompido: o resto da sessão segue utilizável
    db_ = sqlite3.connect(db.DB)
    db_.execute("UPDATE interacoes SET resultado='{quebrado' WHERE seq=2"); db_.commit(); db_.close()
    d = abrir(client, s["id"])
    assert d["interacoes"][1]["resultado"] is None and "não pôde ser reconstruído" in d["interacoes"][1]["aviso"] and d["interacoes"][0]["resultado"]["estado"] == "parcial"


def test_b15_isolamento_total_entre_sessoes_e_uid_por_sessao(client, provedor):
    prepara(provedor)
    a, b = nova(client), nova(client)
    chat(client, a["id"], "segredo da sessão A", uid="mesmo-uid-12345")
    chat(client, b["id"], "conteúdo da sessão B", uid="mesmo-uid-12345")           # o mesmo uid em outra sessão é outra interação
    ta, tb = json.dumps(abrir(client, a["id"]), ensure_ascii=False), json.dumps(abrir(client, b["id"]), ensure_ascii=False)
    assert "segredo da sessão A" in ta and "conteúdo da sessão B" not in ta and "conteúdo da sessão B" in tb and "segredo da sessão A" not in tb
    assert db.consultar("SELECT count(*) FROM interacoes")[0][0] == 2


def test_idempotencia_do_evento_repetido_sem_recalcular_e_repeticao_deliberada_permitida(client, provedor):
    prepara(provedor)
    s = nova(client)
    r1 = chat(client, s["id"], "python", uid="evento-aaaaaaaa").json()
    chamadas, usado = len(provedor.chamadas), cache.usado()
    r2 = chat(client, s["id"], "python", uid="evento-aaaaaaaa").json()           # clique repetido / evento duplicado
    assert r2["interacao"]["id"] == r1["interacao"]["id"] and r2["interacao"]["repetida"] is True and r2["resposta"] == r1["resposta"]
    assert len(provedor.chamadas) == chamadas and cache.usado() == usado
    assert abrir(client, s["id"])["sessao"]["total_interacoes"] == 1
    r3 = chat(client, s["id"], "python", uid="evento-bbbbbbbb").json()           # mesma consulta de propósito: nova interação
    assert r3["interacao"]["seq"] == 2 and abrir(client, s["id"])["sessao"]["total_interacoes"] == 2


def test_analise_sem_sessao_continua_igual(client, provedor):
    prepara(provedor)
    r = client.post("/chat", json={"mensagem": "python", "paginas": 1}).json()
    assert "interacao" not in r and "salvo" not in r and r["dados"]["vagas_analisadas"] == 3
    assert db.consultar("SELECT count(*) FROM interacoes")[0][0] == 0


# ---------------- erros e validações
def test_ids_invalidos_inexistentes_e_uid_invalido(client, provedor):
    prepara(provedor)
    for rota in ("/sessoes/abc", "/sessoes/" + "g" * 32, "/sessoes/' OR 1=1 --"):
        assert client.get(rota).status_code in (404, 422)
        assert client.delete(rota).status_code in (404, 422)
    assert client.get("/sessoes/" + "a" * 32).status_code == 404
    assert client.get("/sessoes/abc").status_code == 422 and "inválido" in client.get("/sessoes/abc").json()["detail"]
    usado = cache.usado()
    r = chat(client, "a" * 32)                                                     # sessão inexistente: não chega ao provedor
    assert r.status_code == 404 and "Sessão não encontrada" in r.json()["detail"] and provedor.chamadas == [] and cache.usado() == usado
    s = nova(client)
    assert chat(client, s["id"], uid="curto").status_code == 422 and chat(client, "xyz").status_code == 422 and provedor.chamadas == []


def test_excluir_remove_so_a_sessao_e_suas_interacoes(client, provedor):
    prepara(provedor)
    client.put("/perfil", json={"nome": "Ana", "areas": ["IA"]}); client.put("/habilidades", json={"habilidades": ["Python"]})
    a, b = nova(client), nova(client)
    chat(client, a["id"]); chat(client, b["id"], "outra")
    paginas, usado = db.consultar("SELECT count(*) FROM paginas")[0][0], cache.usado()
    vistas = db.consultar("SELECT count(*) FROM vistas")[0][0]
    r = client.delete(f"/sessoes/{a['id']}")
    assert r.status_code == 200 and r.json() == {"removida": a["id"]}
    assert client.get(f"/sessoes/{a['id']}").status_code == 404 and client.delete(f"/sessoes/{a['id']}").status_code == 404
    assert db.consultar("SELECT count(*) FROM interacoes WHERE sessao_id=?", (a["id"],))[0][0] == 0
    assert abrir(client, b["id"])["sessao"]["total_interacoes"] == 1                               # a outra sessão intacta
    assert db.consultar("SELECT count(*) FROM paginas")[0][0] == paginas and cache.usado() == usado and db.consultar("SELECT count(*) FROM vistas")[0][0] == vistas
    assert client.get("/perfil").json()["nome"] == "Ana" and client.get("/habilidades").json()["habilidades"] == ["Python"]   # perfil e cache preservados


def test_lista_e_leve_sem_resultados_nem_descricoes(client, provedor):
    prepara(provedor)
    s = nova(client)
    chat(client, s["id"]); client.post("/evolucao", json={"cargo": "Desenvolvedor Python", "paginas": 1, "sessao_id": s["id"]})
    item = client.get("/sessoes").json()["sessoes"][0]
    assert set(item) == {"id", "titulo", "titulo_manual", "criada_em", "atualizada_em", "total_interacoes", "ultimo_tipo", "ultimo_resumo"}
    assert item["total_interacoes"] == 2 and item["ultimo_tipo"] == "evolucao" and "vagas" in item["ultimo_resumo"]
    assert len(client.get("/sessoes").text) < 1000                                                  # não carrega resultados na listagem


# ---------------- Grupo C — persistência e integridade
def test_c16_persistencia_apos_reiniciar_a_aplicacao(tmp_path):
    dbp = str(tmp_path / "h.db")
    itens = [{"q": "desenvolvedor python", "d": {"vagas_analisadas": 5, "tecnologias": [{"nome": "Python", "vagas": 3, "percentual": 60}], "niveis": {}, "cargo": "x"}}]
    with servidor(dbp) as url:
        s = httpx.post(url + "/sessoes", json={"titulo": "Persistente"}).json()
        imp = httpx.post(url + "/sessoes/importar-legado", json={"itens": itens}).json()
        httpx.patch(f"{url}/sessoes/{s['id']}", json={"titulo": "Persistente 2"})
    with servidor(dbp) as url:                                                      # processo novo, mesmo arquivo SQLite
        lista = httpx.get(url + "/sessoes").json()["sessoes"]
        assert {x["titulo"] for x in lista} == {"Persistente 2", "Conversas anteriores (importadas)"}
        d = httpx.get(f"{url}/sessoes/{imp['sessao']['id']}").json()
        assert d["interacoes"][0]["consulta"] == "desenvolvedor python" and d["interacoes"][0]["resultado"]["dados"]["vagas_analisadas"] == 5


def test_c18_migracao_nao_apaga_tabelas_e_dados_existentes(client, banco_legado):
    assert client.get("/sessoes").json() == {"sessoes": []}                        # banco sem as tabelas novas: criadas ao usar
    nova(client)
    c = sqlite3.connect(banco_legado)
    tabelas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"paginas", "uso", "vistas", "progresso", "perfil", "perfil_areas", "perfil_habilidades", "sessoes", "interacoes"} <= tabelas
    assert c.execute("SELECT dados FROM paginas WHERE chave='k'").fetchone() == ("[1,2]",) and c.execute("SELECT n FROM uso").fetchone() == (42,)
    assert c.execute("SELECT ultima_pagina FROM progresso").fetchone() == (3,)
    c.close()


def test_c19_falha_de_gravacao_nao_derruba_a_analise_nem_deixa_registro_pela_metade(client, provedor, banco):
    prepara(provedor)
    s = nova(client)
    chat(client, s["id"], "primeira")
    antes = abrir(client, s["id"])["sessao"]["atualizada_em"]
    c = sqlite3.connect(banco)
    c.execute("CREATE TRIGGER falha BEFORE INSERT ON interacoes WHEN NEW.consulta='boom' BEGIN SELECT RAISE(ABORT, 'falha simulada'); END"); c.commit(); c.close()
    time.sleep(0.01)
    r = chat(client, s["id"], "boom").json()
    assert r["dados"]["vagas_analisadas"] == 3 and r["salvo"] is False and r["interacao"] is None       # a análise é entregue, mas NÃO é dada como salva
    assert "Não foi possível salvar a análise no histórico" in r["aviso_historico"] and "falha simulada" not in str(r)
    d = abrir(client, s["id"])
    assert len(d["interacoes"]) == 1 and d["sessao"]["atualizada_em"] == antes                          # nada parcial; atividade da sessão intacta
    c = sqlite3.connect(banco); c.execute("DROP TRIGGER falha"); c.commit(); c.close()
    assert chat(client, s["id"], "depois").json()["interacao"]["seq"] == 2                              # a sequência continua sem buracos


def test_c20_integridade_das_relacoes(client, banco):
    s = nova(client)
    from app import db as _db
    with pytest.raises(sqlite3.IntegrityError):                                     # interação sem sessão válida
        with _db.transacao() as c:
            c.execute("INSERT INTO interacoes (sessao_id, seq, tipo, consulta, parametros, status, criada_em) VALUES ('naoexiste', 1, 'chat', 'x', '{}', 'ok', 'agora')")
    sessoes.registrar(s["id"], "chat", {"mensagem": "x"}, {"dados": {"vagas_analisadas": 1}})
    with pytest.raises(sqlite3.IntegrityError):                                     # (sessão, seq) é único
        with _db.transacao() as c:
            c.execute("INSERT INTO interacoes (sessao_id, seq, tipo, consulta, parametros, status, criada_em) VALUES (?, 1, 'chat', 'y', '{}', 'ok', 'agora')", (s["id"],))
    assert sessoes.excluir(s["id"]) == {"removida": s["id"]} and db.consultar("SELECT count(*) FROM interacoes")[0][0] == 0


def test_limite_de_interacoes_por_sessao_e_avisado(client, provedor, monkeypatch):
    prepara(provedor)
    monkeypatch.setattr(sessoes, "MAX_INTERACOES", 2)
    s = nova(client)
    chat(client, s["id"], "a"); chat(client, s["id"], "b")
    r = chat(client, s["id"], "c").json()
    assert r["dados"]["vagas_analisadas"] == 3 and r["salvo"] is False and "limite de 2 análises" in r["aviso_historico"]


def test_segredos_nao_sao_gravados(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-segredo-1234567890")
    s = nova(client)
    sessoes.registrar(s["id"], "chat", {"mensagem": "x"}, {"dados": {"vagas_analisadas": 1, "x": "chave sk-ant-segredo-1234567890 aqui"}})
    bruto = str(db.consultar("SELECT parametros, resultado FROM interacoes"))
    assert "sk-ant-segredo" not in bruto and "[removido]" in bruto


def test_importar_historico_antigo_do_navegador(client):
    ok = {"q": "analista de testes", "d": {"vagas_analisadas": 4, "tecnologias": [{"nome": "QA", "vagas": 3, "percentual": 75}], "niveis": {"pleno": 2}}}
    r = client.post("/sessoes/importar-legado", json={"itens": [ok, {"q": "", "d": {}}, {"q": "sem dados"}, "lixo", ok]})
    assert r.status_code == 201 and [i["consulta"] for i in r.json()["interacoes"]] == ["analista de testes", "analista de testes"]
    assert r.json()["interacoes"][0]["resultado"]["importado"] is True and r.json()["sessao"]["titulo"] == "Conversas anteriores (importadas)"
    assert client.post("/sessoes/importar-legado", json={"itens": [{"q": "x"}]}).status_code == 422


def test_titulos_e_textos_sao_guardados_como_texto_e_sql_parametrizado(client):
    s = nova(client, "Robert'); DROP TABLE sessoes;-- <img src=x onerror=alert(1)>")
    assert db.consultar("SELECT count(*) FROM sessoes")[0][0] == 1                                    # nada foi executado
    assert abrir(client, s["id"])["sessao"]["titulo"] == "Robert'); DROP TABLE sessoes;-- <img src=x onerror=alert(1)>"
