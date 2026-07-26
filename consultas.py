from fastapi import APIRouter

from app.api.v1.routes import auth, busca, monitoramentos, processos, saldo

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(processos.router)
api_router.include_router(busca.router)
api_router.include_router(monitoramentos.router)
api_router.include_router(saldo.router)
