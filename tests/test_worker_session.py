"""
A sessão do worker precisa desfazer a transação quando a task falha no meio.
Antes era um gerador consumido com next()/close(), e nesse formato a exceção
da task nunca chegava ao except do gerador — o rollback explícito nunca rodava.
"""

import pytest

from app.worker import db as worker_db


class _SessaoFake:
    def __init__(self) -> None:
        self.rollbacks = 0
        self.closes = 0

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


@pytest.fixture
def sessao_fake(monkeypatch):
    sessao = _SessaoFake()
    monkeypatch.setattr(worker_db, "_get_engine", lambda: None)
    monkeypatch.setattr(worker_db, "_SessionLocal", lambda: sessao)
    return sessao


def test_falha_na_task_faz_rollback_e_fecha(sessao_fake):
    with pytest.raises(RuntimeError):
        with worker_db.worker_session():
            raise RuntimeError("task explodiu no meio")

    assert sessao_fake.rollbacks == 1
    assert sessao_fake.closes == 1


def test_sucesso_nao_faz_rollback(sessao_fake):
    with worker_db.worker_session() as db:
        assert db is sessao_fake

    assert sessao_fake.rollbacks == 0
    assert sessao_fake.closes == 1
