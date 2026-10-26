"""Sobe o app real com o provedor de vagas SIMULADO (só para testes de interface; nada aqui é dado de mercado).

Cenários por texto da consulta: "Vazio" -> sem vagas; "Falha" -> HTTP 401 do provedor; "Cota" -> HTTP 429.
UI_SEM_CHAVE=1 inicia sem credenciais. Porta em UI_PORT; banco em CACHE_DB.
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from tests.falso_provedor import FILLER, Provedor, vaga  # noqa: E402

os.environ["PROVEDOR"] = "jsearch"
for k in ("OPENWEBNINJA_API_KEY", "RAPIDAPI_KEY", "ANTHROPIC_API_KEY", "CHAVE_OPENROUTER"):
    os.environ.pop(k, None)
if not os.environ.get("UI_SEM_CHAVE"):
    os.environ["OPENWEBNINJA_API_KEY"] = "chave-de-teste"

p = Provedor()


ROT = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior"}


def evolucao(query, page):
    """Vagas SINTÉTICAS por nível para a tela de evolução. Cenários pelo texto do cargo: Poucas, SoJunior, SemNivel."""
    q = query.lower()
    nv = "junior" if "júnior" in q else ("pleno" if "pleno" in q else "senior")
    if "SoJunior" in query and nv != "junior":
        return []
    n = 2 if "Poucas" in query else {"junior": 12, "pleno": 10, "senior": 4}[nv]
    ts, git = {"junior": (2, 9), "pleno": (4, 7), "senior": (3, 1)}[nv]
    faixa = range(0, 10) if page == 1 else (range(10, n) if page == 2 else range(0))
    out = []
    for i in faixa:
        if i >= n:
            break
        obrig = ["React Native", "JavaScript"] + (["TypeScript"] if i < ts else []) + (["Git"] if i < git else [])
        titulo = "Desenvolvedor React Native" + ("" if "SemNivel" in query else " " + ROT[nv])
        out.append(vaga(f"{nv}-{i}", titulo, f"Empresa {nv}{i}", obrig, ["Docker"] if i < 2 else []))
    if nv == "junior" and page == 2 and "Poucas" not in query and "SemNivel" not in query:
        out += [
            vaga("c1", "Desenvolvedor React Native Júnior/Pleno", "X", ["React Native"]),
            vaga("nc1", 'Desenvolvedor React Native <img src=x onerror="window.__xss=1">', "Y", ["React Native"]),
            vaga("es1", "Estagiário React Native", "Z", ["React Native", "JavaScript"]),
            vaga("fora1", "Desenvolvedor Java Sênior", "W", ["Java", "Spring"]),
        ]
    return out


def vl(id_, titulo, empresa, obrig, dif=(), extra="", **kw):
    """Vaga SINTÉTICA com descrição longa (>300 caracteres), para a análise não ser marcada como limitada por tamanho."""
    d = f"Requisitos: {', '.join(obrig)}.{extra}{FILLER}{FILLER}" + (f"\nDiferenciais:\n{', '.join(dif)}\n" if dif else "")
    return vaga(id_, titulo, empresa, descricao=d, **kw)


def cmpvagas(query, page):
    """Vagas SINTÉTICAS para a tela de comparação (consultas que começam com 'Cmp')."""
    if "Vazio" in query or page != 1:
        return []
    if "Anos" in query:
        return [vl("ca1", "Dev Pleno Anos", "Alfa", ["Python", "SQL"], extra=" 3 anos de experiência."),
                vl("ca2", "Dev Sênior Anos", "Beta", ["Python", "Go"], extra=" 5 a 7 anos de experiência.")]
    if "SemMarcador" in query:
        texto = f"Usamos Python e SQL no dia a dia do time de dados.{FILLER}{FILLER}"   # nenhum marcador de obrigatório/desejável
        return [vaga("sm1", "Dev Dados SemMarcador", "Alfa", descricao=texto), vl("sm2", "Dev Dados Marcado", "Beta", ["Python", "Docker"])]
    if "Curta" in query:
        return [vaga("cc1", "Dev Curta", "Alfa", descricao="Requisitos: Python, SQL, Docker. " + "Contexto breve da vaga. " * 4),
                vl("cc2", "Dev Longa", "Beta", ["Python", "Go", "Rust"])]
    if "Backend" in query:
        return [
            vl("cb1", "Desenvolvedor Back-end Pleno", "Alfa", ["Python", "PostgreSQL", "Docker"], ["Kafka"], link="https://alfa.test/cb1"),
            vl("cb2", "Desenvolvedor Back-end Sênior", "Beta", ["Python", "AWS", "Kubernetes"], ["Terraform"], link="javascript:alert(1)"),
            vl("cb3", '<img src=x onerror="window.__xss=1">', "Empresa <b>X</b>", ["Python", "Redis"]),
            vaga("cb4", "Dev Sem Descrição", "Delta", descricao=""),
        ]
    return [
        vl("cf1", "Desenvolvedor Front-end Pleno", "Gama", ["JavaScript", "React", "CSS"], ["TypeScript"], link="https://gama.test/cf1"),
        vl("cf2", "Desenvolvedor Front-end Pleno", "Gama", ["JavaScript", "Angular", "HTML"], ["Jest"], link="https://gama.test/cf2"),
    ]


def grafvagas(query, page):
    """Vagas SINTÉTICAS para o chat tradicional (consultas 'Graf ...'). Contagens fixas para conferir os gráficos."""
    if page != 1:
        return []
    if "Pleno100" in query:
        return [vaga(f"p{i}", f"Desenvolvedor Pleno {i}", f"Emp{i}", ["JavaScript"]) for i in range(8)]
    if "Poucos" in query:   # sem soft skills, sem diferenciais e sem nível: gráficos correspondentes devem ser omitidos
        apoio = "Texto de apoio sobre o contexto técnico do produto e do time de engenharia responsável. " * 3
        return [vaga("q0", "Desenvolvedor Web", "Alfa", descricao=f"Requisitos: JavaScript, React. {apoio}"),
                vaga("q1", "Desenvolvedor Web", "Beta", descricao=f"Requisitos: JavaScript. {apoio}")]
    # 12 vagas: 4 júnior, 4 pleno, 3 sênior, 1 sem nível
    cont = {"JavaScript": 12, "React": 9, "Git": 6, "TypeScript": 5, "Docker": 4, "SQL": 3, "Python": 3, "AWS": 2, "Kubernetes": 2,
            "Realidade aumentada": 2, "Event-Driven Architecture": 2, "Redis": 2}
    dif = {"Terraform": 3, "Kafka": 2}
    soft = {"comunicação": 12, "trabalho em equipe": 8, "proatividade": 3, "resolução de problemas": 2}
    niveis = ["Júnior"] * 4 + ["Pleno"] * 4 + ["Sênior"] * 3 + [""]
    out = []
    for i, nv in enumerate(niveis):
        obrig = [t for t, c in cont.items() if i < c]
        d = [t for t, c in dif.items() if i < c]
        sf = [t for t, c in soft.items() if i < c]
        texto = f"Requisitos: {', '.join(obrig)}. Perfil com {', '.join(sf)}.{FILLER}" + (f"\nDiferenciais:\n{', '.join(d)}\n" if d else "")
        out.append(vaga(f"g{i}", f"Desenvolvedor Fullstack {nv}".strip(), f"Empresa{i}", descricao=texto))
    return out


ID_LONGO = ("eyJqb2JfdGl0bGUiOiJTb2Z0d2FyZSBFbmdpbmVlciIsImNvbXBhbnlfbmFtZSI6IkV4YW1wbGUifQ" * 7)[:456]   # job_id de 456 caracteres
ID_ENORME = "Z" * 1200   # acima do limite de 1024


def idlongo(query, page):
    if page != 1:
        return []
    return [vl(ID_LONGO, "Dev Python IdLongo", "Alfa", ["Python", "SQL", "Docker"]), vl(ID_ENORME, "Dev Go IdEnorme", "Beta", ["Rust", "Perl", "Ruby"]),
            vl("curto", "Dev Java IdCurto", "Gama", ["Java", "Spring"])]


def paginas(query, page):
    if page > 5:
        return []
    return [vl(f"pg{page}-{i}", f"Dev Pagina{page} Vaga{i}", f"Emp{page}{i}", ["Python", "SQL"]) for i in range(2)]


def resposta(query, page):
    if "IdLongo" in query:
        return idlongo(query, page)
    if "Paginas" in query:
        return paginas(query, page)
    if query.startswith("Graf"):
        return grafvagas(query, page)
    if query.startswith("Cmp"):
        return cmpvagas(query, page)
    if "Desenvolvedor React Native" in query and "Vazio" not in query:
        return evolucao(query, page)
    if "Vazio" in query or page >= 3:
        return []
    out = [
        vaga(f"a{page}", "Dev Fullstack", "Alfa", ["JavaScript", "Java", "Docker"], ["Kubernetes", "TypeScript"]),
        vaga(f"b{page}", '<img src=x onerror="window.__xss=1">', "Empresa <b>X</b>", ["Python", "SQL", "Docker"],
             link="javascript:alert(1)"),
    ]
    if page == 1:
        out.append(vaga("curta", "Vaga curta", "Gama", descricao="Pouco texto."))
        out.append(vaga("longa", "T" * 200, "E" * 150, ["React", "Node.js", "AWS"], link="https://ok.test/vaga?x=1"))
    return out


p.resposta = resposta
p.falha = lambda params: 429 if "Cota" in params["query"] else (401 if "Falha" in params["query"] else None)

original = httpx.AsyncClient


class Falso(original):
    def __init__(self, *a, **k):
        k["transport"] = httpx.MockTransport(p.handler)
        super().__init__(*a, **k)


httpx.AsyncClient = Falso

from app.main import app  # noqa: E402

uvicorn.run(app, port=int(os.environ["UI_PORT"]), log_level="warning")
