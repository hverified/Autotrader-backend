from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import trades
from app.scheduler import start_scheduler
from app.config import settings

app = FastAPI(title="Auto Trading App")

app = FastAPI(
    title=settings.APP_NAME,
    description="Manage your stock portfolio",
    version="1.0.0",
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(trades.router, prefix="/trades", tags=["Trades"])


@app.get("/")
def root():
    return {"message": "Auto Trading Backend Running 🚀"}


@app.on_event("startup")
async def startup_event():
    start_scheduler()
