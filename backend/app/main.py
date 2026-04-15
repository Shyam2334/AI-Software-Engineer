"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import plugins, tasks, websocket
from app.config import get_settings
from app.database import close_db, init_db

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown events."""
    logger.info("Starting AI Software Engineer backend...")
    logger.info(
        "Config: anthropic_key=%s, gemini_key=%s",
        "set" if settings.anthropic_api_key else "MISSING",
        "set" if settings.gemini_api_key else "MISSING",
    )
    await init_db()
    logger.info("Database initialized")
    yield
    await close_db()
    logger.info("Backend shut down cleanly")


app = FastAPI(
    title="AI Software Engineer",
    description="Autonomous AI Software Engineer with multi-agent orchestration",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(plugins.router, prefix="/api/plugins", tags=["plugins"])
app.include_router(websocket.router, tags=["websocket"])


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for Docker and load balancers."""
    return {"status": "healthy", "service": "ai-software-engineer"}


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "message": "AI Software Engineer API",
        "version": "1.0.0",
        "docs": "/docs",
    }
