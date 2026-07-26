import enum

from pydantic import BaseModel, Field

from app.schemas.processo import ProcessoResponse


class TipoBusca(str, enum.Enum):
    # NUMERO_CNJ deliberadamente NÃO existe aqui — busca exata por número é
    # GET /v1/processos/{numero_cnj}, endpoint diferente. Já existiu como
    # opção aqui e causava confusão real: selecionar "numero_cnj" fazia o
    # número virar termo de busca fuzzy por NOME (sempre retornava vazio,
    # silenciosamente, sem erro nenhum indicando o uso errado).
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
    tribunais_pesquisados: list[str]  # os que responderam de fato
    tribunais_com_falha: list[str] = Field(
        default_factory=list,
        description="Tribunais que não responderam. Resultado é parcial: pode haver processos não listados.",
    )
    resultados: list[ResultadoBusca]
    aviso: str | None = None
