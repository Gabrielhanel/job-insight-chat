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

from tests.falso_provedor import Provedor, vaga  # noqa: E402

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


def resposta(query, page):
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
