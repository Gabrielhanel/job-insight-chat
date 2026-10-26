"""Comparação de duas vagas: análise individual com evidências + diferenças (regras determinísticas, sem I/O nem IA).

Princípios:
- Tudo vem da vaga: cada habilidade/responsabilidade/formação traz o TRECHO da descrição original que a sustenta
  (ou "trecho não localizado"). Nada é preenchido por suposição; o que falta fica "não identificado".
- Dado ausente != requisito ausente: "não identificada na descrição" só vira afirmação forte quando a outra vaga foi
  analisada sem limitações (confiança de ausência "alta"); caso contrário a lista traz o aviso de que pode ser omissão.
- A compatibilidade com o perfil é a de `compat.avaliar` (fórmula da Etapa 2, sem alterações).
- Habilidades equivalentes = mesma chave canônica (`skills.chave`); "relacionadas, mas distintas" vêm de um mapa curado
  (`skills.RELACOES`) e nunca contam como comuns.
"""
import re

from app import compat, skills
from app.evolucao import categorizar_requisitos
from app.senioridade import PRINCIPAIS, RESPONSABILIDADES, ROTULOS, anos_minimos, classificar, normalizar

JANELA = 60  # caracteres de contexto ao redor do trecho-evidência


# ---------------------------------------------------------------- evidências no texto original
def _recorte(texto: str, ini: int, fim: int) -> str:
    a, b = max(0, ini - JANELA), min(len(texto), fim + JANELA)
    return ("…" if a else "") + re.sub(r"\s+", " ", texto[a:b]).strip() + ("…" if b < len(texto) else "")


def trecho_habilidade(descricao: str, nome: str) -> str | None:
    for v in skills.variantes(nome):
        m = re.search(r"(?<![\w.+#])" + re.escape(v) + r"(?![\w+#])", descricao, re.I)
        if m:
            return _recorte(descricao, m.start(), m.end())
    return None


def trecho_regex(descricao: str, rx: "re.Pattern") -> str | None:
    """rx atua no texto sem acentos/minúsculo; se os comprimentos coincidem o trecho sai do texto original."""
    norm = normalizar(descricao)
    m = rx.search(norm)
    if not m:
        return None
    return _recorte(descricao if len(norm) == len(descricao) else norm, m.start(), m.end())


_RESP = {k: (rot, re.compile(rx)) for k, (rot, rx) in RESPONSABILIDADES.items()}
_FORMACAO = [
    ("Ensino médio", r"ensino medio|segundo grau"),
    ("Ensino superior (graduação/bacharelado/tecnólogo)", r"ensino superior|graduacao|bacharelado|tecnologo|superior completo|superior em|formacao (?:em|superior)"),
    ("Graduação em andamento", r"cursando (?:ensino superior|graduacao|ciencia|engenharia|sistemas|analise)|graduando"),
    ("Pós-graduação/MBA", r"pos[- ]graduacao|\bmba\b|especializacao"),
    ("Mestrado/doutorado", r"mestrado|doutorado|\bphd\b"),
]
_CERT = [
    ("AWS Certified", r"aws certified[\w \-]{0,40}"), ("Azure (AZ-/AI-/DP-/SC-)", r"\b(?:az|ai|dp|sc)-\d{3}\b"), ("PMP", r"\bpmp\b"),
    ("CISSP", r"\bcissp\b"), ("CEH", r"\bceh\b"), ("OSCP", r"\boscp\b"), ("ITIL", r"\bitil\b"), ("ISTQB/CTFL", r"\bistqb\b|\bctfl\b"),
    ("Kubernetes (CKA/CKAD)", r"\bckad?\b"), ("Scrum (PSM/CSM)", r"scrum master|\bpsm\b|\bcsm\b"), ("CompTIA", r"comptia[\w \+\-]{0,15}"),
    ("Cisco (CCNA/CCNP)", r"\bccn[ap]\b"),
]
_CERT_GENERICA = ("Certificações (citadas de forma genérica)", r"certificac(?:ao|oes)|certificado em|certification")
_OUTROS = [
    ("Inglês (citado)", r"ingles|english"), ("Espanhol (citado)", r"espanhol|spanish"), ("Trabalho remoto (citado)", r"\bremot[oa]\b|home office|trabalho remoto"),
    ("Modelo híbrido (citado)", r"hibrido|hybrid"), ("Presencial (citado)", r"presencial|on-?site"), ("Contratação CLT (citada)", r"\bclt\b"),
    ("Contratação PJ (citada)", r"\bpj\b"), ("Viagens (citadas)", r"disponibilidade para viaj\w+|viagens"),
]


def _achar(descricao, pares):
    out = []
    for rotulo, rx in pares:
        t = trecho_regex(descricao, re.compile(rx))
        if t is not None:
            out.append({"rotulo": rotulo, "evidencia": t})
    return out


def extras(descricao: str) -> dict:
    cert = _achar(descricao, _CERT) or _achar(descricao, [_CERT_GENERICA])
    return {"formacao": _achar(descricao, _FORMACAO), "certificacoes": cert, "outros": _achar(descricao, _OUTROS)}


def responsabilidades_com_trecho(descricao: str) -> list[dict]:
    out = []
    for chave, (rotulo, rx) in _RESP.items():
        t = trecho_regex(descricao, rx)
        if t is not None:
            out.append({"chave": chave, "rotulo": rotulo, "evidencia": t})
    return out


# ---------------------------------------------------------------- análise individual
def analisar_vaga(vaga: dict, item: dict | None, chaves_perfil: set[str], com_perfil: bool) -> dict:
    """vaga: identidade e descrição original; item: resultado de `extract.extrair_por_vaga` (ou None se não houve extração)."""
    desc = vaga.get("descricao") or ""
    ext = item["extracao"] if item else None
    limitacoes: list[str] = []
    fraca = False  # limitações que enfraquecem a conclusão "não identificada = não exigida"
    if not desc.strip():
        status = "sem_descricao"
        limitacoes.append("A vaga não tem descrição: só os dados de identificação estão disponíveis.")
        fraca = True
    elif ext is None:
        status = "sem_analise"
        limitacoes.append("Não foi possível extrair os requisitos desta descrição.")
        fraca = True
    else:
        status = "analisada"
    if desc.strip():
        if len(desc) < compat.DESCRICAO_CURTA:
            limitacoes.append(f"Descrição curta ({len(desc)} caracteres): a análise pode estar incompleta.")
            fraca = True
        if vaga.get("descricao_resumo"):
            limitacoes.append(f"O provedor ({vaga.get('provedor') or 'desconhecido'}) costuma devolver só um trecho da descrição: requisitos fora dele não aparecem.")
            fraca = True
        if vaga.get("descricao_truncada"):
            limitacoes.append("A descrição foi truncada em 6000 caracteres.")
            fraca = True
    if item and item.get("motivo"):
        limitacoes.append(item["motivo"])
        fraca = fraca or bool(item.get("incompleta"))

    obrig, dif, nc = categorizar_requisitos(ext, desc, item["metodo"]) if ext else ({}, {}, {})
    if ext and not (obrig or dif or nc):
        limitacoes.append("Nenhuma tecnologia identificada na descrição.")
        fraca = True
    if nc:
        limitacoes.append("Sem marcadores explícitos de obrigatório/desejável: a classificação dessas tecnologias é desconhecida.")

    def itens(d):
        return [{"nome": n, "chave": k, "evidencia": trecho_habilidade(desc, n) if desc else None} for k, n in d.items()]

    cls = classificar(vaga.get("titulo") or "", desc)
    exp = anos_minimos(desc) if desc else {"min": None, "valores": []}
    ex = extras(desc) if desc else {"formacao": [], "certificacoes": [], "outros": []}

    if not com_perfil:
        comp = {"disponivel": False, "motivo": "Nenhuma habilidade cadastrada no perfil."}
    elif ext is None:
        comp = {"disponivel": False, "motivo": "Sem análise de requisitos para esta vaga."}
    else:
        try:
            r = compat.avaliar(ext, chaves_perfil, descricao_curta=len(desc) < compat.DESCRICAO_CURTA)
            comp = {"disponivel": r["estado"] == "avaliada", **r}
            if nc and item and item["metodo"] == "dicionario":
                comp["avisos"] = comp["avisos"] + ["A fórmula existente conta como obrigatórias as tecnologias sem marcação explícita."]
        except Exception:  # falha isolada: nunca vira a pontuação da outra vaga
            comp = {"disponivel": False, "motivo": "Falha ao calcular a compatibilidade desta vaga."}

    return {
        "identidade": {k: vaga.get(k) for k in ("id", "origem", "provedor", "titulo", "empresa", "local", "link", "publicada_em", "obtida_em")}
                      | {"descricao_chars": len(desc)},
        "descricao": desc, "status": status, "limitacoes": limitacoes, "confianca_ausencia": "baixa" if fraca else "alta",
        "metodo": item["metodo"] if item else None,
        "senioridade": cls, "experiencia": exp,
        "requisitos": {"obrigatorios": itens(obrig), "diferenciais": itens(dif), "nao_classificados": itens(nc)},
        "soft_skills": sorted(skills_unicas(ext.get("soft_skills") if ext else []).values(), key=str.casefold),
        "responsabilidades": responsabilidades_com_trecho(desc) if desc else [],
        "formacao": ex["formacao"], "certificacoes": ex["certificacoes"], "outros": ex["outros"],
        "compatibilidade": comp,
        "contagens": {"obrigatorios": len(obrig), "diferenciais": len(dif), "nao_classificados": len(nc), "total": len(obrig) + len(dif) + len(nc)},
    }


def skills_unicas(itens) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in itens or []:
        if isinstance(i, str) and i.strip():
            out.setdefault(skills.chave(i), skills.canonizar(i))
    out.pop("", None)
    return out


# ---------------------------------------------------------------- comparação
def _mapa(a: dict) -> dict[str, tuple[str, str]]:
    """chave -> (nome, categoria) com categoria obrigatoria|diferencial|nao_classificada."""
    r = a["requisitos"]
    out: dict[str, tuple[str, str]] = {}
    for cat, lista in (("obrigatoria", r["obrigatorios"]), ("diferencial", r["diferenciais"]), ("nao_classificada", r["nao_classificados"])):
        for i in lista:
            out.setdefault(i["chave"], (i["nome"], cat))
    return out


ROT_CAT = {"obrigatoria": "obrigatória", "diferencial": "desejável", "nao_classificada": "classificação desconhecida"}


def _pode_afirmar_ausencia(outra: dict) -> bool:
    return outra["confianca_ausencia"] == "alta"


def comparar(a: dict, b: dict) -> dict:
    """a, b: saídas de `analisar_vaga`. Sem extração em uma delas, a comparação de requisitos não é feita."""
    for x in (a, b):
        if x["status"] != "analisada":
            return {"disponivel": False, "motivo": "A comparação de requisitos exige a análise das duas vagas; veja as limitações de cada uma."}
    ma, mb = _mapa(a), _mapa(b)
    firme_a, firme_b = _pode_afirmar_ausencia(a), _pode_afirmar_ausencia(b)  # firme_x: a ausência EM x é confiável

    comuns = [{"nome": ma[k][0], "chave": k, "a": ma[k][1], "b": mb[k][1], "mesma_classificacao": ma[k][1] == mb[k][1]}
              for k in ma if k in mb]
    so_a = [{"nome": n, "chave": k, "categoria_a": c, "ausencia_confiavel": firme_b} for k, (n, c) in ma.items() if k not in mb]
    so_b = [{"nome": n, "chave": k, "categoria_b": c, "ausencia_confiavel": firme_a} for k, (n, c) in mb.items() if k not in ma]

    # relacionadas, mas distintas (observação; nunca conta como comum)
    relacionadas, vistos = [], set()
    for ia in so_a:
        for kb, nb, motivo in skills.relacionadas(ia["nome"]):
            if kb in mb and kb not in ma and (ia["chave"], kb) not in vistos:
                vistos.add((ia["chave"], kb))
                relacionadas.append({"a": ia["nome"], "b": nb, "motivo": motivo})

    def dif_obrig(m1, m2, firme_2):
        out = []
        for k, (n, c) in m1.items():
            if c != "obrigatoria":
                continue
            if k in m2 and m2[k][1] == "obrigatoria":
                continue
            em = "nao_identificada" if k not in m2 else m2[k][1]
            out.append({"nome": n, "chave": k, "na_outra": em,
                        "texto": {"diferencial": "aparece como desejável na outra vaga", "nao_classificada": "aparece na outra vaga sem classificação (obrigatória ou não, é desconhecido)",
                                  "nao_identificada": "não identificada na descrição da outra vaga"}[em],
                        "ausencia_confiavel": firme_2 if em == "nao_identificada" else True})
        return out

    def dif_dif(m1, m2, firme_2):
        return [{"nome": n, "chave": k, "ausencia_confiavel": firme_2} for k, (n, c) in m1.items() if c == "diferencial" and k not in m2]

    ra = {x["chave"]: x for x in a["responsabilidades"]}
    rb = {x["chave"]: x for x in b["responsabilidades"]}
    resp = {
        "comuns": [{"rotulo": ra[k]["rotulo"], "evidencia_a": ra[k]["evidencia"], "evidencia_b": rb[k]["evidencia"]} for k in ra if k in rb],
        "so_a": [{"rotulo": ra[k]["rotulo"], "evidencia": ra[k]["evidencia"]} for k in ra if k not in rb],
        "so_b": [{"rotulo": rb[k]["rotulo"], "evidencia": rb[k]["evidencia"]} for k in rb if k not in ra],
    }

    def rotulos(x):
        return {i["rotulo"]: i for i in x["formacao"] + x["certificacoes"]}
    fa, fb = rotulos(a), rotulos(b)
    formacao = {"comuns": sorted(set(fa) & set(fb)), "so_a": sorted(set(fa) - set(fb)), "so_b": sorted(set(fb) - set(fa))}

    sa, sb = a["senioridade"], b["senioridade"]
    if sa["nivel"] == "nao_classificado" or sb["nivel"] == "nao_classificado":
        sen = {"comparavel": False, "a": sa["rotulo"], "b": sb["rotulo"],
               "texto": "Nível não comparável: " + "; ".join(f"vaga {l}: {x['motivo']}" for l, x in (("A", sa), ("B", sb)) if x["nivel"] == "nao_classificado")}
    elif sa["nivel"] == sb["nivel"]:
        sen = {"comparavel": True, "a": sa["rotulo"], "b": sb["rotulo"], "texto": f"As duas vagas indicam o mesmo nível: {sa['rotulo']}."}
    else:
        sen = {"comparavel": True, "a": sa["rotulo"], "b": sb["rotulo"], "texto": f"Níveis diferentes: vaga A {sa['rotulo']} ({_origem(sa)}) × vaga B {sb['rotulo']} ({_origem(sb)})."}

    ea, eb = a["experiencia"], b["experiencia"]
    if ea["min"] is None or eb["min"] is None:
        faltam = " e ".join(l for l, e in (("A", ea), ("B", eb)) if e["min"] is None)
        exp = {"comparavel": False, "a": ea["min"], "b": eb["min"], "texto": f"Experiência mínima não identificada na(s) vaga(s) {faltam}: não há como comparar."}
    else:
        dif = eb["min"] - ea["min"]
        t = (f"Experiência mínima igual nas duas vagas ({ea['min']} ano(s))." if dif == 0 else
             f"Experiência mínima: vaga A {ea['min']} ano(s) × vaga B {eb['min']} ano(s) (diferença de {abs(dif)} ano(s))." )
        amb = [l for l, e in (("A", ea), ("B", eb)) if len(e["valores"]) > 1]
        if amb:
            t += f" A(s) vaga(s) {' e '.join(amb)} cita(m) valores diferentes; vale o menor."
        exp = {"comparavel": True, "a": ea["min"], "b": eb["min"], "diferenca_anos": dif, "texto": t}

    return {
        "disponivel": True,
        "confianca_ausencia": {"a": a["confianca_ausencia"], "b": b["confianca_ausencia"]},
        "habilidades": {"comuns": comuns, "so_a": so_a, "so_b": so_b, "relacionadas": relacionadas,
                        "contagens": {"comuns": len(comuns), "so_a": len(so_a), "so_b": len(so_b), "total_distintas": len(comuns) + len(so_a) + len(so_b),
                                      "total_a": len(ma), "total_b": len(mb), "relacionadas": len(relacionadas)}},
        "obrigatorios": {"a_sem_equivalente_obrigatorio_em_b": dif_obrig(ma, mb, firme_b), "b_sem_equivalente_obrigatorio_em_a": dif_obrig(mb, ma, firme_a)},
        "diferenciais": {"so_a": dif_dif(ma, mb, firme_b), "so_b": dif_dif(mb, ma, firme_a)},
        "responsabilidades": resp, "formacao": formacao, "senioridade": sen, "experiencia": exp,
    }


def _origem(c: dict) -> str:
    return "explícita" if c["origem"] == "explicita" else "inferida"


# ---------------------------------------------------------------- síntese (a partir do resultado estruturado)
def _lista(nomes, n=5):
    nomes = list(nomes)
    if len(nomes) <= n:
        return ", ".join(nomes)
    return ", ".join(nomes[:n]) + f" e mais {len(nomes) - n}"


def sintese(a: dict, b: dict, comp: dict) -> dict:
    indisp = []
    for l, x in (("A", a), ("B", b)):
        for lim in x["limitacoes"]:
            indisp.append(f"Vaga {l}: {lim}")
    base = {"nota": "Esta síntese descreve diferenças entre dois anúncios; não indica qual vaga é melhor, pois isso depende dos seus objetivos e de informações que os anúncios não trazem.",
            "indisponivel": indisp}
    if not comp.get("disponivel"):
        return {**base, "semelhancas": [], "diferencas": [], "especificas": {"a": [], "b": []}, "incompleta": True}
    h = comp["habilidades"]
    sem, dif = [], []
    if h["comuns"]:
        sem.append(f"{len(h['comuns'])} habilidade(s) em comum: {_lista(i['nome'] for i in h['comuns'])}.")
    else:
        sem.append("Nenhuma habilidade técnica em comum foi identificada.")
    if comp["senioridade"]["comparavel"] and comp["senioridade"]["a"] == comp["senioridade"]["b"]:
        sem.append(comp["senioridade"]["texto"])
    if comp["responsabilidades"]["comuns"]:
        sem.append("Responsabilidades em comum: " + _lista(i["rotulo"] for i in comp["responsabilidades"]["comuns"]) + ".")
    if comp["senioridade"]["comparavel"] and comp["senioridade"]["a"] != comp["senioridade"]["b"]:
        dif.append(comp["senioridade"]["texto"])
    if comp["experiencia"]["comparavel"] and comp["experiencia"]["diferenca_anos"] != 0:
        dif.append(comp["experiencia"]["texto"])
    oa = comp["obrigatorios"]["a_sem_equivalente_obrigatorio_em_b"]
    ob = comp["obrigatorios"]["b_sem_equivalente_obrigatorio_em_a"]
    if oa:
        dif.append(f"Obrigatórias na vaga A sem equivalente obrigatório na B: {_lista(i['nome'] for i in oa)}.")
    if ob:
        dif.append(f"Obrigatórias na vaga B sem equivalente obrigatório na A: {_lista(i['nome'] for i in ob)}.")
    if h["relacionadas"]:
        dif.append("Relacionadas, mas distintas (não contam como comuns): " + "; ".join(f"{r['a']} (A) × {r['b']} (B)" for r in h["relacionadas"][:4]) + ".")
    if not dif:
        dif.append("Nenhuma diferença relevante de requisitos obrigatórios, nível ou experiência foi identificada com os dados disponíveis.")
    espec = {"a": [i["nome"] for i in h["so_a"]], "b": [i["nome"] for i in h["so_b"]]}
    if any(not i["ausencia_confiavel"] for i in h["so_a"] + h["so_b"]) or comp["confianca_ausencia"]["a"] == "baixa" or comp["confianca_ausencia"]["b"] == "baixa":
        indisp.append("Uma habilidade 'identificada só em uma vaga' pode apenas ter sido omitida na outra descrição: com análise limitada, a ausência não prova que não seja exigida.")
    return {**base, "indisponivel": indisp, "semelhancas": sem, "diferencas": dif, "especificas": espec, "incompleta": bool(indisp)}
