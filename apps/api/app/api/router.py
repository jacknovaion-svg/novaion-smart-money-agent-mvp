from fastapi import APIRouter

from app.api import auth, dashboard, discovery, market_data, quality, signals, system, validation, wallets


api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(wallets.router)
api_router.include_router(market_data.router)
api_router.include_router(signals.router)
api_router.include_router(quality.router)
api_router.include_router(discovery.router)
api_router.include_router(system.router)
api_router.include_router(validation.router)
