from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ParteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nome: str
    documento: str | None = None
    tipo_pessoa: str | None = None
    polo: str | None = None


class MovimentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data_movimento: datetime
    descricao: str
    codigo_cnj: str | None = None


class ProcessoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero_cnj: str
    tribunal: str
    classe: str | None = None
    assunto: str | None = None
    orgao_julgador: str | None = None
    valor_acao: float | None = None
    data_ajuizamento: date | None = None
    segredo_justica: bool
    partes: list[ParteResponse] = []
    movimentos: list[MovimentoResponse] = []
    atualizado_em: datetime


class ProcessoNaoEncontrado(BaseModel):
    erro: str = "processo_nao_encontrado"
    mensagem: str
