import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MonitoramentoCreate(BaseModel):
    numero_cnj: str = Field(..., description="Processo já deve existir (consultado antes via /v1/processos)")
    tribunal: str
    webhook_url: str = Field(..., description="URL HTTPS que receberá o POST quando houver movimento novo")


class MonitoramentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    processo_id: uuid.UUID
    webhook_url: str
    ativo: bool
    ultima_verificacao_em: datetime | None
    criado_em: datetime


class MonitoramentoCriadoResponse(MonitoramentoResponse):
    webhook_secret: str = Field(
        ..., description="Mostrado uma única vez. Use para validar a assinatura HMAC dos webhooks recebidos."
    )
