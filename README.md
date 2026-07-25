# AdvoJuri API — Core

Núcleo do backend: autenticação por API key, billing pré-pago (ledger append-only)
e adapter de integração com a API Pública do DataJud (CNJ).

## O que já está aqui

- **Auth**: API keys com hash SHA-256, formato `ajr_live_...` / `ajr_test_...`.
- **Billing**: ledger append-only, saldo sempre derivado da última transação
  (nunca uma coluna mutável), débito checado *antes* de consultar a fonte externa.
- **DataJud adapter**: integração real com `api-publica.datajud.cnj.jus.br`
  (Elasticsearch por baixo, um índice por tribunal).
- **Cache**: consultas repetidas dentro do TTL não rebatem no DataJud.
- **Testes**: lógica de billing coberta (`tests/test_billing.py`).

## Busca por CNPJ / nome / CPF (`GET /v1/busca`)

- **CNPJ**: resolvido para razão social via BrasilAPI (espelha dados abertos
  da Receita Federal), depois pesquisado por nome (fuzzy) num conjunto de
  tribunais. Resposta vem com `confianca_match: "provavel"` e um `aviso`
  explicando a limitação — não é match exato garantido por CNPJ, porque o
  DataJud não indexa CNPJ da parte diretamente.
- **Nome**: mesmo fluxo de fuzzy match, direto.
- **CPF**: **não suportado**, retorna `400` com explicação. Não existe base
  pública/gratuita que mapeie CPF a nome no Brasil (diferente do CNPJ, que é
  dado aberto na Receita). Resolver isso exigiria contratar um bureau de
  dados cadastrais com base legal própria de tratamento — decisão de produto
  e jurídica, não pendência técnica.
- A busca faz **fan-out numa lista curada de tribunais** (`TRIBUNAIS_BUSCA_PADRAO`
  em `app/core/config.py`), porque o DataJud não faz busca cross-tribunal.
  Cada tribunal a mais na lista = mais latência e mais custo de rate-limit.

## Worker de monitoramento (Celery)

Fan-out em 3 níveis — cada um falha/retenta de forma independente:

```
varrer_monitoramentos_ativos (periódica, a cada N min via beat)
  └─ verificar_processo_monitorado (1 por monitoramento ativo)
       └─ enviar_webhook (1 por movimento novo encontrado)
```

Pontos importantes de design:

- **Engine de banco síncrona separada** (`app/worker/db.py`, driver `psycopg`)
  em vez de reusar a engine async do FastAPI. Celery faz fork() dos workers
  (modo prefork, o padrão); uma engine async criada antes do fork quebra
  conexões entre processos filhos de forma silenciosa e intermitente — bug
  clássico que não aparece em dev com 1 worker. A ponte com o adapter async
  do DataJud é feita task a task via `asyncio.run()`, que cria e destrói um
  loop novo por chamada (seguro sob fork, diferente de uma engine persistente).
- **Backfill silencioso na primeira verificação.** Quando um monitoramento é
  criado, o processo já pode ter movimentos históricos. Na primeira varredura
  esses movimentos são gravados no banco mas **não** disparam webhook — só
  gera alerta o que aparecer depois de já estar sendo monitorado.
- **Assinatura HMAC-SHA256** (`X-AdvoJuri-Signature`) em cada webhook, no
  mesmo padrão do Stripe/GitHub. O `webhook_secret` é mostrado uma única vez
  na criação do monitoramento (`POST /v1/monitoramentos`).
- **Retry com backoff exponencial** em `enviar_webhook` (2s, 4s, 8s...) até
  `WEBHOOK_MAX_TENTATIVAS`, depois marca `status_entrega="falhou"` — sem
  ficar tentando pra sempre.

### Rodando localmente

```bash
# precisa de Redis rodando (broker + result backend)
redis-server &

# worker (processa as tasks)
celery -A app.core.celery_app worker --loglevel=info

# beat (dispara a varredura periódica)
celery -A app.core.celery_app beat --loglevel=info
```

### Fluxo de uso

```bash
# 1. consulta o processo (popula o cache local, pré-requisito do monitoramento)
curl "http://localhost:8000/v1/processos/5005023-96.2023.4.03.6309?tribunal=TRF3" \
  -H "Authorization: Bearer ajr_live_sua_chave"

# 2. cria o monitoramento (guarde o webhook_secret retornado, só aparece aqui)
curl -X POST "http://localhost:8000/v1/monitoramentos" \
  -H "Authorization: Bearer ajr_live_sua_chave" \
  -H "Content-Type: application/json" \
  -d '{"numero_cnj":"5005023-96.2023.4.03.6309","tribunal":"TRF3","webhook_url":"https://seusite.com.br/webhooks/advojuri"}'
```

## Deploy no Railway

Arquivos já prontos no repo: `Dockerfile`, `.dockerignore`, `railway.json`
(builder explícito, evita o buildpack do Railway adivinhar errado).

**1. Suba este código num repositório GitHub** (Railway deploya a partir de
GitHub ou via CLI — não aceita zip direto pelo dashboard).

**2. No Railway:** New Project → Deploy from GitHub repo → selecione o repo.
Isso cria o serviço **web**. Railway detecta o `Dockerfile` automaticamente
por causa do `railway.json`.

**3. Adicione um addon Redis:** dentro do mesmo projeto, "+ New" → Database →
Redis. Railway provisiona e expõe uma variável de conexão (algo como
`REDIS_URL` no serviço do Redis — o nome exato aparece no próprio dashboard,
copie de lá).

**4. Variáveis de ambiente do serviço web** (Settings → Variables):
```
DATABASE_URL=postgresql+asyncpg://postgres:<SENHA>@db.uzrgwjfndzyizmiqvhkn.supabase.co:5432/postgres
DATAJUD_API_KEY=<sua chave do datajud.cnj.jus.br>
CELERY_BROKER_URL=<connection string do Redis addon>/1
CELERY_RESULT_BACKEND=<connection string do Redis addon>/2
ALLOWED_ORIGINS=["https://<domínio do painel quando existir>"]
ENV=production
DEBUG=false
```

**5. Rode as migrations uma vez** — não precisa, já apliquei via Supabase MCP
diretamente neste projeto (`advojuri-api`, `uzrgwjfndzyizmiqvhkn`). Se recriar
o banco do zero no futuro: `railway run alembic upgrade head` (CLI) ou uma
task one-off no dashboard.

**6. Crie dois serviços adicionais a partir do mesmo repo** (não precisa
reconfigurar variáveis — Railway deixa compartilhar entre serviços do mesmo
projeto via "Shared Variables"):
   - **worker**: Settings → Deploy → Custom Start Command:
     `celery -A app.core.celery_app worker --loglevel=info`
   - **beat**: Settings → Deploy → Custom Start Command:
     `celery -A app.core.celery_app beat --loglevel=info`

**7. Domínio público:** o serviço **web** ganha um domínio `*.up.railway.app`
automaticamente (Settings → Networking → Generate Domain). É essa URL que
vira o `VITE_API_BASE_URL` do painel.

### O que eu não validei (sem Docker no sandbox pra testar)

O `Dockerfile` segue o padrão oficial do guia Railway pra FastAPI (Python
3.12-slim, pip install, uvicorn respeitando `$PORT`), mas eu não consegui
rodar `docker build` de verdade aqui — não tem Docker disponível neste
ambiente. Rode `docker build -t advojuri-api .` localmente antes do primeiro
deploy, só pra confirmar que builda limpo, em vez de descobrir isso já no
Railway.

## O que NÃO está aqui ainda (próximas fases)



1. **Gateway de pagamento real.** `POST /v1/saldo/recarga` hoje credita direto,
   sem validar pagamento. Isso é inseguro em produção — precisa virar um webhook
   assinado do gateway (Stripe/Pagar.me/Mercado Pago), nunca um endpoint que o
   próprio cliente chama para se autocreditar.
2. **Lock de linha real no billing.** O débito lê o saldo e escreve numa
   transação, mas sem um mutex explícito (`SELECT ... FOR UPDATE`) duas
   requisições simultâneas do mesmo tenant podem, em teoria, ler o mesmo saldo
   "velho". Ver comentário em `app/services/billing.py::debitar`. Antes de ter
   tráfego real concorrente, isso precisa de uma tabela auxiliar de lock ou
   `SELECT FOR UPDATE` numa linha de saldo materializada.
3. **Mapa completo de tribunais.** `ALIAS_TRIBUNAL` tem ~13 tribunais de
   exemplo. A lista oficial completa (90+) está no Anexo II do tutorial do CNJ
   e precisa virar uma tabela de config, não ficar hardcoded no adapter.
4. **Rate limiting por tenant** (hoje só existe o rate limit natural do saldo).
5. **BrasilAPI em produção com volume alto.** É um serviço comunitário sem SLA
   formal; se o volume de resolução de CNPJ crescer muito, migrar para um dump
   local dos dados abertos da Receita Federal em vez de bater na BrasilAPI a
   cada request.
6. **Cobrança do monitoramento em si.** Hoje `POST /v1/monitoramentos` não
   debita saldo — só a consulta inicial que popula o cache é cobrada. Se o
   modelo de negócio for cobrar por monitoramento ativo (ex: mensalidade por
   processo monitorado, ou débito a cada varredura), isso precisa entrar no
   `varrer_monitoramentos_ativos` ou como um cron de billing separado.
7. **`verificar_processo_monitorado` não tem circuit breaker por tribunal.**
   Se um tribunal específico ficar fora do ar, cada monitoramento daquele
   tribunal vai tentar e falhar independentemente a cada varredura, gerando
   ruído de retry. Um circuit breaker por tribunal (pular por N minutos após
   K falhas seguidas) é o próximo refinamento natural aqui.
8. **`enviar_webhook` não valida SSRF.** `webhook_url` só é checado quanto a
   `https://`, mas nada impede um cliente malicioso de apontar para um
   endereço interno (ex: `169.254.169.254`, metadados de cloud). Antes de
   expor isso a clientes não confiáveis, adicionar validação de IP privado/
   reservado no momento da criação do monitoramento.

## Setup local

```bash
cp .env.example .env
# preencha DATABASE_URL (Supabase) e DATAJUD_API_KEY
# (cadastro gratuito em https://datajud.cnj.jus.br)

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head          # cria as 9 tabelas no Supabase
uvicorn app.main:app --reload
```

Docs interativas em `http://localhost:8000/docs`.

## Testes

```bash
pytest -v
```

## Criando o primeiro tenant + API key (manual, até existir endpoint de signup)

```python
# script descartável, rodar uma vez
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant
from app.models.api_key import ApiKey
from app.core.security import gerar_api_key

async def main():
    async with AsyncSessionLocal() as db:
        tenant = Tenant(nome="Escritório Exemplo", email="contato@exemplo.com.br")
        db.add(tenant)
        await db.flush()

        chave_texto_puro, chave_hash = gerar_api_key("live")
        db.add(ApiKey(
            tenant_id=tenant.id,
            chave_hash=chave_hash,
            chave_prefixo_visivel=chave_texto_puro[:16] + "...",
            ambiente="live",
        ))
        await db.commit()
        print("Guarde esta chave, ela não será mostrada de novo:")
        print(chave_texto_puro)

asyncio.run(main())
```

## Exemplo de chamada

```bash
curl "http://localhost:8000/v1/processos/5005023-96.2023.4.03.6309?tribunal=TRF3" \
  -H "Authorization: Bearer ajr_live_sua_chave"

curl "http://localhost:8000/v1/busca?tipo=cnpj&termo=00623904000173" \
  -H "Authorization: Bearer ajr_live_sua_chave"
```
