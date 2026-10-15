import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app import cache, evolucao, perfil, reversa  # noqa: E402
from app.aggregate import agregar  # noqa: E402
from app.busca import coletar  # noqa: E402
from app.extract import extrair_todas  # noqa: E402
from app.jobs import ErroVagas  # noqa: E402

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
    apenas_novas: bool = False  # True: só vagas ainda não exibidas para esta consulta


class PerfilEntrada(BaseModel):
    nome: str = ""  # vazio é válido: o perfil não é obrigatório para usar a aplicação
    areas: list[str] = []


class HabilidadesEntrada(BaseModel):
    habilidades: list[str] = []


class TermoEntrada(BaseModel):
    termo: str = ""


class BuscaHabilidades(BaseModel):
    habilidades: list[str] | None = None  # None = usar as habilidades salvas no perfil
    area: str | None = None  # contexto opcional (uma área do perfil), entra no texto da consulta
    pais: str = Field("br", pattern=r"^[a-z]{2}$")
    paginas: int = Field(1, ge=1, le=reversa.MAX_PAGINAS)  # por consulta; cada página = 1 requisição se não estiver em cache


class EvolucaoEntrada(BaseModel):
    cargo: str = ""
    pais: str = Field("br", pattern=r"^[a-z]{2}$")
    paginas: int = Field(2, ge=1, le=evolucao.MAX_PAGINAS)  # por nível; cada página = 1 requisição se não estiver em cache
    habilidades: list[str] | None = None  # None = habilidades salvas no perfil (opcional: sem perfil a análise funciona igual)


MSG_SEM_NOVAS = "Não localizamos novas vagas semelhantes à descrição solicitada."


async def analisar(cargo: str, pais: str, paginas: int | None = None, apenas_novas: bool = False) -> dict:
    chave = (cargo.lower().strip(), pais, paginas)
    hit = None if apenas_novas else _cache.get(chave)  # buscas por novidades nunca usam este cache
    if hit and time.time() - hit[0] < TTL:
        return hit[1]

    try:
        vagas, info = await coletar(cargo, pais, paginas, apenas_novas)
    except ErroVagas as e:
        raise HTTPException(e.status, e.msg)
    if not vagas:
        if apenas_novas:
            return {"cargo": cargo, "sem_novas": True, "aviso": MSG_SEM_NOVAS}
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
        "novas": apenas_novas,
        "metodo": metodo,
        "avisos": avisos,
        "do_cache": info["do_cache"],
        "vagas": [{"titulo": v["titulo"], "empresa": v["empresa"], "link": v["link"]} for v in vagas],
    }
    if not apenas_novas:
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
    r = await analisar(p.mensagem, p.pais, p.paginas, p.apenas_novas)
    return {"resposta": r["aviso"] if r.get("sem_novas") else formatar(r), "dados": r}


@app.get("/analisar")
async def analisar_get(cargo: str, pais: str = "br", paginas: int | None = Query(None, ge=1, le=5)):
    return await analisar(cargo, pais, paginas)


@app.get("/perfil")
async def perfil_obter():
    try:
        return perfil.obter()
    except perfil.ErroPerfil as e:
        raise HTTPException(e.status, e.msg)


@app.put("/perfil")
async def perfil_salvar(p: PerfilEntrada):
    # Substitui o perfil inteiro (nome + lista de áreas): adicionar/remover áreas = enviar a lista nova.
    try:
        return perfil.salvar(p.nome, p.areas)
    except perfil.ErroPerfil as e:
        raise HTTPException(e.status, e.msg)


@app.get("/habilidades")
async def habilidades_obter():
    try:
        return perfil.obter_habilidades()
    except perfil.ErroPerfil as e:
        raise HTTPException(e.status, e.msg)


@app.put("/habilidades")
async def habilidades_salvar(p: HabilidadesEntrada):
    # Substitui só a lista de habilidades; nome e áreas do perfil não são tocados.
    try:
        return perfil.salvar_habilidades(p.habilidades)
    except perfil.ErroPerfil as e:
        raise HTTPException(e.status, e.msg)


@app.post("/habilidades/normalizar")
async def habilidades_normalizar(p: TermoEntrada):
    # Regra única de canonicalização para a interface (evita duplicar aliases em JavaScript).
    try:
        return perfil.normalizar_habilidade(p.termo)
    except perfil.ErroPerfil as e:
        raise HTTPException(e.status, e.msg)


def _habilidades_da_busca(p: BuscaHabilidades) -> list[str]:
    if p.habilidades is None:
        return perfil.obter_habilidades()["habilidades"]
    return [n for _, n in perfil.validar_habilidades(p.habilidades)]


@app.post("/busca-habilidades/plano")
async def busca_habilidades_plano(p: BuscaHabilidades):
    """Mostra as consultas e o consumo máximo de requisições, sem chamar o provedor."""
    try:
        return reversa.planejar(_habilidades_da_busca(p), p.area, p.paginas)
    except (reversa.ErroReversa, perfil.ErroPerfil) as e:
        raise HTTPException(e.status, e.msg)


@app.post("/busca-habilidades")
async def busca_habilidades(p: BuscaHabilidades):
    try:
        return await reversa.buscar(_habilidades_da_busca(p), p.area, p.pais, p.paginas)
    except (reversa.ErroReversa, perfil.ErroPerfil) as e:
        raise HTTPException(e.status, e.msg)


@app.post("/evolucao/plano")
async def evolucao_plano(p: EvolucaoEntrada):
    """Consultas por nível e consumo máximo de requisições, sem chamar o provedor."""
    try:
        return evolucao.planejar(p.cargo, p.pais, p.paginas)
    except evolucao.ErroEvolucao as e:
        raise HTTPException(e.status, e.msg)


@app.post("/evolucao")
async def evolucao_analisar(p: EvolucaoEntrada):
    try:
        habilidades = None if p.habilidades is None else [n for _, n in perfil.validar_habilidades(p.habilidades)]
        return await evolucao.analisar(p.cargo, p.pais, p.paginas, habilidades)
    except (evolucao.ErroEvolucao, perfil.ErroPerfil) as e:
        raise HTTPException(e.status, e.msg)
