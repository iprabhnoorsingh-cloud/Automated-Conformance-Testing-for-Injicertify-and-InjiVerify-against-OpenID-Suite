from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import api_key_middleware, warn_if_unconfigured
from app.config import settings
from app.executions import router as executions_router
from app.health import router as health_router
from app.reports import router as reports_router
from app.test_runs import router as test_runs_router

app = FastAPI(title=settings.app_name, version=settings.app_version)

# M10: authentication is registered BEFORE CORS so CORS is the outermost
# layer: browser preflight (OPTIONS) requests, which carry no credentials,
# are answered by CORS, and 401 responses still carry CORS headers.
app.middleware("http")(api_key_middleware)
warn_if_unconfigured()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(test_runs_router)
app.include_router(executions_router)
app.include_router(reports_router)


@app.get("/")
def get_root() -> dict:
    return {"name": settings.app_name, "version": settings.app_version}
