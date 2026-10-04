# JobInsight

Chatbot web que, a partir de um cargo ou área, busca vagas relacionadas e mostra os requisitos que mais aparecem nelas, com o percentual de vagas em que cada um é citado.

Exemplo: ao buscar `desenvolvedor Kotlin jr`, você vê quais tecnologias, diferenciais e soft skills aparecem na maioria das vagas encontradas.

## Funcionalidades

- Busca de vagas por API (JSearch ou Adzuna)
- Ranking de tecnologias, diferenciais e soft skills, com nível e experiência mínima mediana
- Interface de chat no navegador, com botão de cancelar e cópia do resumo
- Cache local e contador de cota, para não gastar requisições à toa
- Extração gratuita por dicionário de palavras; uso opcional da Claude para uma extração mais precisa

## Requisitos

- Python 3.10 ou superior
- Uma chave de API de vagas: [JSearch no OpenWeb Ninja](https://app.openwebninja.com) (tem plano gratuito) ou [Adzuna](https://developer.adzuna.com) (cadastro gratuito)

## Instalação

```bash
git clone https://github.com/Gabrielhanel/job-insight-chat.git
cd cd job-insight-chat
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

No Ubuntu/Debian, se o `venv` reclamar de `ensurepip`, instale antes o pacote: `sudo apt install python3-venv`.

## Configuração

Crie um arquivo `.env` na raiz do projeto (ao lado do `requirements.txt`). Configuração mínima com o JSearch:

```dotenv
PROVEDOR=jsearch
OPENWEBNINJA_API_KEY=sua_chave
```

Cada variável vai em uma linha, sem aspas e sem espaços em volta do `=`.

| Variável | Obrigatória | Descrição |
|---|---|---|
| `PROVEDOR` | Não | `jsearch` ou `adzuna`. Padrão: `adzuna` |
| `OPENWEBNINJA_API_KEY` | Com `jsearch` | Chave do JSearch no OpenWeb Ninja |
| `RAPIDAPI_KEY` | Alternativa | Chave do JSearch, se a assinatura for pela RapidAPI |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Com `adzuna` | Credenciais do Adzuna |
| `ANTHROPIC_API_KEY` | Não | Se definida, a extração usa a Claude em vez do dicionário |
| `EXTRACTION_MODEL` | Não | Modelo da Claude usado na extração. Padrão: `claude-haiku-4-5-20251001` |
| `QUOTA_MENSAL` | Não | Limite mensal do contador local. Padrão: `200` |
| `CACHE_TTL_H` | Não | Validade do cache das páginas, em horas. Padrão: `24` |
| `CACHE_DB` | Não | Caminho do arquivo SQLite do cache. Padrão: `cache.db` na raiz |

## Como rodar

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --reload
```

Abra **http://localhost:8000** e digite um cargo. Rode sempre a partir da pasta do projeto. O servidor só lê o `.env` ao iniciar: depois de editá-lo, pare com `Ctrl+C` e rode de novo.

## Uso da API

A documentação interativa fica em **http://localhost:8000/docs**.

| Rota | Descrição |
|---|---|
| `GET /` | Interface de chat |
| `POST /chat` | Analisa um cargo. Corpo: `{"mensagem": "qa automation", "pais": "br", "paginas": 2, "apenas_novas": false}`. Com `apenas_novas: true`, continua nas páginas seguintes e devolve só vagas ainda não exibidas para a consulta |
| `GET /analisar?cargo=...&pais=br&paginas=2` | Mesma análise, via query string |
| `GET /status` | Uso da cota local e método de extração ativo |

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"mensagem": "desenvolvedor Kotlin jr", "pais": "br", "paginas": 2}'
```

A resposta traz `resposta` (texto pronto) e `dados` (o mesmo resultado em JSON).

## Páginas e cota

- `paginas` aceita de 1 a 5. Sem o campo, o padrão é 3 no JSearch (~10 vagas por página) e 1 no Adzuna (até 50 vagas por página).
- Cada página gasta 1 requisição da cota do provedor. O plano gratuito do JSearch no OpenWeb Ninja mostrava 200 requisições por mês no painel; confira os limites atuais na sua conta.
- Páginas já buscadas ficam em cache por 24 horas e não gastam cota de novo.
- O contador local (`x/200` na interface) só conta as requisições feitas por este projeto. Compare com o painel do provedor.
