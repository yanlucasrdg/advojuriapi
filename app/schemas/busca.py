import enum

from pydantic import BaseModel

from app.schemas.processo import ProcessoResponse


class TipoBusca(str, enum.Enum):
    NUMERO_CNJ = "numero_cnj"
    CNPJ = "cnpj"
    NOME = "nome"
    CPF = "cpf"  # aceito no enum só para dar erro explicativo, não suportado


class ConfiancaMatch(str, enum.Enum):
    EXATA = "exata"  # veio de numero_cnj
    PROVAVEL = "provavel"  # veio de match de nome (fuzzy), inclusive quando originado de CNPJ resolvido


class ResultadoBusca(BaseModel):
    processo: ProcessoResponse
    confianca_match: ConfiancaMatch


class BuscaResponse(BaseModel):
    tipo_busca: TipoBusca
    termo_resolvido: str | None = None  # ex: razão social encontrada a partir do CNPJ
    tribunais_pesquisados: list[str]
    resultados: list[ResultadoBusca]
    aviso: str | None = None
