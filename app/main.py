# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.routers import trades, market, logs, users
from app.scheduler import start_scheduler
from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    await init_db()
    print("✅ Database initialized successfully")
    yield
    print("Application shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    description="Manage your stock portfolio",
    version="1.0.0",
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(trades.router, prefix="/trades", tags=["Trades"])
app.include_router(market.router, prefix="/market", tags=["Market"])
app.include_router(logs.router, prefix="/logs", tags=["Logs"])
app.include_router(users.router, prefix="/users", tags=["Users"])


@app.get("/")
def root():
    return {"message": "Auto Trading Backend Running 🚀"}


@app.on_event("startup")
async def startup_event():
    start_scheduler()
