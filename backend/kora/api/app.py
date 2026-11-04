"""FastAPI application for Kora's Phase 1 API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from kora.aggregator import Aggregator
from kora.api.schemas import (
    HealthOut,
    ProfileOut,
    ResolveRequest,
    ScholarSummary,
)
from kora.http import HttpClient
from kora.storage.database import (
    Settings,
    build_engine,
    build_session_factory,
    database_ok,
    init_schema,
)
from kora.storage.repository import get_profile, list_scholars, save_profile

log = logging.getLogger(__name__)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_aggregator(request: Request) -> Aggregator:
    return Aggregator(request.app.state.http)


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    http_client: HttpClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_engine = engine is None
        owns_http = http_client is None
        app.state.settings = settings
        app.state.engine = engine or build_engine(settings)
        app.state.session_factory = build_session_factory(app.state.engine)
        app.state.http = http_client or HttpClient(cache_dir=settings.cache_dir)
        if settings.auto_create_schema:
            await init_schema(app.state.engine)
        try:
            yield
        finally:
            if owns_http:
                await app.state.http.close()
            if owns_engine:
                await app.state.engine.dispose()

    app = FastAPI(title=settings.title, version=settings.version, lifespan=lifespan)

    @app.get("/health", response_model=HealthOut, tags=["system"])
    async def health(request: Request) -> HealthOut:
        ok = await database_ok(request.app.state.engine)
        return HealthOut(
            status="ok" if ok else "degraded",
            version=settings.version,
            database="ok" if ok else "unavailable",
        )

    @app.post("/v1/profiles/resolve", response_model=ProfileOut, tags=["profiles"])
    async def resolve(
        body: ResolveRequest,
        session: AsyncSession = Depends(get_session),
        aggregator: Aggregator = Depends(get_aggregator),
    ) -> ProfileOut:
        profile = await aggregator.build_profile(
            body.query, pick=body.pick, include_about=body.include_about
        )
        if profile is None:
            raise HTTPException(status_code=404, detail=f"No person found for {body.query!r}")
        scholar_id = None
        if body.persist:
            try:
                scholar_id = await save_profile(session, profile)
            except Exception as exc:  # noqa: BLE001 - surface storage failure honestly
                log.exception("failed to persist profile for %s", body.query)
                raise HTTPException(
                    status_code=503, detail="Profile resolved but persistence failed"
                ) from exc
        return ProfileOut.from_model(profile, scholar_id=scholar_id, stored=body.persist)

    @app.get("/v1/profiles/{query}", response_model=ProfileOut, tags=["profiles"])
    async def resolve_live(
        query: str,
        pick: int = Query(default=0, ge=0),
        include_about: bool = True,
        aggregator: Aggregator = Depends(get_aggregator),
    ) -> ProfileOut:
        """Live resolution without writing to the database."""
        profile = await aggregator.build_profile(
            query, pick=pick, include_about=include_about
        )
        if profile is None:
            raise HTTPException(status_code=404, detail=f"No person found for {query!r}")
        return ProfileOut.from_model(profile)

    @app.get("/v1/scholars", response_model=list[ScholarSummary], tags=["scholars"])
    async def scholars(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        session: AsyncSession = Depends(get_session),
    ) -> list[ScholarSummary]:
        rows = await list_scholars(session, limit=limit, offset=offset)
        return [ScholarSummary(**row) for row in rows]

    @app.get("/v1/scholars/{scholar_id}", response_model=ProfileOut, tags=["scholars"])
    async def scholar(
        scholar_id: int,
        session: AsyncSession = Depends(get_session),
    ) -> ProfileOut:
        profile = await get_profile(session, scholar_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Scholar not found")
        return ProfileOut.from_model(profile, scholar_id=scholar_id, stored=True)

    return app


app = create_app()
