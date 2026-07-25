from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "advojuri_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Fortaleza",
    enable_utc=True,
    task_acks_late=True,  # se o worker morrer no meio da task, reprocessa em vez de perder
    worker_prefetch_multiplier=1,  # evita um worker travar várias tasks de monitoramento numa fila só
)

celery_app.conf.beat_schedule = {
    "varrer-monitoramentos-ativos": {
        "task": "app.worker.tasks.varrer_monitoramentos_ativos",
        "schedule": crontab(minute=f"*/{settings.INTERVALO_VARREDURA_MONITORAMENTOS_MINUTOS}"),
    },
}
