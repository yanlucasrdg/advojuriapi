from pydantic import BaseModel, Field


class SaldoResponse(BaseModel):
    saldo_centavos: int
    saldo_reais: float

    @classmethod
    def from_centavos(cls, centavos: int) -> "SaldoResponse":
        return cls(saldo_centavos=centavos, saldo_reais=round(centavos / 100, 2))


class RecargaRequest(BaseModel):
    valor_centavos: int = Field(gt=0, description="Valor da recarga em centavos, ex: 5000 = R$ 50,00")


class RecargaResponse(BaseModel):
    transacao_id: str
    saldo_apos_centavos: int
    status: str  # "pendente" até o gateway de pagamento confirmar
