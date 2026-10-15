"""Caso de uso: evolução por senioridade — compara requisitos observados em vagas júnior, pleno e sênior.

Fluxo: 1 consulta por nível (mesmo cargo + termo do nível) pelo `jobs.buscar_vagas` existente (cache e cota
iguais aos das outras buscas) -> junta e deduplica -> checa contexto -> classifica senioridade por evidências
(`senioridade.py`) -> extrai requisitos só das vagas dos 3 níveis comparados (`extract.extrair_por_vaga`, por id)
-> estatísticas e diferenças em p.p. (`comparativo.py`). Nada é guardado no banco: repetir a análise substitui o
resultado (as páginas vêm do cache, sem gastar cota).

O nível de uma vaga vem das EVIDÊNCIAS dela, nunca da consulta que a trouxe: uma vaga retornada pela busca
"júnior" mas intitulada "Sênior" entra no grupo sênior.
"""
import logging
import re

from app import cache, comparativo, jobs, perfil, skills
from app.extract import extrair_por_vaga
from app.keywords import extrair_dicionario
from app.senioridade import OUTROS, PRINCIPAIS, ROTULOS, classificar, normalizar, responsabilidades

log = logging.getLogger("vagas")

MAX_PAGINAS = 3  # por nível (3 níveis => no máximo 9 requisições, ~10 anúncios por página)
MIN_CARGO, MAX_CARGO = 2, 80
# "Associate" não é usado: não equivale a um nível em qualquer contexto.
TERMOS_CONSULTA = {
    "pt": {"junior": "júnior", "pleno": "pleno", "senior": "sênior"},
    "en": {"junior": "junior", "pleno": "mid-level", "senior": "senior"},
}
ADERENCIA_MIN = 0.6


class ErroEvolucao(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def planejar(cargo: str, pais: str = "br", paginas: int = 2) -> dict:
    """Consultas que seriam feitas (sem chamar o provedor)."""
    cargo = skills.limpar(cargo or "")
    if len(cargo) < MIN_CARGO:
        raise ErroEvolucao(422, "Informe um cargo, tecnologia ou área (por exemplo: Desenvolvedor React Native).")
    if len(cargo) > MAX_CARGO:
        raise ErroEvolucao(422, f"O cargo pode ter no máximo {MAX_CARGO} caracteres (atual: {len(cargo)}).")
    if not 1 <= paginas <= MAX_PAGINAS:
        raise ErroEvolucao(422, f"Escolha de 1 a {MAX_PAGINAS} páginas por nível.")
    termos = TERMOS_CONSULTA["pt" if pais == "br" else "en"]
    provedor, ok = jobs.provedor_status()
    consultas = [{"nivel": n, "texto": f"{cargo} {termos[n]}"} for n in PRINCIPAIS]
    return {
        "cargo": cargo, "consultas": consultas, "paginas": paginas, "requisicoes_max": len(consultas) * paginas,
        "usado": cache.usado(), "limite": cache.QUOTA, "provedor": provedor, "credenciais": ok,
        "cache_ttl_horas": cache.TTL // 3600,
    }


# ---------------------------------------------------------------- contexto
def termos_de_contexto(cargo: str) -> list[str]:
    """Tecnologias reconhecidas no cargo (a mais específica vence: 'React Native' dispensa 'React')."""
    achadas = extrair_dicionario({"titulo": cargo, "descricao": ""})["tecnologias"]
    chaves = {skills.chave(t): t for t in achadas}
    return [n for k, n in chaves.items() if not any(o != k and o.startswith(k + " ") for o in chaves)]


_FILLERS = {"de", "da", "do", "das", "dos", "e", "em", "para", "pessoa", "a", "o", "com", "na", "no"}


def _tokens(texto: str) -> set[str]:
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", "", normalizar(texto))
    return {w[:6] for w in re.findall(r"[a-z0-9+#.]{3,}", t) if w not in _FILLERS}


def _menciona(vaga: dict, chaves_ctx: set[str]) -> bool:
    ext = extrair_dicionario({"titulo": vaga["titulo"], "descricao": vaga["descricao"]})
    return any(skills.chave(t) in chaves_ctx for t in ext["tecnologias"] + ext["diferenciais"])


# ---------------------------------------------------------------- requisitos por categoria
_MARC_REQ = re.compile(r"requisit|obrigat|pre[- ]?requisit|qualifica|must have|o que (?:esperamos|buscamos|precisamos)|conhecimentos? (?:necessarios|tecnicos)")
_MARC_DIF = re.compile(r"diferencial|desejav|nice to have|bonus|\bplus\b")


def categorizar_requisitos(extracao: dict, descricao: str, metodo: str | None) -> tuple[dict, dict, dict]:
    """(obrigatórios, diferenciais, não classificados): chave canônica -> nome, cada habilidade uma vez por vaga.

    O dicionário trata como obrigatório tudo que está fora da seção de diferenciais. Quando o texto não traz nenhum
    marcador explícito (requisitos/obrigatório/diferencial/desejável...), essa suposição não se sustenta: as
    tecnologias ficam como "não classificadas". Com extração por IA mantém-se a divisão que ela devolveu."""
    def unicos(itens):
        out = {}
        for i in itens or []:
            out.setdefault(skills.chave(i), skills.canonizar(i))
        out.pop("", None)
        return out

    obrig, dif = unicos(extracao.get("tecnologias")), unicos(extracao.get("diferenciais"))
    dif = {k: n for k, n in dif.items() if k not in obrig}
    if metodo == "dicionario":
        d = normalizar(descricao)
        if not _MARC_REQ.search(d) and not _MARC_DIF.search(d):
            return {}, dif, obrig  # sem marcador: nada pode ser afirmado como obrigatório
    return obrig, dif, {}


# ---------------------------------------------------------------- análise
def _msg_credenciais(provedor: str) -> str:
    quais = "OPENWEBNINJA_API_KEY (ou RAPIDAPI_KEY)" if provedor == "jsearch" else "ADZUNA_APP_ID e ADZUNA_APP_KEY"
    return f"A busca real está indisponível: faltam as credenciais do provedor de vagas ({quais}) no .env."


def _link_seguro(link):
    return link if isinstance(link, str) and link.lower().startswith(("http://", "https://")) else None


async def analisar(cargo: str, pais: str, paginas: int, habilidades: list[str] | None = None) -> dict:
    plano = planejar(cargo, pais, paginas)
    cargo = plano["cargo"]
    if not plano["credenciais"]:
        raise ErroEvolucao(503, _msg_credenciais(plano["provedor"]))

    usado_antes = cache.usado()
    avisos: list[str] = []
    erros: list[jobs.ErroVagas] = []
    unicas: dict[str, dict] = {}
    consultada: dict[str, set] = {}
    status_consulta = {n: "nao_consultada" for n in PRINCIPAIS}
    retornadas = do_cache = 0

    for c in plano["consultas"]:
        try:
            vagas, info = await jobs.buscar_vagas(c["texto"], pais, paginas, 1, por_anuncio=True)
        except jobs.ErroVagas as e:
            erros.append(e)
            status_consulta[c["nivel"]] = "falhou"
            avisos.append(f"A consulta de vagas {ROTULOS[c['nivel']].lower()} falhou: {e.msg}")
            if e.status == 429:  # cota/limite: para e preserva o que já veio
                break
            continue
        status_consulta[c["nivel"]] = "ok"
        retornadas += info["total_bruto"]
        do_cache += info["do_cache"]
        if info["paginas_ok"] < info["paginas_total"]:
            avisos.append(f"Resultado parcial na consulta {ROTULOS[c['nivel']].lower()}: {info['paginas_ok']} de {info['paginas_total']} páginas.")
        for v in vagas:
            unicas.setdefault(v["id"], v)
            consultada.setdefault(v["id"], set()).add(c["nivel"])
    if not any(s == "ok" for s in status_consulta.values()):
        raise ErroEvolucao(erros[0].status, erros[0].msg)
    nao_consultadas = [n for n, s in status_consulta.items() if s == "nao_consultada"]
    if nao_consultadas:
        avisos.append("Consultas não realizadas por limite de cota: " + ", ".join(ROTULOS[n].lower() for n in nao_consultadas) + ". Os resultados obtidos foram preservados.")

    todas = list(unicas.values())
    ctx_termos = termos_de_contexto(cargo)
    ctx_chaves = {skills.chave(t) for t in ctx_termos}
    contexto_verificavel = bool(ctx_chaves)
    classificadas: list[dict] = []
    for v in todas:
        cls = classificar(v["titulo"], v["descricao"])
        fora = contexto_verificavel and not _menciona(v, ctx_chaves)
        classificadas.append({"vaga": v, "cls": cls, "fora": fora})

    no_ctx = [x for x in classificadas if not x["fora"]]
    if not contexto_verificavel and no_ctx:
        toks = _tokens(cargo)
        if toks:
            aderentes = sum(1 for x in no_ctx if toks & _tokens(x["vaga"]["titulo"] + " " + x["vaga"]["descricao"]))
            avisos.append("O cargo informado não tem tecnologia reconhecida; não é possível garantir que todas as vagas sejam da mesma área. "
                          f"{aderentes} de {len(no_ctx)} vagas citam termos do cargo.")
            if aderentes / len(no_ctx) < ADERENCIA_MIN:
                avisos.append("Poucas vagas citam os termos do cargo: a comparação pode estar misturando áreas diferentes.")
    n_fora = len(classificadas) - len(no_ctx)
    if n_fora:
        avisos.append(f"{n_fora} vaga(s) não citam a tecnologia do contexto ({', '.join(ctx_termos)}) e foram deixadas fora dos cálculos.")

    alvo = [x for x in no_ctx if x["cls"]["nivel"] in PRINCIPAIS]
    extracoes = await extrair_por_vaga([x["vaga"] for x in alvo]) if alvo else {}

    if habilidades is None:
        try:
            habilidades = perfil.obter_habilidades()["habilidades"]
        except perfil.ErroPerfil:
            habilidades = []
            avisos.append("Não foi possível ler as habilidades do perfil; a comparação com o perfil foi omitida.")

    jobs_calc = []
    for x in alvo:
        v, cls = x["vaga"], x["cls"]
        item = extracoes[v["id"]]
        ext = item["extracao"]
        obrig, dif, nc = categorizar_requisitos(ext, v["descricao"], item["metodo"]) if ext else ({}, {}, {})
        x["analisada"], x["incompleta"], x["metodo"], x["motivo_analise"] = ext is not None, item["incompleta"], item["metodo"], item["motivo"]
        jobs_calc.append({"id": v["id"], "nivel": cls["nivel"], "analisada": ext is not None, "incompleta": item["incompleta"],
                          "origem": cls["origem"], "obrig": obrig, "dif": dif, "nc": nc, "anos": cls["anos_min"],
                          "resp": responsabilidades(v["descricao"])})
    comp = comparativo.calcular(jobs_calc, habilidades)

    n_nc = [x for x in no_ctx if x["cls"]["nivel"] == "nao_classificado"]
    contagens = {
        "retornadas": retornadas, "unicas": len(todas), "fora_do_contexto": n_fora, "no_contexto": len(no_ctx),
        "classificadas": len(no_ctx) - len(n_nc), "principais": len(alvo),
        "outros": {o: sum(1 for x in no_ctx if x["cls"]["nivel"] == o) for o in OUTROS},
        "nao_classificadas": {"total": len(n_nc), "conflitante": sum(1 for x in n_nc if x["cls"]["conflito"]),
                              "informacao_insuficiente": sum(1 for x in n_nc if not x["cls"]["conflito"])},
        "analisadas": sum(1 for x in alvo if x["analisada"]), "sem_analise": sum(1 for x in alvo if not x["analisada"]),
        "analise_incompleta": sum(1 for x in alvo if x["incompleta"]),
        "explicitas": sum(1 for x in alvo if x["cls"]["origem"] == "explicita"), "inferidas": sum(1 for x in alvo if x["cls"]["origem"] == "inferida"),
    }
    if contagens["analise_incompleta"]:
        avisos.append(f"{contagens['analise_incompleta']} vaga(s) com análise incompleta (a IA falhou e o dicionário foi usado).")
    if contagens["sem_analise"]:
        avisos.append(f"{contagens['sem_analise']} vaga(s) sem requisitos analisados ficaram fora dos percentuais.")
    if no_ctx and len(n_nc) / len(no_ctx) > 0.5:
        avisos.append("Mais da metade das vagas não indica o nível de forma confiável; os grupos refletem só as vagas classificadas.")
    for n in PRINCIPAIS:
        cob = comp["niveis"][n]["cobertura"]
        if cob == "sem_dados":
            avisos.append(f"Nenhuma vaga {ROTULOS[n].lower()} classificada e analisada: comparações com esse nível não foram calculadas.")
        elif cob in ("insuficiente", "baixa"):
            avisos.append(f"Cobertura {cob} no nível {ROTULOS[n].lower()}: {comp['niveis'][n]['analisadas']} vaga(s) analisada(s) (adequado: {comparativo.MIN_ANALISADAS}+). Trate os percentuais como indicativos.")
    requisicoes = max(0, cache.usado() - usado_antes)
    todo_cache = requisicoes == 0 and do_cache > 0
    if todo_cache:
        avisos.append(f"Resultados vindos do cache (válido por até {plano['cache_ttl_horas']} h), sem novas requisições.")

    estado = "ok"
    if not todas:
        estado = "sem_vagas"
    elif not alvo:
        estado = "sem_classificadas"

    vagas_out = [{
        "id": x["vaga"]["id"], "titulo": x["vaga"]["titulo"], "empresa": x["vaga"]["empresa"], "local": x["vaga"]["local"] or None,
        "link": _link_seguro(x["vaga"]["link"]), "nivel": x["cls"]["nivel"], "rotulo": x["cls"]["rotulo"], "categoria": x["cls"]["categoria"],
        "origem": x["cls"]["origem"], "confianca": x["cls"]["confianca"], "motivo": x["cls"]["motivo"], "fora_do_contexto": x["fora"],
        "analisada": x.get("analisada"), "analise_incompleta": x.get("incompleta", False),
        "encontrada_nas_consultas": sorted(consultada[x["vaga"]["id"]]),
    } for x in classificadas]

    return {
        "estado": estado, "cargo": cargo, "consultas": plano["consultas"], "status_consultas": status_consulta, "paginas": paginas,
        "contexto": {"tecnologias": ctx_termos, "verificavel": contexto_verificavel},
        "contagens": contagens, "comparacao_confiavel": all(comp["niveis"][n]["cobertura"] == "adequada" for n in PRINCIPAIS),
        **comp, "perfil_habilidades": len(habilidades), "avisos": avisos, "vagas": vagas_out,
        "do_cache": do_cache, "todo_do_cache": todo_cache, "cache_ttl_horas": plano["cache_ttl_horas"], "requisicoes_feitas": requisicoes,
        "usado": cache.usado(), "limite": cache.QUOTA,
    }
