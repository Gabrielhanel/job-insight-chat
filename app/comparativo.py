"""Estatísticas por nível e comparações entre níveis (determinístico, sem I/O e sem IA).

Entrada: lista de vagas já classificadas/extraídas, cada uma com
  nivel ('junior'|'pleno'|'senior'|outro), analisada (bool: requisitos extraídos com sucesso), origem ('explicita'|'inferida'|None),
  obrig / dif / nc (dict chave canônica -> nome: obrigatórios, diferenciais e "não classificados"), anos (int|None), resp (set).

Denominador de cada nível = vagas daquele nível ANALISADAS com sucesso (não as coletadas). Cada habilidade conta no máximo
uma vez por vaga e por categoria; "mencionam" = união das três categorias. Diferenças são em PONTOS PERCENTUAIS (p.p.).
Experiência e responsabilidades só usam vagas de nível explícito (título/frase), para não haver circularidade com a inferência.
"""
from statistics import median

from app import skills
from app.senioridade import PRINCIPAIS, RESPONSABILIDADES, ROTULOS

NIVEIS = PRINCIPAIS
MIN_ANALISADAS = 10  # amostra "adequada" por nível: cada vaga pesa <= 10 p.p. e uma página do provedor traz ~10 anúncios
MIN_DESCRITIVA = 3  # abaixo disso o nível só mostra contagens (sem comparação)
DIF_MIN_PP = 15.0  # diferença mínima para destacar (>= 1,5 vaga numa amostra de 10)
PRESENCA_MIN_PCT = 20.0  # o lado "maior" precisa aparecer em pelo menos 20% das vagas
COMUM_MIN_PCT = 25.0  # "comum" = >= 25% em todos os níveis
ESTAVEL_MAX_PP = 15.0  # "estável" = comum e com amplitude <= 15 p.p.
MIN_MENCOES = 2  # habilidades com menos menções (no total) ficam de fora das tabelas, salvo amostra muito pequena
MIN_ANOS_MEDIANA = 5  # só mostra mediana de experiência com pelo menos 5 valores
TOP_RANKING = 10


def pct(v: int, n: int) -> float | None:
    return round(100 * v / n, 1) if n else None


def cobertura(n: int) -> str:
    if n == 0:
        return "sem_dados"
    if n < MIN_DESCRITIVA:
        return "insuficiente"
    return "baixa" if n < MIN_ANALISADAS else "adequada"


def _por_nivel(vagas, nivel):
    return [v for v in vagas if v["nivel"] == nivel]


def estatisticas_niveis(vagas: list[dict]) -> dict:
    out = {}
    for n in NIVEIS:
        vs = _por_nivel(vagas, n)
        analisadas = [v for v in vs if v["analisada"]]
        out[n] = {
            "rotulo": ROTULOS[n], "coletadas": len(vs), "analisadas": len(analisadas),
            "sem_analise": len(vs) - len(analisadas),
            "analise_incompleta": sum(1 for v in vs if v.get("incompleta")),
            "cobertura": cobertura(len(analisadas)),
        }
    return out


def tabela_habilidades(vagas: list[dict], stats: dict) -> list[dict]:
    contagem: dict[str, dict] = {}
    for n in NIVEIS:
        for v in (x for x in _por_nivel(vagas, n) if x["analisada"]):
            obrig, dif = dict(v["obrig"]), {k: x for k, x in v["dif"].items() if k not in v["obrig"]}
            nc = {k: x for k, x in v["nc"].items() if k not in obrig and k not in dif}
            for cat, grupo in (("obrigatoria", obrig), ("diferencial", dif), ("nao_classificada", nc)):
                for k, nome in grupo.items():
                    c = contagem.setdefault(k, {"nome": nome, **{l: {"obrigatoria": 0, "diferencial": 0, "nao_classificada": 0} for l in NIVEIS}})
                    c[n][cat] += 1
    total_analisadas = sum(stats[n]["analisadas"] for n in NIVEIS)
    minimo = MIN_MENCOES if total_analisadas >= 8 else 1
    tabela = []
    for k, c in contagem.items():
        niveis, total = {}, 0
        for n in NIVEIS:
            d, den = c[n], stats[n]["analisadas"]
            m = d["obrigatoria"] + d["diferencial"] + d["nao_classificada"]
            total += m
            niveis[n] = {
                "vagas": m, "pct": pct(m, den), **{cat: d[cat] for cat in ("obrigatoria", "diferencial", "nao_classificada")},
                "pct_obrigatoria": pct(d["obrigatoria"], den), "pct_diferencial": pct(d["diferencial"], den),
            }
        if total < minimo:
            continue
        def dif_pp(a, b):
            pa, pb = niveis[a]["pct"], niveis[b]["pct"]
            return None if pa is None or pb is None else round(pb - pa, 1)
        tabela.append({
            "chave": k, "nome": c["nome"], "total_vagas": total, "niveis": niveis,
            "diferenca_pp": {"junior_pleno": dif_pp("junior", "pleno"), "pleno_senior": dif_pp("pleno", "senior"),
                             "junior_senior": dif_pp("junior", "senior")},
        })
    tabela.sort(key=lambda h: (-max((h["niveis"][n]["pct"] or 0) for n in NIVEIS), -h["total_vagas"], h["nome"].casefold()))
    return tabela


def rankings(tabela: list[dict]) -> dict:
    out = {}
    for n in NIVEIS:
        itens = [h for h in tabela if h["niveis"][n]["vagas"] > 0]
        itens.sort(key=lambda h: (-h["niveis"][n]["vagas"], -h["niveis"][n]["obrigatoria"], -h["niveis"][n]["diferencial"], h["nome"].casefold()))
        out[n] = [{"nome": h["nome"], **h["niveis"][n]} for h in itens[:TOP_RANKING]]
    return out


def _pct(h, n):
    return h["niveis"][n]["pct"] or 0.0


def categorias(tabela: list[dict], stats: dict) -> list[dict]:
    n = {l: stats[l]["analisadas"] for l in NIVEIS}

    def liberado(*ls):
        return all(n[l] >= MIN_DESCRITIVA for l in ls)

    def firmeza(*ls):
        return "adequada" if all(n[l] >= MIN_ANALISADAS for l in ls) else "indicativa"

    def motivo(*ls):
        return "; ".join(f"{ROTULOS[l]}: {n[l]} vaga(s) analisada(s)" for l in ls if n[l] < MIN_DESCRITIVA) + f" (mínimo para comparar: {MIN_DESCRITIVA})"

    def item(h, dest, ref_pp=None):
        return {"nome": h["nome"], "pct": {l: h["niveis"][l]["pct"] for l in NIVEIS}, "diferenca_pp": ref_pp,
                "obrigatoria_destino": h["niveis"][dest]["obrigatoria"], "diferencial_destino": h["niveis"][dest]["diferencial"],
                "vagas_destino": h["niveis"][dest]["vagas"]}

    def ordenar(itens):
        return sorted(itens, key=lambda i: (-(i["diferenca_pp"] or 0), -i["obrigatoria_destino"], -i["vagas_destino"], i["nome"].casefold()))

    defs = []
    # comuns / estáveis (três níveis)
    comuns = [h for h in tabela if all(_pct(h, l) >= COMUM_MIN_PCT for l in NIVEIS)]
    estaveis = [h for h in comuns if max(_pct(h, l) for l in NIVEIS) - min(_pct(h, l) for l in NIVEIS) <= ESTAVEL_MAX_PP]
    def por_minimo(hs):
        return sorted(hs, key=lambda h: (-min(_pct(h, l) for l in NIVEIS), -h["total_vagas"], h["nome"].casefold()))
    defs += [
        ("comuns", "Habilidades comuns aos três níveis", f"Aparecem em pelo menos {COMUM_MIN_PCT:g}% das vagas analisadas de cada nível.",
         NIVEIS, [item(h, "pleno", None) for h in por_minimo(comuns)]),
        ("estaveis", "Requisitos cuja frequência varia pouco", f"Comuns aos três níveis e com amplitude de até {ESTAVEL_MAX_PP:g} p.p.",
         NIVEIS, [item(h, "pleno", None) for h in por_minimo(estaveis)]),
        ("mais_frequentes_junior", "Mais frequentes nas vagas júnior da amostra",
         f"Frequência júnior pelo menos {DIF_MIN_PP:g} p.p. acima da maior entre pleno e sênior (e presente em {PRESENCA_MIN_PCT:g}%+ das vagas júnior).",
         NIVEIS, ordenar([item(h, "junior", round(_pct(h, "junior") - max(_pct(h, "pleno"), _pct(h, "senior")), 1)) for h in tabela
                          if _pct(h, "junior") >= PRESENCA_MIN_PCT and _pct(h, "junior") - max(_pct(h, "pleno"), _pct(h, "senior")) >= DIF_MIN_PP])),
        ("ganham_junior_pleno", "Ganham relevância de júnior para pleno", f"Aumento de pelo menos {DIF_MIN_PP:g} p.p. (e {PRESENCA_MIN_PCT:g}%+ nas vagas pleno).",
         ("junior", "pleno"), ordenar([item(h, "pleno", h["diferenca_pp"]["junior_pleno"]) for h in tabela
                                       if (h["diferenca_pp"]["junior_pleno"] or 0) >= DIF_MIN_PP and _pct(h, "pleno") >= PRESENCA_MIN_PCT])),
        ("ganham_pleno_senior", "Ganham relevância de pleno para sênior", f"Aumento de pelo menos {DIF_MIN_PP:g} p.p. (e {PRESENCA_MIN_PCT:g}%+ nas vagas sênior).",
         ("pleno", "senior"), ordenar([item(h, "senior", h["diferenca_pp"]["pleno_senior"]) for h in tabela
                                       if (h["diferenca_pp"]["pleno_senior"] or 0) >= DIF_MIN_PP and _pct(h, "senior") >= PRESENCA_MIN_PCT])),
        ("caracteristicas_senior", "Mais características das vagas sênior da amostra",
         f"Frequência sênior pelo menos {DIF_MIN_PP:g} p.p. acima da maior entre júnior e pleno (e {PRESENCA_MIN_PCT:g}%+ das vagas sênior).",
         NIVEIS, ordenar([item(h, "senior", round(_pct(h, "senior") - max(_pct(h, "junior"), _pct(h, "pleno")), 1)) for h in tabela
                          if _pct(h, "senior") >= PRESENCA_MIN_PCT and _pct(h, "senior") - max(_pct(h, "junior"), _pct(h, "pleno")) >= DIF_MIN_PP])),
        ("diminuem_junior_pleno", "Aparecem menos de júnior para pleno", f"Queda de pelo menos {DIF_MIN_PP:g} p.p. (e {PRESENCA_MIN_PCT:g}%+ nas vagas júnior).",
         ("junior", "pleno"), ordenar([item(h, "junior", -h["diferenca_pp"]["junior_pleno"]) for h in tabela
                                       if (h["diferenca_pp"]["junior_pleno"] or 0) <= -DIF_MIN_PP and _pct(h, "junior") >= PRESENCA_MIN_PCT])),
        ("diminuem_pleno_senior", "Aparecem menos de pleno para sênior", f"Queda de pelo menos {DIF_MIN_PP:g} p.p. (e {PRESENCA_MIN_PCT:g}%+ nas vagas pleno).",
         ("pleno", "senior"), ordenar([item(h, "pleno", -h["diferenca_pp"]["pleno_senior"]) for h in tabela
                                       if (h["diferenca_pp"]["pleno_senior"] or 0) <= -DIF_MIN_PP and _pct(h, "pleno") >= PRESENCA_MIN_PCT])),
    ]
    out = []
    for cid, titulo, desc, niveis, itens in defs:
        if not liberado(*niveis):
            out.append({"id": cid, "titulo": titulo, "descricao": desc, "disponivel": False, "motivo": motivo(*niveis), "itens": []})
        else:
            out.append({"id": cid, "titulo": titulo, "descricao": desc, "disponivel": True, "firmeza": firmeza(*niveis), "itens": itens})
    return out


def experiencia(vagas: list[dict]) -> dict:
    out = {}
    for n in NIVEIS:
        base = [v for v in _por_nivel(vagas, n) if v["analisada"] and v["origem"] == "explicita"]
        valores = sorted(v["anos"] for v in base if v["anos"] is not None)
        out[n] = {
            "base": len(base), "com_informacao": len(valores),
            "mediana": median(valores) if len(valores) >= MIN_ANOS_MEDIANA else None,
            "minimo": valores[0] if valores else None, "maximo": valores[-1] if valores else None,
            "valores": valores if 0 < len(valores) < MIN_ANOS_MEDIANA else None,
        }
    return out


def responsabilidades(vagas: list[dict]) -> dict:
    bases = {n: [v for v in _por_nivel(vagas, n) if v["analisada"] and v["origem"] == "explicita"] for n in NIVEIS}
    itens = []
    for chave, (rotulo, _) in RESPONSABILIDADES.items():
        linha = {"chave": chave, "rotulo": rotulo, "niveis": {}}
        for n in NIVEIS:
            m = sum(1 for v in bases[n] if chave in v["resp"])
            linha["niveis"][n] = {"vagas": m, "pct": pct(m, len(bases[n]))}
        itens.append(linha)
    return {"base": {n: len(bases[n]) for n in NIVEIS}, "itens": itens}


def proximo_nivel(tabela: list[dict], stats: dict, perfil: list[str] | None) -> dict:
    """Requisitos mais presentes no nível de destino que não constam no perfil. Sem perfil: disponivel=False."""
    if not perfil:
        return {"disponivel": False, "transicoes": []}
    chaves = {skills.chave(h) for h in perfil}
    transicoes = []
    for de, para in (("junior", "pleno"), ("pleno", "senior")):
        den = stats[para]["analisadas"]
        faltam, presentes = [], 0
        for h in tabela:
            d = h["niveis"][para]
            if not d["vagas"] or (d["pct"] or 0) < PRESENCA_MIN_PCT:
                continue
            if h["chave"] in chaves:
                presentes += 1
                continue
            ref = h["diferenca_pp"]["junior_pleno" if para == "pleno" else "pleno_senior"]
            expl = (f"Aparece em {d['vagas']} de {den} vagas {ROTULOS[para].lower()} analisadas ({d['pct']:g}%); "
                    f"obrigatória em {d['obrigatoria']}, diferencial em {d['diferencial']}"
                    + (f"; {ref:+g} p.p. em relação às vagas {ROTULOS[de].lower()}" if ref is not None else "") + ". Não cadastrada no perfil.")
            faltam.append({"nome": h["nome"], "vagas": d["vagas"], "analisadas": den, "pct": d["pct"], "obrigatoria": d["obrigatoria"],
                           "diferencial": d["diferencial"], "nao_classificada": d["nao_classificada"], "pct_obrigatoria": d["pct_obrigatoria"],
                           "pct_diferencial": d["pct_diferencial"], "diferenca_pp": ref, "nao_cadastrada_no_perfil": True, "explicacao": expl})
        faltam.sort(key=lambda i: (-i["pct"], -i["obrigatoria"], -i["vagas"], i["nome"].casefold()))
        transicoes.append({"de": de, "para": para, "cobertura_destino": stats[para]["cobertura"], "analisadas_destino": den,
                           "ja_no_perfil": presentes, "itens": faltam})
    return {"disponivel": True, "transicoes": transicoes}


def calcular(vagas: list[dict], perfil: list[str] | None = None) -> dict:
    stats = estatisticas_niveis(vagas)
    tabela = tabela_habilidades(vagas, stats)
    return {
        "niveis": stats, "habilidades": tabela, "rankings": rankings(tabela), "categorias": categorias(tabela, stats),
        "experiencia": experiencia(vagas), "responsabilidades": responsabilidades(vagas), "perfil": proximo_nivel(tabela, stats, perfil),
        "limiares": {"min_analisadas": MIN_ANALISADAS, "min_descritiva": MIN_DESCRITIVA, "dif_min_pp": DIF_MIN_PP,
                     "presenca_min_pct": PRESENCA_MIN_PCT, "comum_min_pct": COMUM_MIN_PCT, "estavel_max_pp": ESTAVEL_MAX_PP},
    }
