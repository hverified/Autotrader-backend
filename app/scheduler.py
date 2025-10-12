# backend/app/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from app.routers import trades
from app.services import trading
from app.utils.logger import logger
from app.utils.decorators import job_runner
from app.config import settings


@job_runner("Update Shortlist")
async def run_update_shortlist():
    await trades.update_shortlist()


@job_runner("Buy Shortlisted")
async def run_buy_shortlisted():
    await trades.buy_shortlisted()


@job_runner("Mark EOD Positions to Sell")
async def run_mark_to_sell_eod():
    await trading.mark_to_sell_eod()


@job_runner("Execute Next Day Sells")
async def run_execute_sell_next_day():
    await trading.execute_sell_next_day()


JOBS = [
    {
        "id": "shortlist_job",
        "func": run_update_shortlist,
        "cron": settings.SHORTLIST_CRON,
    },
    # {
    #     "id": "buy_job",
    #     "func": run_buy_shortlisted,
    #     "cron": settings.BUY_CRON,
    # },
    # {
    #     "id": "eod_to_sell",
    #     "func": run_mark_to_sell_eod,
    #     "cron": settings.EOD_MARK_TO_SELL_CRON,
    # },
    # {
    #     "id": "sell_next_day",
    #     "func": run_execute_sell_next_day,
    #     "cron": settings.EXECUTE_SELL_CRON,
    # },
]


def start_scheduler():
    """Initializes and starts the APScheduler with jobs defined in the JOBS list."""
    # Set timezone to Asia/Kolkata
    kolkata_tz = timezone("Asia/Kolkata")
    scheduler = AsyncIOScheduler(timezone=kolkata_tz)

    for job in JOBS:
        hour, minute, day_of_week = job["cron"].split()
        scheduler.add_job(
            job["func"],
            CronTrigger(
                hour=hour,
                minute=minute,
                day_of_week=day_of_week if day_of_week != "*" else "mon-fri",
                timezone=kolkata_tz,
            ),
            id=job["id"],
            name=job["id"],
            replace_existing=True,
        )
        logger.info(f"Scheduled job '{job['id']}' with trigger: {job['cron']}")

    scheduler.start()
    logger.info("Scheduler started successfully!")
