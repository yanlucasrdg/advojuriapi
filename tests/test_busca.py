"""
Testes do fluxo de busca por nome/CNPJ/CPF.
Não sobe a app inteira com TestClient (isso exigiria Postgres real por causa
das dependencies de DB) — testa a lógica que dá pra isolar sem infra:
normalização do payload do DataJud e validação do schema Pydantic resultante,
que é exatamente o ponto que eu suspeitava ser frágil (dict cru virando
model Pydantic dentro de outro model).
"""

from app.schemas.busca import ConfiancaMatch, ResultadoBusca
from app.services.cnpj_resolver import normalizar_cnpj
from app.services.datajud_adapter import normalizar_processo_datajud


def test_normalizar_cnpj_remove_pontuacao():
    assert normalizar_cnpj("11.222.333/0001-81") == "11222333000181"
    assert normalizar_cnpj("11222333000181") == "11222333000181"


def test_normalizar_processo_datajud_produz_dict_valido_para_schema():
    bruto_datajud = {
        "numeroProcesso": "50050239620234036309",
        "classe": {"nome": "Cumprimento de Sentença"},
        "assuntos": [{"nome": "Assunto A"}, {"nome": "Assunto B"}],
        "orgaoJulgador": {"nome": "1ª Vara Federal"},
        "dataAjuizamento": "2023-05-10T00:00:00.000Z",
        "nivelSigilo": 0,
        "partes": [
            {"nome": "Fulano de Tal", "tipoPessoa": "fisica", "polo": "ativo"},
        ],
        "movimentos": [
            {"nome": "Distribuição", "dataHora": "2023-05-10T10:00:00.000Z", "codigo": 26},
        ],
    }

    dados = normalizar_processo_datajud(bruto_datajud, "TRF3")

    assert dados["numero_cnj"] == "50050239620234036309"
    assert dados["assunto"] == "Assunto A, Assunto B"
    assert dados["segredo_justica"] is False
    assert len(dados["partes"]) == 1
    assert len(dados["movimentos"]) == 1
    assert dados["movimentos"][0]["hash_dedup"]  # foi calculado, não vazio


def test_resultado_busca_aceita_dict_normalizado_como_processo():
    """
    Este é o teste que valida a costura frágil: ResultadoBusca.processo é
    tipado como ProcessoResponse, mas em app/api/v1/routes/busca.py o valor
    passado é o dict cru retornado por normalizar_processo_datajud (não uma
    instância ORM). Se o schema não aceitar isso, a rota quebra em runtime
    com um erro de validação Pydantic — melhor pegar isso aqui.
    """
    bruto_datajud = {
        "numeroProcesso": "50050239620234036309",
        "classe": {"nome": "Cumprimento de Sentença"},
        "assuntos": [],
        "orgaoJulgador": {"nome": "1ª Vara Federal"},
        "dataAjuizamento": "2023-05-10T00:00:00.000Z",
        "nivelSigilo": 0,
        "partes": [{"nome": "Fulano de Tal", "tipoPessoa": "fisica", "polo": "ativo"}],
        "movimentos": [{"nome": "Distribuição", "dataHora": "2023-05-10T10:00:00.000Z", "codigo": 26}],
    }
    dados = normalizar_processo_datajud(bruto_datajud, "TRF3")

    resultado = ResultadoBusca(processo=dados, confianca_match=ConfiancaMatch.PROVAVEL)

    assert resultado.processo.numero_cnj == "50050239620234036309"
    assert resultado.processo.partes[0].nome == "Fulano de Tal"
    assert resultado.confianca_match == ConfiancaMatch.PROVAVEL
