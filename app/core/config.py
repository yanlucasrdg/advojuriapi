from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "AdvoJuri API"
    ENV: str = "development"  # development | staging | production
    DEBUG: bool = True

    # Banco (Supabase Postgres)
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host:5432/db

    # Redis (cache quente + fila do worker)
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Frequência da varredura de monitoramentos ativos (minutos)
    INTERVALO_VARREDURA_MONITORAMENTOS_MINUTOS: int = 15

    # DataJud CNJ
    # A chave pública é rotacionada periodicamente pelo CNJ.
    # Ver: https://datajud-wiki.cnj.jus.br/api-publica/acesso/
    DATAJUD_API_KEY: str
    DATAJUD_BASE_URL: str = "https://api-publica.datajud.cnj.jus.br"

    # Cache de consultas (em horas) — movimentos mudam mais rápido que cadastro
    CACHE_TTL_MOVIMENTOS_HORAS: int = 6
    CACHE_TTL_CADASTRO_HORAS: int = 72

    # Billing — custo em centavos por tipo de consulta
    PRECO_CONSULTA_PROCESSO_CENTAVOS: int = 15
    PRECO_BUSCA_PARTE_CENTAVOS: int = 25

    # Busca por nome/CNPJ não sabe a priori em qual tribunal o processo está,
    # então faz fan-out numa lista curada. Cada tribunal a mais = mais custo
    # de rate-limit no DataJud e mais latência. Isso é uma escolha de produto,
    # não só técnica — ajustar conforme o perfil de cliente (ex: escritório
    # trabalhista pesa mais TRTs, imobiliário pesa mais TJs estaduais).
    TRIBUNAIS_BUSCA_PADRAO: list[str] = ["TJSP", "TJRJ", "TJMG", "TJCE", "TRF3", "TST"]
    LIMITE_RESULTADOS_BUSCA_NOME: int = 10

    # Segurança
    API_KEY_PREFIX_LIVE: str = "ajr_live_"
    API_KEY_PREFIX_TEST: str = "ajr_test_"

    # CORS — domínios autorizados a chamar a API do navegador (o painel Lovable).
    # Setar via env var em produção, ex: ALLOWED_ORIGINS=["https://painel.advojuri.com.br"]
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Webhooks
    WEBHOOK_TIMEOUT_SEGUNDOS: int = 10
    WEBHOOK_MAX_TENTATIVAS: int = 5

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """
        Deriva a connection string síncrona (psycopg) a partir da async
        (asyncpg), pra não duplicar credencial em duas env vars.
        O worker Celery usa esta; o FastAPI usa DATABASE_URL (async).
        """
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
