"""Regras determinísticas da busca por habilidades (sem I/O e sem IA).

COMPATIBILIDADE ESTIMADA (cobertura dos requisitos identificados no anúncio):

    100 × (2·OC + DC) / (2·OT + DT)

    OT = requisitos obrigatórios identificados   OC = obrigatórios que constam no perfil
    DT = diferenciais identificados              DC = diferenciais que constam no perfil

Cada requisito canônico conta uma vez por vaga (se aparecer como obrigatório e como diferencial, vale como
obrigatório). Sem nenhum requisito identificado (denominador 0) não há pontuação: estado "dados_insuficientes".
Não é probabilidade de contratação: ignora senioridade, anos de experiência e formação.
"""
from app import skills

PESO_OBRIGATORIO = 2
PESO_DIFERENCIAL = 1
MIN_REQUISITOS_CONFIAVEL = 3  # abaixo disso a nota é calculada, mas marcada como de confiança baixa
DESCRICAO_CURTA = 300  # caracteres


def _unicos(itens) -> dict[str, str]:
    """chave canônica -> nome canônico, sem repetir (mantém a ordem de aparição)."""
    out: dict[str, str] = {}
    for item in itens or []:
        if isinstance(item, str) and item.strip():
            out.setdefault(skills.chave(item), skills.canonizar(item))
    out.pop("", None)
    return out


def avaliar(extracao: dict | None, chaves_perfil: set[str], descricao_curta: bool = False) -> dict:
    base = {
        "estado": "sem_analise",
        "compatibilidade": None,
        "confianca": None,
        "requisitos_total": 0,
        "obrigatorios_total": 0,
        "diferenciais_total": 0,
        "obrigatorios_correspondidos": 0,
        "diferenciais_correspondidos": 0,
        "correspondencias": [],
        "faltando_obrigatorios": [],
        "faltando_diferenciais": [],
        "soft_skills": [],
        "nivel": None,
        "anos_experiencia_min": None,
        "avisos": [],
    }
    if extracao is None:
        base["avisos"].append("Esta vaga não pôde ser analisada.")
        return base

    obrig = _unicos(extracao.get("tecnologias"))
    dif = {k: n for k, n in _unicos(extracao.get("diferenciais")).items() if k not in obrig}
    oc = [n for k, n in obrig.items() if k in chaves_perfil]
    dc = [n for k, n in dif.items() if k in chaves_perfil]
    total = len(obrig) + len(dif)

    base.update(
        requisitos_total=total,
        obrigatorios_total=len(obrig),
        diferenciais_total=len(dif),
        obrigatorios_correspondidos=len(oc),
        diferenciais_correspondidos=len(dc),
        correspondencias=oc + dc,
        faltando_obrigatorios=[n for k, n in obrig.items() if k not in chaves_perfil],
        faltando_diferenciais=[n for k, n in dif.items() if k not in chaves_perfil],
        soft_skills=sorted(_unicos(extracao.get("soft_skills")).values(), key=str.casefold),
        nivel=extracao.get("nivel") if extracao.get("nivel") != "nao_informado" else None,
        anos_experiencia_min=extracao.get("anos_experiencia_min"),
    )
    if descricao_curta:
        base["avisos"].append("Descrição curta: a avaliação é limitada pelos dados disponíveis.")
    if total == 0:
        base["estado"] = "dados_insuficientes"
        base["avisos"].append("Nenhum requisito identificado na descrição; não há pontuação.")
        return base

    peso_total = PESO_OBRIGATORIO * len(obrig) + PESO_DIFERENCIAL * len(dif)
    peso_ok = PESO_OBRIGATORIO * len(oc) + PESO_DIFERENCIAL * len(dc)
    base["estado"] = "avaliada"
    base["compatibilidade"] = round(100 * peso_ok / peso_total, 1)
    base["confianca"] = "normal" if total >= MIN_REQUISITOS_CONFIAVEL and not descricao_curta else "baixa"
    if total < MIN_REQUISITOS_CONFIAVEL:
        base["avisos"].append(f"Só {total} requisito(s) identificado(s): a nota tem pouca base.")
    return base


def ordenar(vagas: list[dict]) -> list[dict]:
    """Avaliadas (confiança normal) -> avaliadas (confiança baixa) -> dados insuficientes -> sem análise.

    Dentro de cada grupo: maior compatibilidade, mais obrigatórios correspondidos, menos obrigatórios
    faltando e, por fim, título (desempate estável). Vagas sem pontuação nunca recebem posição por nota.
    """

    def grupo(v):
        if v["estado"] == "avaliada":
            return 0 if v["confianca"] == "normal" else 1
        return 2 if v["estado"] == "dados_insuficientes" else 3

    return sorted(
        vagas,
        key=lambda v: (
            grupo(v),
            -(v["compatibilidade"] or 0),
            -v["obrigatorios_correspondidos"],
            len(v["faltando_obrigatorios"]),
            (v.get("titulo") or "").casefold(),
            v.get("id") or "",
        ),
    )


def priorizar_lacunas(avaliacoes: list[dict], top: int = 20) -> dict:
    """Requisitos que não constam no perfil, por relevância nas vagas efetivamente avaliadas.

    Base = vagas com ao menos um requisito identificado. Ordem: nº de vagas em que aparece, depois nº como
    obrigatório, depois nº como diferencial, depois nome (desempate fixo). Percentual = vagas / base.
    """
    avaliadas = [a for a in avaliacoes if a["estado"] == "avaliada"]
    base = len(avaliadas)
    cont: dict[str, dict] = {}
    for a in avaliadas:
        for nome in a["faltando_obrigatorios"]:
            c = cont.setdefault(skills.chave(nome), {"nome": nome, "obrigatoria": 0, "diferencial": 0})
            c["obrigatoria"] += 1
        for nome in a["faltando_diferenciais"]:
            c = cont.setdefault(skills.chave(nome), {"nome": nome, "obrigatoria": 0, "diferencial": 0})
            c["diferencial"] += 1
    itens = [
        {
            "nome": c["nome"],
            "vagas": c["obrigatoria"] + c["diferencial"],
            "percentual": round(100 * (c["obrigatoria"] + c["diferencial"]) / base),
            "como_obrigatoria": c["obrigatoria"],
            "como_diferencial": c["diferencial"],
        }
        for c in cont.values()
    ]
    itens.sort(key=lambda i: (-i["vagas"], -i["como_obrigatoria"], -i["como_diferencial"], i["nome"].casefold()))
    return {"base": base, "total": len(itens), "itens": itens[:top]}
