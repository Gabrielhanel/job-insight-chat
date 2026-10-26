"""Insights da Etapa 8: leituras curtas derivadas dos resultados reais de cada análise (funções puras, sem I/O, sem IA).

Formato de cada insight: {id, nivel, titulo, texto, acao}
  nivel: "destaque" | "info" | "alerta"
  acao: None ou {rotulo, destino, [preencher]}; destino em DESTINOS. `preencher` só pré-preenche um campo (nunca dispara busca).
Nada é inventado: cada texto cita números/nomes presentes no resultado. `gerar` nunca propaga exceção.
"""
import logging

from app import comparativo

log = logging.getLogger("vagas")

MIN_AMOSTRA = comparativo.MIN_ANALISADAS
DESTINOS = ("vagas", "hab", "evo", "cmp", "perfil")
MAX_INSIGHTS = 6


def _i(id_, nivel, titulo, texto, acao=None):
    return {"id": id_, "nivel": nivel, "titulo": titulo, "texto": texto, "acao": acao}


def _acao(rotulo, destino, preencher=None):
    a = {"rotulo": rotulo, "destino": destino}
    if preencher:
        a["preencher"] = preencher
    return a


def _lista(itens, n=3):
    return ", ".join(str(x) for x in itens[:n])


def _aviso_amostra(id_, n, o_que="vagas analisadas"):
    return _i(id_, "alerta", "Amostra pequena",
              f"Só {n} {o_que} (recomendado: {MIN_AMOSTRA}+). Trate os percentuais como indicativos.")


# ------------------------------------------------------------------ busca por cargo
def para_chat(r: dict) -> list[dict]:
    d = (r or {}).get("dados") or {}
    if d.get("sem_novas"):
        return [_i("chat-sem-novas", "info", "Nenhuma vaga nova", d.get("aviso") or "Não há novas vagas para esta consulta.")]
    n = d.get("vagas_analisadas") or 0
    if not n:
        return []
    out = []
    if n < MIN_AMOSTRA:
        out.append(_aviso_amostra("chat-amostra", n))
    tec = d.get("tecnologias") or []
    if tec:
        t = tec[0]
        out.append(_i("chat-top", "destaque", f"{t['nome']} lidera",
                      f"{t['nome']} aparece em {t['percentual']}% das {n} vagas analisadas ({t['vagas']} vagas)."
                      + (f" Em seguida: {_lista([x['nome'] for x in tec[1:]], 3)}." if len(tec) > 1 else ""),
                      _acao("Testar esta habilidade", "hab", {"habilidades": [t["nome"]]})))
    dif = d.get("diferenciais") or []
    if dif:
        out.append(_i("chat-dif", "info", "Diferenciais citados", f"Mais citados como diferencial: {_lista([x['nome'] for x in dif])}."))
    nd = d.get("niveis_detalhe") or []
    if nd:
        m = max(nd, key=lambda x: x["vagas"])
        out.append(_i("chat-nivel", "info", "Nível predominante",
                      f"{m['percentual']}% das vagas analisadas estão classificadas como “{m['nivel']}”.",
                      _acao("Ver evolução por senioridade", "evo", {"cargo": d.get("cargo")}) if d.get("cargo") else None))
    if d.get("experiencia_mediana_anos") is not None:
        out.append(_i("chat-exp", "info", "Experiência mínima", f"Mediana de {d['experiencia_mediana_anos']} ano(s) entre as vagas que informam experiência."))
    return out[:MAX_INSIGHTS]


# ------------------------------------------------------------------ busca por habilidades
def para_habilidades(r: dict) -> list[dict]:
    r = r or {}
    if r.get("estado") == "sem_vagas":
        return [_i("hab-sem-vagas", "info", "Nenhuma vaga encontrada", "As consultas não retornaram vagas. Tente outras habilidades ou outro país.")]
    c = r.get("contagens") or {}
    aval = c.get("avaliadas") or 0
    if not aval:
        return []
    out = []
    if not r.get("habilidades"):
        out.append(_i("hab-sem-perfil", "info", "Sem habilidades no perfil", "Cadastre habilidades para ver a compatibilidade com as vagas.", _acao("Abrir perfil", "perfil")))
    if aval < MIN_AMOSTRA:
        out.append(_aviso_amostra("hab-amostra", aval, "vagas avaliadas"))
    lac = ((r.get("lacunas") or {}).get("itens")) or []
    if lac:
        t = lac[0]
        out.append(_i("hab-lacuna", "destaque", f"Maior lacuna: {t['nome']}",
                      f"{t['nome']} é pedida em {t['percentual']}% das {aval} vagas avaliadas e não consta no seu perfil "
                      f"({t['como_obrigatoria']} como obrigatória, {t['como_diferencial']} como diferencial).",
                      _acao("Adicionar às minhas habilidades", "hab", {"habilidades": [t["nome"]]})))
        if len(lac) > 1:
            out.append(_i("hab-lacunas", "info", "Outras lacunas", f"Em seguida: {_lista([x['nome'] for x in lac[1:]], 4)}."))
    vagas = [v for v in (r.get("vagas") or []) if isinstance(v, dict)]
    if vagas and vagas[0].get("titulo"):
        out.append(_i("hab-top", "info", "Vaga mais compatível", f"{vagas[0]['titulo']}" + (f" — {vagas[0]['empresa']}" if vagas[0].get("empresa") else "") + " aparece primeiro na ordenação."))
    if c.get("dados_insuficientes"):
        out.append(_i("hab-insuf", "alerta", "Descrições curtas", f"{c['dados_insuficientes']} vaga(s) sem dados suficientes ficaram fora da compatibilidade."))
    return out[:MAX_INSIGHTS]


# ------------------------------------------------------------------ evolução por senioridade
def para_evolucao(r: dict) -> list[dict]:
    r = r or {}
    if r.get("estado") in ("sem_vagas", "sem_classificadas"):
        return [_i("evo-sem-dados", "info", "Sem vagas classificadas", "Não houve vagas com nível identificável para comparar.")]
    niveis = r.get("niveis") or {}
    n_an = {k: (v or {}).get("analisadas", 0) for k, v in niveis.items()}
    if not any(n_an.values()):
        return []
    out = []
    baixos = [k for k, n in n_an.items() if n < MIN_AMOSTRA]
    if baixos:
        out.append(_i("evo-amostra", "alerta", "Amostra insuficiente em alguns níveis",
                      "Analisadas por nível: " + ", ".join(f"{k} {n}" for k, n in n_an.items()) + f" (recomendado: {MIN_AMOSTRA}+ em cada)."))
    for cat in r.get("categorias") or []:
        if cat.get("id") in ("ganham_junior_pleno", "ganham_pleno_senior") and cat.get("disponivel") and cat.get("itens"):
            it = cat["itens"][0]
            de, para = ("júnior", "pleno") if cat["id"] == "ganham_junior_pleno" else ("pleno", "sênior")
            out.append(_i("evo-" + cat["id"], "destaque", f"{it['nome']} ganha peso de {de} para {para}",
                          f"Aumento de {it['diferenca_pp']:g} p.p. entre as vagas analisadas (firmeza {cat.get('firmeza', 'indicativa')})."))
    comuns = next((c for c in (r.get("categorias") or []) if c.get("id") == "comuns" and c.get("disponivel") and c.get("itens")), None)
    if comuns:
        out.append(_i("evo-comuns", "info", "Base comum aos três níveis", f"Presentes em todos os níveis: {_lista([x['nome'] for x in comuns['itens']], 4)}."))
    p = r.get("perfil") or {}
    if p.get("disponivel"):
        falta = [t for t in p.get("transicoes") or [] if t.get("itens")]
        if falta:
            t = falta[0]
            out.append(_i("evo-perfil", "destaque", "Para o próximo nível",
                          f"Faltam no perfil ({t['de']} → {t['para']}): {_lista([x['nome'] for x in t['itens']], 4)}.",
                          _acao("Ver vagas por habilidade", "hab")))
    else:
        out.append(_i("evo-sem-perfil", "info", "Perfil sem habilidades", "Cadastre habilidades para ver o que falta para o próximo nível.", _acao("Abrir perfil", "perfil")))
    return out[:MAX_INSIGHTS]


# ------------------------------------------------------------------ comparação de vagas
def para_comparar(r: dict) -> list[dict]:
    r = r or {}
    comp = r.get("comparacao") or {}
    out = []
    for l in ("a", "b"):
        x = r.get(l) or {}
        if x.get("status") == "falha_ao_carregar":
            out.append(_i(f"cmp-falha-{l}", "alerta", f"Vaga {l.upper()} não carregada", x.get("motivo") or "Não foi possível carregar esta vaga."))
    if not comp.get("disponivel"):
        if not out:
            out.append(_i("cmp-indisp", "alerta", "Comparação indisponível", comp.get("motivo") or "Faltam dados para comparar as duas vagas."))
        return out
    h = comp.get("habilidades") or {}
    com, sa, sb = h.get("comuns") or [], h.get("so_a") or [], h.get("so_b") or []
    out.append(_i("cmp-comuns", "destaque", f"{len(com)} habilidade(s) em comum",
                  (f"Em comum: {_lista([x['nome'] for x in com], 5)}." if com else "Nenhuma habilidade técnica em comum foi identificada.")))
    ob = comp.get("obrigatorios") or {}
    oa, obb = ob.get("a_sem_equivalente_obrigatorio_em_b") or [], ob.get("b_sem_equivalente_obrigatorio_em_a") or []
    if oa:
        out.append(_i("cmp-obr-a", "info", "Obrigatórias só na vaga A", _lista([x["nome"] for x in oa], 5) + "."))
    if obb:
        out.append(_i("cmp-obr-b", "info", "Obrigatórias só na vaga B", _lista([x["nome"] for x in obb], 5) + "."))
    if sa or sb:
        incerto = any(not x.get("ausencia_confiavel", True) for x in sa + sb)
        out.append(_i("cmp-especificas", "alerta" if incerto else "info", "Habilidades em uma só vaga",
                      f"Só na A: {len(sa)}; só na B: {len(sb)}."
                      + (" Com análise limitada, a ausência pode ser só omissão da descrição." if incerto else "")))
    sen = comp.get("senioridade") or {}
    if sen.get("comparavel") and sen.get("texto"):
        out.append(_i("cmp-sen", "info", "Senioridade", sen["texto"]))
    if not r.get("perfil_habilidades"):
        out.append(_i("cmp-sem-perfil", "info", "Perfil sem habilidades", "Cadastre habilidades para ver a aderência de cada vaga.", _acao("Abrir perfil", "perfil")))
    return out[:MAX_INSIGHTS]


_POR_TIPO = {"chat": para_chat, "habilidades": para_habilidades, "evolucao": para_evolucao, "comparar": para_comparar}


def gerar(tipo, resultado) -> list[dict]:
    """Insights do resultado de uma análise; tipo ou dados inválidos/incompletos devolvem lista vazia (nunca levanta)."""
    try:
        f = _POR_TIPO.get(tipo)
        if f is None or not isinstance(resultado, dict):
            return []
        saida = []
        for x in f(resultado):
            a = x.get("acao")
            if a and a.get("destino") not in DESTINOS:
                x = {**x, "acao": None}
            saida.append(x)
        return saida
    except Exception as e:  # insight é complemento: nunca derruba a análise
        log.warning("Falha ao gerar insights (%s): %s", tipo, type(e).__name__)
        return []
