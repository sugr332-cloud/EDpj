"""FastAPI app entrypoint. Phase 1 mounts only the State API
(IMPLEMENTATION_SPEC_V0.2.md §13.1); score/mining/bio/calibration
endpoints are later phases and not registered here."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.state import router as state_router

app = FastAPI(title="EDpj API")
app.include_router(state_router)
