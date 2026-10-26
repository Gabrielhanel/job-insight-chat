"""Provedor de vagas SIMULADO para testes (httpx.MockTransport). Nada aqui representa dados reais de mercado."""
import httpx

FILLER = (
    " Buscamos pessoa desenvolvedora para atuar em um squad de produto digital, com autonomia, colaboração e foco"
    " em entrega contínua de qualidade. Oferecemos ambiente colaborativo, plano de carreira e benefícios flexíveis."
)


def vaga(job_id, titulo="Pessoa Desenvolvedora", empresa="Empresa A", obrigatorios=(), diferenciais=(),
         cidade="São Paulo", link="https://exemplo.test/vaga", descricao=None, publicada=None):
    """Vaga no formato JSearch. Descrição com 'Requisitos' e (opcional) seção 'Diferenciais'."""
    if descricao is None:
        descricao = f"Requisitos: {', '.join(obrigatorios)}.{FILLER}"
        if diferenciais:
            descricao += f"\nDiferenciais:\n{', '.join(diferenciais)}\n"
    d = {"job_title": titulo, "employer_name": empresa, "job_description": descricao,
         "job_apply_link": link, "job_city": cidade, "job_state": "SP", "job_country": "BR"}
    if job_id is not None:
        d["job_id"] = job_id
    if publicada:
        d["job_posted_at_datetime_utc"] = publicada
    return d


class Provedor:
    def __init__(self):
        self.chamadas: list[dict] = []
        self.resposta = lambda query, page: []  # (query, page) -> lista de vagas
        self.status = 200
        self.falha = None  # (params) -> status HTTP de erro para consultas específicas, ou None

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.chamadas.append(params)
        if self.falha and (st := self.falha(params)):
            return httpx.Response(st, json={"erro": "simulado"})
        if self.status != 200:
            return httpx.Response(self.status, json={"erro": "simulado"})
        return httpx.Response(200, json={"data": self.resposta(params["query"], int(params["page"]))})
