"""api"""

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .logger import log_manager
from .ratelimiter import limiter
from .route import router


def create_app():
    """API app loader"""
    this_app = FastAPI(title="matchbox", version="1.0", description="cRF/Matchability calculator API")
    this_app.mount("/static", StaticFiles(directory="static"), name="static")

    # start up / shut down events
    this_app.add_event_handler("startup", api_startup)
    this_app.add_event_handler("shutdown", api_shutdown)

    # rate limiter

    this_app.state.limiter = limiter
    this_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # include routes
    this_app.include_router(router)
    return this_app


async def api_startup():
    """API start up"""
    # logging set up
    log_manager.setup_application_logging()
    logging.info("API starting up...")


async def api_shutdown():
    """API shut down"""
    logging.info("API shutting down...")
