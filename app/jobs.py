import asyncio
import os

import httpx

from app import cache

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{pais}/search/{pagina}"
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"  # via RapidAPI (antigo)
OPENWEBNINJA_URL = "https://api.openwebninja.com/jsearch/search"  # JSearch no OpenWeb Ninja


class ErroVagas(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _converter(e: Exception) -> Exception:
    if isinstance(e, ErroVagas):
        return e
    if isinstance(e, httpx.HTTPStatusError):
        c = e.response.status_code
        if c in (401, 403):
            return ErroVagas(502, "A API de vagas recusou a chave (inválida ou plano não assinado).")
        if c == 429:
            return ErroVagas(429, "Limite de requisições da API de vagas atingido.")
        return ErroVagas(502, f"API de vagas indisponível ({c}). Tente de novo em instantes.")
    if isinstance(e, httpx.HTTPError):
        return ErroVagas(502, "Tempo esgotado ou falha de conexão com a API de vagas.")
    return e


def _credenciais() -> tuple[str, dict]:
    if os.getenv("OPENWEBNINJA_API_KEY"):
        return OPENWEBNINJA_URL, {"x-api-key": os.environ["OPENWEBNINJA_API_KEY"]}
    if os.getenv("RAPIDAPI_KEY"):
        return JSEARCH_URL, {
            "X-RapidAPI-Key": os.environ["RAPIDAPI_KEY"],
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        }
    raise ErroVagas(500, "Defina OPENWEBNINJA_API_KEY no .env.")


async def _adzuna(cargo: str, pais: str, paginas: int) -> tuple[list[dict], dict]:
    if not (os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY")):
        raise ErroVagas(500, "Defina ADZUNA_APP_ID e ADZUNA_APP_KEY no .env.")
    brutas = []
    async with httpx.AsyncClient(timeout=60) as client:
        for pagina in range(1, paginas + 1):
            r = await client.get(
                ADZUNA_URL.format(pais=pais, pagina=pagina),
                params={
                    "app_id": os.environ["ADZUNA_APP_ID"],
                    "app_key": os.environ["ADZUNA_APP_KEY"],
                    "what": cargo,
                    "results_per_page": 50,
                },
            )
            r.raise_for_status()
            for v in r.json().get("results", []):
                brutas.append(
                    {
                        "titulo": v.get("title"),
                        "empresa": (v.get("company") or {}).get("display_name"),
                        "descricao": v.get("description"),
                        "link": v.get("redirect_url"),
                    }
                )
    return brutas, {"paginas_ok": paginas, "paginas_total": paginas, "do_cache": 0}


async def _jsearch(cargo: str, pais: str, paginas: int) -> tuple[list[dict], dict]:
    url, headers = _credenciais()
    base = cargo.lower().strip()

    async def pagina(client: httpx.AsyncClient, n: int) -> tuple[list, bool]:
        chave = f"jsearch|{pais}|{base}|{n}"
        hit = cache.pegar(chave)
        if hit is not None:
            return hit, True  # página já buscada: não gasta cota
        params = {"query": cargo, "page": n, "num_pages": 1, "country": pais, "date_posted": "month"}
        for tentativa in range(2):  # 1 nova tentativa em timeout/erro 5xx
            if cache.usado() >= cache.QUOTA:
                raise ErroVagas(429, f"Cota local de {cache.QUOTA} requisições/mês esgotada.")
            cache.registrar()
            try:
                r = await client.get(url, headers=headers, params=params)
                r.raise_for_status()
                dados = r.json().get("data", [])
                cache.salvar(chave, dados)
                return dados, False
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                cliente = isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500
                if cliente or tentativa == 1:
                    raise
                await asyncio.sleep(2)

    async with httpx.AsyncClient(timeout=60) as client:
        res = await asyncio.gather(
            *(pagina(client, n) for n in range(1, paginas + 1)), return_exceptions=True
        )
    ok = [r for r in res if not isinstance(r, Exception)]
    if not ok:
        raise _converter(next(r for r in res if isinstance(r, Exception)))
    brutas = [
        {
            "titulo": v.get("job_title"),
            "empresa": v.get("employer_name"),
            "descricao": v.get("job_description"),
            "link": v.get("job_apply_link"),
        }
        for dados, _ in ok
        for v in dados
    ]
    info = {"paginas_ok": len(ok), "paginas_total": paginas, "do_cache": sum(1 for _, c in ok if c)}
    return brutas, info


def _limpar(brutas: list[dict]) -> list[dict]:
    vistos, vagas = set(), []
    for v in brutas:
        titulo, empresa = v["titulo"] or "", v["empresa"] or ""
        desc = v["descricao"] or ""
        chave = (titulo.lower(), empresa.lower())
        # descarta duplicadas e descrições curtas demais para extrair algo útil
        if chave in vistos or len(desc) < 150:
            continue
        vistos.add(chave)
        vagas.append({"titulo": titulo, "empresa": empresa, "descricao": desc[:6000], "link": v["link"]})
    return vagas


async def buscar_vagas(cargo: str, pais: str = "br", paginas: int | None = None) -> tuple[list[dict], dict]:
    """PROVEDOR=adzuna (padrão) ou jsearch. Devolve (vagas, info de páginas/cache)."""
    try:
        if os.getenv("PROVEDOR", "adzuna") == "jsearch":
            brutas, info = await _jsearch(cargo, pais, paginas or 3)  # ~10 vagas por página
        else:
            brutas, info = await _adzuna(cargo, pais, paginas or 1)  # até 50 vagas por página
    except (httpx.HTTPError, ErroVagas) as e:
        raise _converter(e)
    return _limpar(brutas), info
