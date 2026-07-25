import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    description="API de consulta processual — núcleo (auth, billing, DataJud adapter)",
    version="0.1.0",
)

# CORS: liberado para o painel (Lovable) chamar a API de um domínio diferente.
# Em produção, ALLOWED_ORIGINS deve ser a lista explícita do(s) domínio(s)
# do painel — nunca "*", porque os endpoints usam Bearer token, e "*" com
# credenciais habilitadas é uma combinação insegura (embora aqui as
# credenciais venham no header, não em cookie, o princípio de não usar
# wildcard em produção continua valendo).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"erro": True, "mensagem": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Erro de validação com o mesmo envelope dos demais erros. Sem isto o
    cliente recebe `{"detail": [...]}` em 422 e `{"erro": ...}` em todo o
    resto — dois formatos de erro para tratar na mesma API."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "erro": True,
            "mensagem": "Requisição inválida",
            "detalhes": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Última rede de segurança: qualquer exceção não tratada vai para o log
    com stack trace (senão o erro some e só sobra um 500 vazio no cliente) e
    volta no mesmo envelope de erro, sem expor a mensagem interna."""
    logger.exception("Erro não tratado em %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"erro": True, "mensagem": "Erro interno inesperado"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.ENV}
