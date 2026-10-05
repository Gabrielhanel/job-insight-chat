"""Caso de uso: coletar as vagas de uma consulta, opcionalmente só as ainda não exibidas."""
from app import historico
from app.jobs import buscar_vagas


async def coletar(
    cargo: str, pais: str, paginas: int | None, apenas_novas: bool = False
) -> tuple[list[dict], dict]:
    # Busca nova continua de onde a anterior parou: as páginas já percorridas ficam para trás.
    inicio = historico.proxima_pagina(cargo, pais) if apenas_novas else 1
    vagas, info = await buscar_vagas(cargo, pais, paginas, inicio)

    if apenas_novas:
        vistas = historico.ids_vistos(cargo, pais)
        vagas = [v for v in vagas if v["id"] not in vistas]

    # Só avança a paginação se todas as páginas responderam e havia resultados; assim, quando
    # as vagas acabam, cliques repetidos releem páginas vazias do cache em vez de gastar cota.
    avancar = info["paginas_ok"] == info["paginas_total"] and info["total_bruto"] > 0
    historico.registrar(cargo, pais, [v["id"] for v in vagas], info["ultima_pagina"] if avancar else None)
    return vagas, info
