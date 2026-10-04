import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app import cache  # noqa: E402
from app.aggregate import agregar  # noqa: E402
from app.extract import extrair_todas  # noqa: E402
from app.jobs import ErroVagas, buscar_vagas  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vagas")

app = FastAPI(title="Analisador de requisitos de vagas")
STATIC = Path(__file__).parent / "static"

_cache: dict = {}
TTL = 6 * 3600  # cache em memória do resultado final (as páginas ficam no SQLite)

# Verificação na inicialização: só avisa, não impede o servidor de subir
if os.getenv("PROVEDOR", "adzuna") == "jsearch" and not (
    os.getenv("OPENWEBNINJA_API_KEY") or os.getenv("RAPIDAPI_KEY")
):
    log.warning("PROVEDOR=jsearch, mas OPENWEBNINJA_API_KEY não está definida no .env")


class Pergunta(BaseModel):
    mensagem: str  # o texto inteiro é tratado como o cargo buscado
    pais: str = "br"
    # Cada página = 1 requisição na cota. Vazio = padrão do provedor.
    paginas: int | None = Field(None, ge=1, le=5)


async def analisar(cargo: str, pais: str, paginas: int | None = None) -> dict:
    chave = (cargo.lower().strip(), pais, paginas)
    hit = _cache.get(chave)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]

    try:
        vagas, info = await buscar_vagas(cargo, pais, paginas)
    except ErroVagas as e:
        raise HTTPException(e.status, e.msg)
    if not vagas:
        raise HTTPException(404, "Nenhuma vaga encontrada para essa busca.")

    extracoes, metodo = await extrair_todas(vagas)

    avisos = []
    if info["paginas_ok"] < info["paginas_total"]:
        avisos.append(f"Resultado parcial: {info['paginas_ok']} de {info['paginas_total']} páginas.")
    if metodo == "dicionario" and os.getenv("ANTHROPIC_API_KEY"):
        avisos.append("A extração com a Claude falhou; usei o dicionário de palavras.")

    resultado = {
        "cargo": cargo,
        **agregar(extracoes),
        "metodo": metodo,
        "avisos": avisos,
        "do_cache": info["do_cache"],
        "vagas": [{"titulo": v["titulo"], "empresa": v["empresa"], "link": v["link"]} for v in vagas],
    }
    _cache[chave] = (time.time(), resultado)
    return resultado


def formatar(r: dict) -> str:
    # Texto montado em código: os números vêm da contagem, não do LLM.
    linhas = [f"Analisei {r['vagas_analisadas']} vagas para “{r['cargo']}”.", ""]

    def bloco(titulo: str, itens: list[dict], limite: int):
        if itens:
            linhas.append(titulo)
            linhas.extend(
                f"- {i['nome']}: {i['percentual']}% ({i['vagas']} vagas)" for i in itens[:limite]
            )
            linhas.append("")

    bloco("Tecnologias mais pedidas:", r["tecnologias"], 10)
    bloco("Diferenciais:", r["diferenciais"], 5)
    bloco("Soft skills:", r["soft_skills"], 5)

    if r.get("experiencia_mediana_anos") is not None:
        linhas.append(f"Experiência mínima mediana: {r['experiencia_mediana_anos']} anos")
    return "\n".join(linhas).strip()


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/status")
async def status():
    return {
        "usado": cache.usado(),
        "limite": cache.QUOTA,
        "extracao": "claude" if os.getenv("ANTHROPIC_API_KEY") else "dicionario",
    }


@app.post("/chat")
async def chat(p: Pergunta):
    r = await analisar(p.mensagem, p.pais, p.paginas)
    return {"resposta": formatar(r), "dados": r}


@app.get("/analisar")
async def analisar_get(cargo: str, pais: str = "br", paginas: int | None = Query(None, ge=1, le=5)):
    return await analisar(cargo, pais, paginas)
