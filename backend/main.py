"""Backend API: KB service (Q2), calls/dispatch + mock CRM (Q1/Q3), copilot hub (Q4)."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(find_dotenv())

import crm  # noqa: E402
from api import calls, copilot_hub, kb  # noqa: E402
from api import crm as crm_api  # noqa: E402

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    crm.init()
    try:
        kb.retriever()  # load model + index once at startup, not on the first call
    except FileNotFoundError:
        logging.warning("KB not built yet: run `uv run python -m kb.build`")
    yield


app = FastAPI(title="Darwix Voice AI API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (kb.router, calls.router, crm_api.router, copilot_hub.router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
