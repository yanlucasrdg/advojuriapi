"""
Engine síncrona separada da engine async do FastAPI.

Por quê: Celery (modo prefork, o padrão) faz fork() do processo depois
de importar o módulo. Se a engine async (asyncpg) fosse criada no
import-time e o pool de conexões já tivesse sido aberto antes do fork,
os processos filhos herdariam file descriptors de socket compartilhados
e corromperiam as conexões entre workers — um bug clássico, silencioso
e intermitente sob carga, exatamente o tipo de coisa que passa despercebido
em dev (1 worker, sem fork visível) e explode em produção.

Solução mais simples e robusta: usar uma engine síncrona (psycopg3) só
para o worker, criada de forma preguiçosa (lazy) na primeira vez que uma
task precisa dela, dentro do processo já "forkado". Nada de estado
async compartilhado entre processos.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.DATABASE_URL_SYNC,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


@contextmanager
def worker_session() -> Generator[Session, None, None]:
    """Sessão síncrona por task: abre, entrega, faz rollback em erro e fecha sempre."""
    _get_engine()
    session = _SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
