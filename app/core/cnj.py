"""
Normalização do número de processo CNJ.

Extraído pra cá depois do mesmo bug aparecer duas vezes em lugares
diferentes (app/api/v1/routes/processos.py e depois monitoramentos.py):
o DataJud devolve numeroProcesso sem pontuação, é isso que fica salvo no
banco, mas o cliente pode mandar o número na URL/JSON com ou sem
pontuação. Toda comparação contra o valor salvo precisa passar por aqui
primeiro — duplicar o `.replace(".", "").replace("-", "")` inline em cada
rota nova é exatamente como o bug voltou a acontecer.
"""


def normalizar_numero_cnj(numero: str) -> str:
    return numero.replace(".", "").replace("-", "")
