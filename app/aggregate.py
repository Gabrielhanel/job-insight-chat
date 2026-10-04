from collections import Counter
from statistics import median

from app.keywords import SOFT, TECNOLOGIAS

# Fonte única: variantes do keywords.py + extras que só o LLM costuma devolver
ALIASES = {v.lower(): nome for d in (TECNOLOGIAS, SOFT) for nome, vs in d.items() for v in vs}
ALIASES.update({"ts": "TypeScript", "rn": "React Native", ".net core": ".NET", "google cloud platform": "Google Cloud"})


def canon(termo: str) -> str:
    t = " ".join(termo.split())
    return ALIASES.get(t.lower(), t)


def _ranking(listas: list[list[str]], total: int, top: int, minimo: int = 1) -> list[dict]:
    cont: Counter = Counter()
    nomes: dict[str, str] = {}
    for itens in listas:
        # conta cada termo no máximo uma vez por vaga
        unicos: dict[str, str] = {}
        for item in itens:
            nome = canon(item)
            if nome:
                unicos.setdefault(nome.lower(), nome)
        for chave, nome in unicos.items():
            cont[chave] += 1
            nomes.setdefault(chave, nome)
    return [
        {"nome": nomes[k], "vagas": c, "percentual": round(100 * c / total)}
        for k, c in cont.most_common(top)
        if c >= minimo
    ]


def agregar(extracoes: list[dict], top: int = 15) -> dict:
    n = len(extracoes)
    minimo = 2 if n >= 8 else 1  # esconde termos de uma única vaga em amostras grandes
    if n == 0:
        return {"vagas_analisadas": 0}
    anos = [
        e["anos_experiencia_min"]
        for e in extracoes
        if isinstance(e.get("anos_experiencia_min"), int)
    ]
    return {
        "vagas_analisadas": n,
        "tecnologias": _ranking([e.get("tecnologias", []) for e in extracoes], n, top, minimo),
        "diferenciais": _ranking([e.get("diferenciais", []) for e in extracoes], n, top, minimo),
        "soft_skills": _ranking([e.get("soft_skills", []) for e in extracoes], n, 8, minimo),
        "niveis": dict(Counter(e.get("nivel", "nao_informado") for e in extracoes)),
        "experiencia_mediana_anos": median(anos) if anos else None,
    }
