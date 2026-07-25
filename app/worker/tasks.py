"""
Tasks do worker de monitoramento.

Fan-out em 3 níveis, de propósito:
  varrer_monitoramentos_ativos (periódica)
    -> verificar_processo_monitorado (1 por monitoramento)
         -> enviar_webhook (1 por movimento novo encontrado)

Isso significa que uma falha isolada (um DataJud fora do ar pra um
tribunal, um webhook_url que não responde) nunca derruba a varredura
inteira — cada nível falha e faz retry de forma independente.
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.ssrf import WebhookUrlInseguraError, validar_url_webhook
from app.models.consulta_log import ConsultaLog  # noqa: F401 - garante metadata carregado
from app.models.monitoramento import AlertaEnviado, Monitoramento
from app.models.processo import Movimento, Processo
from app.services.datajud_adapter import DataJudAdapter, normalizar_processo_datajud
from app.worker.db import worker_session
from app.worker.webhook import assinar_payload, identificar_movimentos_novos, montar_payload_webhook

logger = logging.getLogger(__name__)
settings = get_settings()


def _buscar_no_datajud_sync(numero_cnj: str, tribunal: str) -> dict | None:
    """
    Ponte sync -> async: cria um event loop novo por chamada, roda o
    adapter async dentro dele, fecha tudo. Não compartilha estado entre
    chamadas (diferente do problema de engine de DB), então é seguro
    mesmo sob fork do Celery — cada task cria e destrói seu próprio loop.
    """

    async def _fetch():
        async with DataJudAdapter() as adapter:
            return await adapter.buscar_por_numero_cnj(numero_cnj, tribunal)

    return asyncio.run(_fetch())


@celery_app.task(name="app.worker.tasks.varrer_monitoramentos_ativos")
def varrer_monitoramentos_ativos() -> int:
    """
    Task periódica (agendada via beat_schedule). Só enfileira o trabalho
    de verificação de cada monitoramento — não faz o trabalho pesado ela
    mesma, pra não virar uma task gigante e monolítica que trava a fila.
    """
    with worker_session() as db:
        stmt = select(Monitoramento.id).where(Monitoramento.ativo.is_(True))
        ids = db.execute(stmt).scalars().all()

    for monitoramento_id in ids:
        verificar_processo_monitorado.delay(str(monitoramento_id))

    logger.info("Varredura enfileirou %d monitoramentos", len(ids))
    return len(ids)


@celery_app.task(
    name="app.worker.tasks.verificar_processo_monitorado",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def verificar_processo_monitorado(self, monitoramento_id: str) -> None:
    with worker_session() as db:
        monitoramento = db.get(Monitoramento, monitoramento_id)
        if monitoramento is None or not monitoramento.ativo:
            return

        processo = db.get(Processo, monitoramento.processo_id)
        if processo is None:
            logger.warning("Monitoramento %s aponta para processo inexistente", monitoramento_id)
            return

        # Primeira verificação = momento em que o monitoramento foi criado
        # e ainda não rodou nenhuma varredura. Nesse caso fazemos só o
        # backfill dos movimentos já existentes, SEM disparar webhook —
        # senão o cliente recebe uma enxurrada de "alertas" de movimentos
        # que já existiam antes dele monitorar, o que não é o que ele pediu.
        eh_primeira_verificacao = monitoramento.ultima_verificacao_em is None

        try:
            bruto = _buscar_no_datajud_sync(processo.numero_cnj, processo.tribunal)
        except Exception as exc:
            logger.warning("Falha ao consultar DataJud para %s: %s", processo.numero_cnj, exc)
            raise self.retry(exc=exc)

        if bruto is None:
            monitoramento.ultima_verificacao_em = datetime.now(timezone.utc)
            db.commit()
            return

        dados = normalizar_processo_datajud(bruto, processo.tribunal)

        hashes_existentes = {
            h for (h,) in db.execute(
                select(Movimento.hash_dedup).where(Movimento.processo_id == processo.id)
            ).all()
        }
        novos = identificar_movimentos_novos(hashes_existentes, dados["movimentos"])

        alertas_para_enviar: list[str] = []
        for mov in novos:
            movimento = Movimento(
                processo_id=processo.id,
                data_movimento=mov["data_movimento"],
                descricao=mov["descricao"],
                codigo_cnj=mov["codigo_cnj"],
                hash_dedup=mov["hash_dedup"],
            )
            db.add(movimento)
            db.flush()  # garante movimento.id antes de referenciar no alerta

            if not eh_primeira_verificacao:
                alerta = AlertaEnviado(
                    monitoramento_id=monitoramento.id,
                    movimento_id=movimento.id,
                    status_entrega="pendente",
                )
                db.add(alerta)
                db.flush()
                alertas_para_enviar.append(str(alerta.id))

        monitoramento.ultima_verificacao_em = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "Monitoramento %s: %d movimento(s) novo(s), %d alerta(s) a enviar (primeira_verificacao=%s)",
            monitoramento_id, len(novos), len(alertas_para_enviar), eh_primeira_verificacao,
        )

        for alerta_id in alertas_para_enviar:
            enviar_webhook.delay(alerta_id)


@celery_app.task(
    name="app.worker.tasks.enviar_webhook",
    bind=True,
    max_retries=settings.WEBHOOK_MAX_TENTATIVAS,
)
def enviar_webhook(self, alerta_id: str) -> None:
    with worker_session() as db:
        alerta = db.get(AlertaEnviado, alerta_id)
        if alerta is None:
            return

        monitoramento = db.get(Monitoramento, alerta.monitoramento_id)
        movimento = db.get(Movimento, alerta.movimento_id)
        if monitoramento is None or movimento is None:
            alerta.status_entrega = "falhou"
            db.commit()
            return

        # Revalida a URL imediatamente antes de enviar: defende contra DNS
        # rebinding (host que resolvia para IP público na criação e passa a
        # resolver para um endereço interno depois). Falha definitiva, sem retry.
        try:
            validar_url_webhook(monitoramento.webhook_url)
        except WebhookUrlInseguraError as exc:
            alerta.status_entrega = "falhou"
            db.commit()
            logger.error("Webhook %s bloqueado por SSRF (%s): %s", alerta_id, monitoramento.webhook_url, exc)
            return

        processo = db.get(Processo, monitoramento.processo_id)

        payload_bytes = montar_payload_webhook(
            processo.numero_cnj,
            processo.tribunal,
            {
                "data_movimento": movimento.data_movimento,
                "descricao": movimento.descricao,
                "codigo_cnj": movimento.codigo_cnj,
            },
        )
        assinatura = assinar_payload(payload_bytes, monitoramento.webhook_secret)

        alerta.tentativas += 1

        try:
            with httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SEGUNDOS) as client:
                resposta = client.post(
                    monitoramento.webhook_url,
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-AdvoJuri-Signature": assinatura,
                    },
                )
            resposta.raise_for_status()
        except Exception as exc:
            db.commit()  # persiste o incremento de tentativas mesmo em falha
            if alerta.tentativas >= settings.WEBHOOK_MAX_TENTATIVAS:
                alerta.status_entrega = "falhou"
                db.commit()
                logger.error("Webhook %s falhou definitivamente após %d tentativas", alerta_id, alerta.tentativas)
                return
            # backoff exponencial: 2, 4, 8, 16... segundos
            raise self.retry(exc=exc, countdown=2 ** alerta.tentativas)

        alerta.status_entrega = "entregue"
        db.commit()
