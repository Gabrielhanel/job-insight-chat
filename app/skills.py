"""Normalização e canonicalização de habilidades — fonte única para perfil, extração e comparação.

Regras:
- Comparação ignora maiúsculas/minúsculas, acentos, espaços repetidos e pontuação irrelevante, mas
  PRESERVA símbolos que fazem parte do nome (+ # . /): C, C++ e C# são termos diferentes; .NET != NET.
- Aliases conhecidos (JS -> JavaScript, ...) vêm da tabela do projeto (`aggregate.ALIASES`, que é montada a
  partir de `keywords.py`) mais poucos extras abaixo. Não há correspondência por prefixo/substring nem difusa:
  se o termo não é um alias conhecido, só é igual a outro de mesma chave textual.
- O que é exibido ao usuário é o nome canônico legível (ou a grafia dele, se o termo não é conhecido).
"""
import re
import unicodedata

from app.aggregate import ALIASES as _ALIASES_BASE
from app.keywords import TECNOLOGIAS

# Só o que a tabela do projeto ainda não cobre. "py" ficou de fora de propósito: é ambíguo sem contexto.
EXTRA_ALIASES = {
    "java script": "JavaScript",
    "type script": "TypeScript",
    "node js": "Node.js",
    "react js": "React",
    "reactnative": "React Native",
    "react.native": "React Native",
    "vue js": "Vue",
    "next js": "Next.js",
    "nest js": "NestJS",
    "express js": "Express",
    "python3": "Python",
    "python 3": "Python",
    "csharp": "C#",
    "c plus plus": "C++",
    "dot net": ".NET",
    "asp net": "ASP.NET",
    "asp net core": "ASP.NET",
    "postgre sql": "PostgreSQL",
    "mongo db": "MongoDB",
    "ddd": "Domain-Driven Design",  # o dicionário devolve DDD e Domain-Driven Design para o mesmo texto
}

_RUIDO = re.compile(r"[,;:!?()\[\]{}\"'“”‘’]")


def limpar(termo: str) -> str:
    """Forma de exibição: NFC, espaços colapsados, bordas aparadas. Não altera a grafia."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", termo)).strip()


def chave_texto(termo: str) -> str:
    """Chave de comparação textual (sem aliases). Mantém + # . / e o ponto inicial de '.NET'."""
    t = unicodedata.normalize("NFD", termo)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # sem acentos
    t = _RUIDO.sub(" ", t.casefold())
    t = re.sub(r"[-_\s]+", " ", t).strip()
    return t.rstrip(". ")


def _montar_tabela() -> dict[str, str]:
    tabela = {chave_texto(v): nome for v, nome in _ALIASES_BASE.items()}
    tabela.update({chave_texto(v): nome for v, nome in EXTRA_ALIASES.items()})
    for nome in set(tabela.values()):
        tabela.setdefault(chave_texto(nome), nome)
    return tabela


_TABELA = _montar_tabela()


def canonizar(termo: str) -> str:
    """Nome canônico legível: alias conhecido -> nome do projeto; desconhecido -> grafia limpa do usuário."""
    return _TABELA.get(chave_texto(termo)) or limpar(termo)


def chave(termo: str) -> str:
    """Identidade para comparar, deduplicar e contar (mesma regra em perfil, vagas e priorização)."""
    return chave_texto(canonizar(termo))


def mesma_habilidade(a: str, b: str) -> bool:
    return bool(chave(a)) and chave(a) == chave(b)


# Ordem do dicionário (linguagens primeiro, depois frameworks...): usada só para escolher termos de busca.
_POSICAO = {chave(nome): i for i, nome in enumerate(TECNOLOGIAS)}


def posicao_no_dicionario(termo: str) -> int | None:
    return _POSICAO.get(chave(termo))


def variantes(nome: str) -> list[str]:
    """Grafias conhecidas de uma habilidade (para localizar o trecho do anúncio que a evidencia), mais longas primeiro."""
    k = chave(nome)
    achadas = {nome.lower()}
    achadas |= {v for v, n in {**_ALIASES_BASE, **EXTRA_ALIASES}.items() if chave(n) == k}
    return sorted(achadas, key=lambda v: (-len(v), v))


# Relações técnicas CURADAS e conservadoras (não derivam de semelhança de texto). Servem só para uma observação
# complementar na comparação de vagas: nunca contam como habilidade comum.
RELACOES = [
    ("JavaScript", "TypeScript", "TypeScript é um superconjunto tipado de JavaScript, mas exige conhecimento próprio"),
    ("JavaScript", "Node.js", "Node.js executa JavaScript no servidor, com ecossistema próprio"),
    ("JavaScript", "React", "React é uma biblioteca escrita em JavaScript"),
    ("React", "React Native", "React Native usa React para apps móveis, com conhecimento de plataforma adicional"),
    ("SQL", "PostgreSQL", "PostgreSQL é um banco de dados que usa SQL"),
    ("SQL", "MySQL", "MySQL é um banco de dados que usa SQL"),
    (".NET", "ASP.NET", "ASP.NET é um framework web sobre a plataforma .NET"),
    ("Java", "Kotlin", "ambas rodam na JVM, mas são linguagens diferentes"),
    ("Java", "Spring", "Spring é um framework do ecossistema Java"),
    ("Python", "Django", "Django é um framework web em Python"),
    ("Python", "FastAPI", "FastAPI é um framework web em Python"),
    ("Python", "Flask", "Flask é um framework web em Python"),
]
_REL: dict[str, list[tuple[str, str, str]]] = {}
for _a, _b, _m in RELACOES:
    _REL.setdefault(chave(_a), []).append((chave(_b), canonizar(_b), _m))
    _REL.setdefault(chave(_b), []).append((chave(_a), canonizar(_a), _m))


def relacionadas(termo: str) -> list[tuple[str, str, str]]:
    """[(chave, nome canônico, motivo)] das habilidades relacionadas, mas distintas, de `termo`."""
    return _REL.get(chave(termo), [])
