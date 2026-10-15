"""Classificação de senioridade por evidências (determinística, sem IA) + experiência e responsabilidades.

Níveis comparáveis: junior, pleno, senior. Fora deles (preservados, mas fora das porcentagens): estagio, lideranca,
especialista. Sem evidência suficiente ou com evidências contraditórias: nao_classificado (nunca forçado a um nível).

Regras (nesta ordem):
1. Título com UM nível explícito -> esse nível (origem "explicita", confiança "alta"), desde que a descrição não o
   contradiga (frase explícita de outro nível, ou anos mínimos claramente fora da faixa do nível).
   Título com mais de um nível (ex.: "Júnior/Pleno") ou contradição -> nao_classificado (conflitante).
   Exceção documentada: "Sênior" + (liderança|especialista) no mesmo título vale como o cargo de liderança/especialista.
2. Sem nível no título: uma frase explícita na descrição ("vaga de nível pleno", "atuar como sênior") -> nível
   (origem "inferida", confiança "media"). Frases de níveis diferentes -> conflitante.
3. Sem nada disso: indícios somados (anos mínimos, responsabilidades típicas). Só classifica se a soma for >= 3 e
   superar o 2º colocado por >= 2. Nunca se usa a quantidade de tecnologias nem o tamanho da descrição.
A "confiança" é categórica e vem da regra aplicada; não é probabilidade estatística.
"""
import re
import unicodedata

PRINCIPAIS = ("junior", "pleno", "senior")
OUTROS = ("estagio", "lideranca", "especialista")
ROTULOS = {
    "junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "estagio": "Estágio/trainee",
    "lideranca": "Liderança/gestão", "especialista": "Especialista/arquitetura", "nao_classificado": "Não classificado",
}

# Faixas de anos mínimos usadas só para DETECTAR contradição com o título (inclusive).
FAIXA_CONTRADICAO = {"junior": (0, 4), "pleno": (1, 7), "senior": (2, 40)}
# Limiar de indícios para inferir sem título/frase explícita.
INDICIOS_MIN = 3
INDICIOS_MARGEM = 2


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


_A = r"(?<![a-z0-9])"  # fronteira esquerda (sem \b para tratar "pl/sql" e "jr.")
_Z = r"(?![a-z0-9])"
_TITULO = {
    "estagio": rf"estagi|{_A}intern(?:ship)?{_Z}|trainee|aprendiz",
    "lideranca": rf"tech lead|team lead|{_A}lead{_Z}|{_A}leader{_Z}|lider|gerente|coordenador|{_A}head{_Z}|manager|diretor|supervisor",
    "especialista": rf"especialista|specialist|{_A}staff{_Z}|{_A}principal{_Z}|arquitet[oa]|architect",
    "junior": rf"{_A}(?:junior|jr){_Z}|entry[ -]?level",
    "pleno": rf"{_A}pleno{_Z}|mid[ -]?level|{_A}mid{_Z}|{_A}middle{_Z}|{_A}pl(?![a-z0-9/])(?!\s*sql)",
    "senior": rf"{_A}(?:senior|sr){_Z}",
}
_TITULO = {k: re.compile(v) for k, v in _TITULO.items()}


def niveis_no_titulo(titulo: str) -> set[str]:
    t = re.sub(r"[()\[\]{},;:|]", " ", normalizar(titulo))
    return {nivel for nivel, rx in _TITULO.items() if rx.search(t)}


def _resolver_titulo(niveis: set[str]) -> tuple[str | None, str | None]:
    """(nível, None) | (None, descrição do conflito) | (None, None) se o título não traz nível."""
    if not niveis:
        return None, None
    if len(niveis) == 1:
        return next(iter(niveis)), None
    if "senior" in niveis and len(niveis) == 2:
        outro = (niveis - {"senior"}).pop()
        if outro in ("lideranca", "especialista"):
            return outro, None
    return None, "o título cita mais de um nível (" + " e ".join(ROTULOS[n] for n in sorted(niveis)) + ")"


_NIVEL = r"(junior|pleno|senior)(?![a-z0-9])"
_FRASES = [
    re.compile(rf"(?:vaga|nivel|posicao|cargo|senioridade|level)\s*(?:de|para|:|-)?\s*(?:\w+\s+){{0,2}}?{_NIVEL}"),
    re.compile(rf"(?:atuar|atuara|atuacao|trabalhar|trabalhara)\s+como\s+(?:\w+\s+){{0,3}}?{_NIVEL}"),
    re.compile(rf"(?:buscamos|procuramos|buscando|procurando|contratando|contratar|selecionando)\s+(?:\w+\s+){{0,4}}?{_NIVEL}"),
]


def niveis_na_descricao(descricao: str) -> dict[str, str]:
    """nível -> trecho que o evidenciou. Só frases contextuais; 'mentoria de sêniores' não conta."""
    d = re.sub(r"\s+", " ", normalizar(descricao))
    achados: dict[str, str] = {}
    for rx in _FRASES:
        for m in rx.finditer(d):
            achados.setdefault(m.group(1), m.group(0)[:80])
    return achados


# ---------------------------------------------------------------- experiência
_EXP = r"(?:experiencia|experience|vivencia)"
_ANOS = r"(?:anos?|years?)"
_PADROES_ANOS = [
    re.compile(rf"(\d{{1,2}})\s*(?:a|-|ate|to)\s*\d{{1,2}}\s*\+?\s*{_ANOS}(?:\s+de|\s+of)?\s*(?:de\s+)?{_EXP}"),
    re.compile(rf"(\d{{1,2}})\s*\+?\s*{_ANOS}\s+(?:de\s+|of\s+)?{_EXP}"),
    re.compile(rf"{_EXP}[^.\n]{{0,40}}?(\d{{1,2}})\s*(?:a|-|ate|to)\s*\d{{1,2}}\s*\+?\s*{_ANOS}"),
    re.compile(rf"{_EXP}[^.\n]{{0,40}}?(\d{{1,2}})\s*\+?\s*{_ANOS}"),
]


def anos_minimos(texto: str) -> dict:
    """Anos de experiência citados junto da palavra 'experiência'. Em faixas ('3 a 5 anos') vale o início.
    Com valores diferentes no texto, 'min' é o menor e 'valores' guarda todos (a ambiguidade fica visível)."""
    t = normalizar(texto)
    valores = sorted({int(m.group(1)) for rx in _PADROES_ANOS for m in rx.finditer(t) if 0 <= int(m.group(1)) <= 40})
    return {"min": valores[0] if valores else None, "valores": valores}


# ---------------------------------------------------------------- responsabilidades
RESPONSABILIDADES = {
    "desenvolvimento": ("Desenvolvimento de software", r"desenvolv(?:er|imento) de (?:software|sistemas|funcionalidades|aplicac\w+|features|apis?)|implementar|codificar"),
    "revisao_codigo": ("Revisão de código", r"code review|revis(?:ao|oes) de codigo|revisar codigo"),
    "mentoria": ("Mentoria/orientação", r"mentor\w*|orientar (?:outros |os |o )?(?:desenvolvedores|profissionais|time|equipe|colegas)|coach"),
    "arquitetura": ("Arquitetura", r"arquitetura|arquiteto|architect|system design|design de sistemas|desenho de solucoes"),
    "decisoes_tecnicas": ("Decisões técnicas", r"decisoes? tecnicas?|definir (?:a |as )?(?:stack|padroes|arquitetura|tecnologias)|definicao de (?:padroes|arquitetura|tecnologias?)|technical decisions"),
    "autonomia": ("Autonomia", r"autonomia|autonomo|independente"),
    "negocio": ("Contato com o negócio", r"requisitos de negocio|regras de negocio|areas? de negocio|stakeholders|product owner|levantamento de requisitos|business requirements"),
    "colaboracao": ("Colaboração entre equipes", r"trabalho em equipe|colabora\w*|multidisciplinar|squad|pair programming"),
    "entregas": ("Responsabilidade por entregas/sistemas", r"ponta a ponta|end[- ]to[- ]end|ownership|responsavel por (?:entregar|sistemas|projetos|entregas|produtos|modulos)|responsabilidade por (?:entregas|sistemas|projetos)"),
    "lideranca_tecnica": ("Liderança técnica", r"lideranca tecnica|liderar|tech lead|lider tecnico"),
}
_RESP = {k: (rot, re.compile(rx)) for k, (rot, rx) in RESPONSABILIDADES.items()}
_CUES_SENIOR = ("mentoria", "arquitetura", "decisoes_tecnicas", "lideranca_tecnica")
_CUES_JUNIOR = re.compile(
    r"aprend(?:er|izado|izagem)|sob supervisao|acompanhamento (?:de|por) (?:profissionais|desenvolvedores|colegas|time)"
    r"|primeira experiencia|sem experiencia previa|nao (?:e|eh) necessari[oa] (?:ter )?experiencia|inicio de carreira"
)


def responsabilidades(descricao: str) -> set[str]:
    d = normalizar(descricao)
    return {k for k, (_, rx) in _RESP.items() if rx.search(d)}


# ---------------------------------------------------------------- classificação
def _resultado(nivel, origem, confianca, motivo, evidencias=(), conflito=False, anos=None):
    categoria = "principal" if nivel in PRINCIPAIS else ("outro" if nivel in OUTROS else "nao_classificado")
    return {
        "nivel": nivel, "rotulo": ROTULOS[nivel], "categoria": categoria, "origem": origem, "confianca": confianca,
        "motivo": motivo, "evidencias": list(evidencias), "conflito": conflito, "anos_min": anos,
    }


def _na_faixa(nivel: str, anos: int) -> bool:
    lo, hi = FAIXA_CONTRADICAO[nivel]
    return lo <= anos <= hi


def classificar(titulo: str, descricao: str) -> dict:
    titulo, descricao = titulo or "", descricao or ""
    anos = anos_minimos(descricao)["min"]
    frases = niveis_na_descricao(descricao)

    nivel_t, conflito_t = _resolver_titulo(niveis_no_titulo(titulo))
    if conflito_t:
        return _resultado("nao_classificado", None, None, f"Informações conflitantes: {conflito_t}.", conflito=True, anos=anos)

    if nivel_t:
        if nivel_t in OUTROS:
            return _resultado(nivel_t, "explicita", "alta",
                              f"Título identificado como {ROTULOS[nivel_t]} (fora das categorias júnior/pleno/sênior).",
                              [f"título: {titulo.strip()[:80]}"], anos=anos)
        outros_niveis = [n for n in frases if n != nivel_t]
        if outros_niveis:
            return _resultado("nao_classificado", None, None,
                              f"Informações conflitantes: título indica {ROTULOS[nivel_t]}, mas a descrição cita nível {ROTULOS[outros_niveis[0]]}.",
                              [frases[outros_niveis[0]]], conflito=True, anos=anos)
        if anos is not None and not _na_faixa(nivel_t, anos):
            return _resultado("nao_classificado", None, None,
                              f"Informações conflitantes: título indica {ROTULOS[nivel_t]}, mas a descrição pede {anos} ano(s) de experiência.",
                              [f"experiência mínima: {anos} ano(s)"], conflito=True, anos=anos)
        confirma = nivel_t in frases or (anos is not None and _na_faixa(nivel_t, anos))
        return _resultado(nivel_t, "explicita", "alta",
                          f"Título identificado explicitamente como {ROTULOS[nivel_t]}." + (" A descrição é compatível." if confirma else ""),
                          [f"título: {titulo.strip()[:80]}"], anos=anos)

    if len(frases) > 1:
        return _resultado("nao_classificado", None, None,
                          "Informações conflitantes: a descrição cita mais de um nível (" + " e ".join(ROTULOS[n] for n in sorted(frases)) + ").",
                          list(frases.values()), conflito=True, anos=anos)
    if len(frases) == 1:
        nivel, trecho = next(iter(frases.items()))
        return _resultado(nivel, "inferida", "media", f"A descrição cita nível {ROTULOS[nivel]} explicitamente.", [trecho], anos=anos)

    pontos = {n: 0 for n in PRINCIPAIS}
    evid: dict[str, list[str]] = {n: [] for n in PRINCIPAIS}
    if anos is not None:
        alvo = "junior" if anos <= 1 else ("pleno" if anos <= 4 else "senior")
        pontos[alvo] += 1
        evid[alvo].append(f"experiência mínima de {anos} ano(s)")
    resp = responsabilidades(descricao)
    for c in _CUES_SENIOR:
        if c in resp:
            pontos["senior"] += 1
            evid["senior"].append(RESPONSABILIDADES[c][0].lower())
    if _CUES_JUNIOR.search(normalizar(descricao)):
        pontos["junior"] += 1
        evid["junior"].append("aprendizado/acompanhamento citado")
    ordem = sorted(pontos.items(), key=lambda kv: -kv[1])
    (topo, p1), (_, p2) = ordem[0], ordem[1]
    if p1 >= INDICIOS_MIN and p1 - p2 >= INDICIOS_MARGEM:
        return _resultado(topo, "inferida", "media",
                          f"Classificação baseada em múltiplos indícios da descrição ({', '.join(evid[topo])}).", evid[topo], anos=anos)
    return _resultado("nao_classificado", None, None, "Informação insuficiente para classificar.", anos=anos)
