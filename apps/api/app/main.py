from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.scheduler import shutdown_scheduler, start_scheduler
from app.services.system_log_service import write_log


settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    if settings.v3_enabled:
        from app.services.v3_shadow import ensure_run, snapshot, atomic, now_utc
        from app.models.v3 import V3Equity
        with SessionLocal() as db:
            run = ensure_run(db)
            if not db.query(V3Equity.id).filter_by(run_id=run.id).first():
                with atomic(db):
                    snapshot(db, run, now_utc())
    start_scheduler()
    db = SessionLocal()
    try:
        write_log(db, level="info", module="system", message="API started")
    finally:
        db.close()


@app.on_event("shutdown")
def on_shutdown() -> None:
    shutdown_scheduler()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    db = SessionLocal()
    try:
        write_log(
            db,
            level="error",
            module="api",
            message="Unhandled exception",
            payload={"path": str(request.url.path), "error": str(exc)},
        )
    finally:
        db.close()
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)
