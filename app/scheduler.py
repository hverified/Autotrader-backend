# backend/app/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.routers import trades
from app.utils.logger import logger
from app.services import trading


async def scheduled_shortlist_job():
    try:
        await trades.shortlist_stocks(manual=False)
        logger.info("Scheduled shortlist job completed at 5 PM")
    except Exception as e:
        logger.error(f"Error in scheduled_shortlist_job: {e}")


async def scheduled_buy_job():
    try:
        await trades.buy_shortlisted(manual=False)
        logger.info("Scheduled buy job completed at 9:30 AM")
    except Exception as e:
        logger.error(f"Error in scheduled_buy_job: {e}")


def start_scheduler():
    """Start APScheduler with async jobs."""
    scheduler = AsyncIOScheduler()

    # Scrape at 5 PM every weekday
    scheduler.add_job(
        scheduled_shortlist_job,
        CronTrigger(day_of_week="mon-fri", hour=20, minute=22),
        id="shortlist_job",
    )

    # Buy at 9:30 AM every weekday
    scheduler.add_job(
        scheduled_buy_job,
        CronTrigger(day_of_week="mon-fri", hour=20, minute=51),
        id="buy_job",
    )

    # 6 PM EOD check
    scheduler.add_job(
        trading.mark_to_sell_eod,
        CronTrigger(day_of_week="mon-fri", hour=20, minute=12),
        id="eod_to_sell",
    )

    # 9:16 AM next day execution
    scheduler.add_job(
        trading.execute_sell_next_day,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=16),
        id="sell_next_day",
    )

    scheduler.start()
    logger.info("Scheduler started!")
