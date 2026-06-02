from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routers.foundation import router as foundation_router
from app.routers.v1 import router as v1_router
from app.routers.trust import router as trust_router
from app.routers.data_ingest import router as data_ingest_router
from app.routers.live_progress import router as live_progress_router
from app.store.memory_store import init_db
from app.version import APP_VERSION

app = FastAPI(title="wgs-cockpit-api", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve result/input/reference files for IGV.js and browser access
for _dir in ["/data/results", "/data/input", "/data/references"]:
    if Path(_dir).is_dir():
        app.mount(f"/files{_dir}", StaticFiles(directory=_dir), name=f"files-{_dir.split('/')[-1]}")

app.include_router(foundation_router)
app.include_router(v1_router)
app.include_router(trust_router)
app.include_router(data_ingest_router)
app.include_router(live_progress_router)


@app.on_event("startup")
def _startup_init_db():
    init_db()
