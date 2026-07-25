"""
Testes de `app.services.cache`.

Foca na regra pura `cache_esta_fresco` (a busca em banco depende de infra e é
coberta por testes de integração). O TTL usado é
`CACHE_TTL_MOVIMENTOS_HORAS` — movimentos mudam mais rápido que cadastro,
então o cache "fresco" tem janela curta.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.config import get_settings
from app.services.cache import cache_esta_fresco

settings = get_settings()
TTL = settings.CACHE_TTL_MOVIMENTOS_HORAS


def _processo(atualizado_em):
    return SimpleNamespace(atualizado_em=atualizado_em)


def test_cache_recem_atualizado_e_fresco():
    proc = _processo(datetime.now(timezone.utc))
    assert cache_esta_fresco(proc) is True


def test_cache_dentro_do_ttl_e_fresco():
    proc = _processo(datetime.now(timezone.utc) - timedelta(hours=TTL - 1))
    assert cache_esta_fresco(proc) is True


def test_cache_expirado_nao_e_fresco():
    proc = _processo(datetime.now(timezone.utc) - timedelta(hours=TTL + 1))
    assert cache_esta_fresco(proc) is False


def test_cache_exatamente_no_limite_do_ttl_nao_e_fresco():
    # limite = atualizado_em + TTL; a comparação é estrita (agora < limite),
    # então exatamente no limite já conta como expirado.
    proc = _processo(datetime.now(timezone.utc) - timedelta(hours=TTL))
    assert cache_esta_fresco(proc) is False
