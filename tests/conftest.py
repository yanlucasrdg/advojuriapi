"""
Configuração compartilhada da suíte de testes.

Vários módulos (`datajud_adapter`, `security`, `cache`, ...) chamam
`get_settings()` no momento do import, e `Settings` exige `DATABASE_URL`
e `DATAJUD_API_KEY`. Em CI/local esses valores não existem como env var,
então definimos placeholders determinísticos ANTES de qualquer import de
`app.*` acontecer. Como o conftest é carregado pelo pytest antes de coletar
os módulos de teste, isso garante que os imports não estourem
ValidationError — sem depender de um arquivo `.env` presente no repo.
"""

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb"
)
os.environ.setdefault("DATAJUD_API_KEY", "test-datajud-key")
