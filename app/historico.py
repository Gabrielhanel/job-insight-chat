"""Memória, por consulta, das vagas já exibidas e das páginas já percorridas."""
from app.db import consultar, consultar_varios


def _consulta(cargo: str, pais: str) -> str:
    return f"{pais}|{cargo.lower().strip()}"


def proxima_pagina(cargo: str, pais: str) -> int:
    linhas = consultar("SELECT ultima_pagina FROM progresso WHERE consulta=?", (_consulta(cargo, pais),))
    return (linhas[0][0] if linhas else 0) + 1


def ids_vistos(cargo: str, pais: str) -> set[str]:
    linhas = consultar("SELECT vaga FROM vistas WHERE consulta=?", (_consulta(cargo, pais),))
    return {linha[0] for linha in linhas}


def registrar(cargo: str, pais: str, ids: list[str], ultima_pagina: int | None = None) -> None:
    consulta = _consulta(cargo, pais)
    consultar_varios("INSERT OR IGNORE INTO vistas VALUES (?, ?)", [(consulta, i) for i in ids])
    if ultima_pagina is not None:  # nunca recua: guarda a maior página já percorrida
        consultar(
            "INSERT INTO progresso VALUES (?, ?) ON CONFLICT(consulta) "
            "DO UPDATE SET ultima_pagina = MAX(ultima_pagina, excluded.ultima_pagina)",
            (consulta, ultima_pagina),
        )
