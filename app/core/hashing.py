"""
Hashes determinísticos usados em pontos diferentes do sistema: API keys,
dedup de movimentos do DataJud e log de consultas (que guarda o hash do
termo pesquisado, nunca o termo em claro).
"""

import hashlib


def sha256_hex(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hash_termo_busca(termo: str) -> str:
    """Normaliza (trim + lowercase) antes de hashear, para que o mesmo termo
    digitado de formas diferentes gere a mesma entrada no log de consultas."""
    return sha256_hex(termo.strip().lower())
