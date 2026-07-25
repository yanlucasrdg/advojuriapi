from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()

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


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.ENV}
