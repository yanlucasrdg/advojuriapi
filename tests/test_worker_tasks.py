"""
Testes da ponte sync->async do worker (`app.worker.tasks._buscar_no_datajud_sync`).

Essa função existe porque o Celery roda sync (prefork/fork) mas o adapter do
DataJud é async — ela cria/destrói um event loop por chamada via
`asyncio.run`. Aqui validamos que ela delega para o adapter e sempre fecha o
client, sem tocar em Celery/DB nem na rede real.
"""

import app.worker.tasks as tasks


class _FakeAdapter:
    instancias: list["_FakeAdapter"] = []

    def __init__(self):
        self.fechado = False
        self.chamada = None
        _FakeAdapter.instancias.append(self)

    async def buscar_por_numero_cnj(self, numero_cnj, tribunal):
        self.chamada = (numero_cnj, tribunal)
        return {"numeroProcesso": numero_cnj, "tribunal": tribunal}

    async def close(self):
        self.fechado = True


class _FakeAdapterQueFalha(_FakeAdapter):
    async def buscar_por_numero_cnj(self, numero_cnj, tribunal):
        raise RuntimeError("DataJud fora do ar")


def test_buscar_no_datajud_sync_delega_e_fecha_client(monkeypatch):
    _FakeAdapter.instancias.clear()
    monkeypatch.setattr(tasks, "DataJudAdapter", _FakeAdapter)

    resultado = tasks._buscar_no_datajud_sync("5005023962023", "TRF3")

    assert resultado == {"numeroProcesso": "5005023962023", "tribunal": "TRF3"}
    adapter = _FakeAdapter.instancias[-1]
    assert adapter.chamada == ("5005023962023", "TRF3")
    assert adapter.fechado is True


def test_buscar_no_datajud_sync_fecha_client_mesmo_em_erro(monkeypatch):
    _FakeAdapter.instancias.clear()
    monkeypatch.setattr(tasks, "DataJudAdapter", _FakeAdapterQueFalha)

    try:
        tasks._buscar_no_datajud_sync("123", "TJSP")
    except RuntimeError:
        pass
    else:
        raise AssertionError("esperava RuntimeError propagado do adapter")

    assert _FakeAdapter.instancias[-1].fechado is True
