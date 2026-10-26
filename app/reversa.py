"""Caso de uso: busca reversa — das habilidades do usuário para vagas, compatibilidade e lacunas.

Fluxo: planejar consultas (determinístico) -> coletar páginas pelo mesmo `jobs.buscar_vagas` da busca por cargo
(cache e cota existentes) -> extrair requisitos por vaga -> calcular compatibilidade em código -> priorizar lacunas.
Não usa `historico`: a paginação aqui é sem estado (o cliente pede N páginas; as já lidas vêm do cache e não
gastam cota), então a busca por cargo e a busca por habilidades nunca alteram o progresso uma da outra.
"""
import logging
import math

from app import cache, compat, jobs, skills
from app.extract import extrair_por_vaga

log = logging.getLogger("vagas")

MAX_CONSULTAS = 2  # teto de consultas distintas por busca (nunca uma por habilidade)
HABILIDADES_POR_CONSULTA = {"jsearch": 3, "adzuna": 2}  # texto livre: poucos termos por consulta evitam resultados vazios
MAX_PAGINAS = 5  # por consulta, igual ao teto da busca por cargo
MAX_AREA = 60


class ErroReversa(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _prioridade(item: tuple[str, str]):
    chave, nome = item
    pos = skills.posicao_no_dicionario(nome)
    return (0, pos, chave) if pos is not None else (1, 0, chave)  # conhecidas primeiro, ordem do dicionário


def _unicas(habilidades: list[str]) -> list[tuple[str, str]]:
    vistas: dict[str, str] = {}
    for h in habilidades:
        nome = skills.canonizar(h)
        vistas.setdefault(skills.chave(nome), nome)
    vistas.pop("", None)
    return list(vistas.items())


def planejar(habilidades: list[str], area: str | None = None, paginas: int = 1) -> dict:
    """Consultas que seriam enviadas ao provedor. Não faz chamadas externas. Independe da ordem de entrada."""
    if not 1 <= paginas <= MAX_PAGINAS:
        raise ErroReversa(422, f"Escolha de 1 a {MAX_PAGINAS} páginas por consulta.")
    itens = sorted(_unicas(habilidades), key=_prioridade)
    if not itens:
        raise ErroReversa(
            422, "Informe ao menos uma habilidade (por exemplo: Python, React, SQL) para buscar vagas."
        )
    provedor, ok = jobs.provedor_status()
    por = HABILIDADES_POR_CONSULTA.get(provedor, 2)
    usadas = itens[: por * MAX_CONSULTAS]
    fora = itens[por * MAX_CONSULTAS :]
    k = min(MAX_CONSULTAS, math.ceil(len(usadas) / por))
    grupos = [usadas[i::k] for i in range(k)]  # alternado: cada consulta mistura termos "mais" e "menos" básicos
    contexto = skills.limpar(area)[:MAX_AREA] if area else ""
    consultas = [
        {"texto": " ".join(([contexto] if contexto else []) + [n for _, n in g]), "habilidades": [n for _, n in g]}
        for g in grupos
    ]
    return {
        "consultas": consultas,
        "contexto": contexto or None,
        "habilidades_na_busca": [n for _, n in usadas],
        "habilidades_fora_da_busca": [n for _, n in fora],
        "paginas": paginas,
        "requisicoes_max": len(consultas) * paginas,  # páginas já em cache não gastam cota
        "usado": cache.usado(),
        "limite": cache.QUOTA,
        "provedor": provedor,
        "credenciais": ok,
    }


def _msg_credenciais(provedor: str) -> str:
    quais = "OPENWEBNINJA_API_KEY (ou RAPIDAPI_KEY)" if provedor == "jsearch" else "ADZUNA_APP_ID e ADZUNA_APP_KEY"
    return f"A busca real está indisponível: faltam as credenciais do provedor de vagas ({quais}) no .env."


def _link_seguro(link) -> str | None:
    return link if isinstance(link, str) and link.lower().startswith(("http://", "https://")) else None


async def buscar(habilidades: list[str], area: str | None, pais: str, paginas: int) -> dict:
    plano = planejar(habilidades, area, paginas)
    if not plano["credenciais"]:
        raise ErroReversa(503, _msg_credenciais(plano["provedor"]))

    usado_antes = cache.usado()
    avisos: list[str] = []
    erros: list[jobs.ErroVagas] = []
    unicas: dict[str, dict] = {}
    retornadas = do_cache = consultas_ok = 0

    for consulta in plano["consultas"]:
        try:
            vagas, info = await jobs.buscar_vagas(consulta["texto"], pais, paginas, 1, por_anuncio=True)
        except jobs.ErroVagas as e:  # falha de uma consulta não derruba as outras
            erros.append(e)
            avisos.append(f"A consulta “{consulta['texto']}” falhou: {e.msg}")
            if e.status == 429:  # cota/limite: não insiste nas próximas
                break
            continue
        consultas_ok += 1
        retornadas += info["total_bruto"]
        do_cache += info["do_cache"]
        if info["paginas_ok"] < info["paginas_total"]:
            avisos.append(
                f"Resultado parcial na consulta “{consulta['texto']}”: {info['paginas_ok']} de {info['paginas_total']} páginas."
            )
        for v in vagas:
            v["_consulta"] = consulta["texto"]  # consulta que trouxe a vaga (referência para comparar vagas)
            unicas.setdefault(v["id"], v)  # a mesma vaga vinda de duas consultas conta uma vez

    if consultas_ok == 0:
        raise ErroReversa(erros[0].status, erros[0].msg)

    vagas = list(unicas.values())
    base_resposta = {
        "consultas": plano["consultas"],
        "habilidades": [skills.canonizar(h) for h in habilidades],
        "habilidades_na_busca": plano["habilidades_na_busca"],
        "habilidades_fora_da_busca": plano["habilidades_fora_da_busca"],
        "paginas": paginas,
        "max_paginas": MAX_PAGINAS,
        "pode_carregar_mais": paginas < MAX_PAGINAS and not any(e.status == 429 for e in erros),
        "do_cache": do_cache,
        "requisicoes_feitas": max(0, cache.usado() - usado_antes),
        "usado": cache.usado(),
        "limite": cache.QUOTA,
    }
    if plano["habilidades_fora_da_busca"]:
        avisos.append(
            f"{len(plano['habilidades_fora_da_busca'])} habilidade(s) ficaram fora do texto da consulta "
            "(limite de termos por consulta), mas contam na compatibilidade."
        )
    if not vagas:
        return {**base_resposta, "estado": "sem_vagas", "avisos": avisos, "vagas": [], "lacunas": compat.priorizar_lacunas([]),
                "contagens": {"retornadas": retornadas, "unicas": 0, "avaliadas": 0, "dados_insuficientes": 0,
                              "sem_analise": 0, "analise_incompleta": 0}}

    extracoes = await extrair_por_vaga(vagas)  # id da vaga -> extração (sem depender de índice)
    chaves_perfil = {skills.chave(h) for h in habilidades}
    saida = []
    for v in vagas:
        item = extracoes[v["id"]]
        av = compat.avaliar(item["extracao"], chaves_perfil, descricao_curta=len(v["descricao"]) < compat.DESCRICAO_CURTA)
        if item["motivo"]:
            av["avisos"].append(item["motivo"])
        saida.append(
            {
                "id": v["id"], "provedor": v.get("provedor"), "titulo": v["titulo"], "empresa": v["empresa"], "local": v["local"] or None,
                "link": _link_seguro(v["link"]), "metodo": item["metodo"], "analise_incompleta": item["incompleta"],
                "ref": {"consulta": v["_consulta"], "pais": pais, "paginas": paginas}, **av,
            }
        )
    saida = compat.ordenar(saida)
    contagens = {
        "retornadas": retornadas,
        "unicas": len(saida),
        "avaliadas": sum(1 for s in saida if s["estado"] == "avaliada"),
        "dados_insuficientes": sum(1 for s in saida if s["estado"] == "dados_insuficientes"),
        "sem_analise": sum(1 for s in saida if s["estado"] == "sem_analise"),
        "analise_incompleta": sum(1 for s in saida if s["analise_incompleta"]),
    }
    if contagens["analise_incompleta"]:
        avisos.append(f"{contagens['analise_incompleta']} vaga(s) com análise incompleta (veja o aviso em cada uma).")
    if contagens["avaliadas"] < 5:
        avisos.append("Poucas vagas avaliadas: as prioridades de estudo abaixo têm base pequena.")
    return {
        **base_resposta,
        "estado": "ok",
        "avisos": avisos,
        "contagens": contagens,
        "vagas": saida,
        "lacunas": compat.priorizar_lacunas(saida),
    }
