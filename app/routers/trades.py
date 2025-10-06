from fastapi import APIRouter, Query
from datetime import datetime
from app.services.scraping import scrape_chartink
from app.services.trading import (
    is_nifty_above_50ema,
    check_stock_above_50ema,
    buy_stock,
    mark_to_sell_eod,
    execute_sell_next_day,
)
from app.database import trades_collection
from app.utils.logger import logger

router = APIRouter()


def serialize_mongo_doc(doc):
    """Convert ObjectId to string for JSON serialization."""
    doc["_id"] = str(doc["_id"])
    return doc


@router.post("/update_shortlist")
async def update_shortlist():
    try:
        stocks = scrape_chartink()
        if not stocks:
            return {"message": "No stocks scraped"}

        result = await trades_collection.insert_many(stocks)
        for idx, stock in enumerate(stocks):
            stock["_id"] = str(result.inserted_ids[idx])
        return {"message": f"{len(stocks)} stocks scraped and stored"}
    except Exception as e:
        logger.error(f"Error in /update_shortlist endpoint: {e}")
        return {"error": "Failed to update shortlist"}


@router.get("/get_stocks")
async def get_stocks():
    """
    Returns stocks stored in DB.
    """
    try:
        all_stocks = await trades_collection.find({}).to_list(length=None)
        all_stocks = [serialize_mongo_doc(s) for s in all_stocks]

        grouped = {
            "shortlisted": [],
            "bought": [],
            "not_triggered": [],
            "to_sell": [],
            "sold": [],
        }
        for stock in all_stocks:
            status = stock.get("status", "shortlisted")
            grouped.setdefault(status, []).append(stock)
        return grouped

    except Exception as e:
        logger.error(f"Error in /get_stocks endpoint: {e}")
        return {"error": "Failed to fetch stocks"}


@router.post("/buy")
async def buy_shortlisted(
    manual: bool = Query(False, description="Return stocks if manual")
):
    """Buy shortlisted stocks based on Nifty and stock EMA conditions."""
    try:
        shortlisted = await trades_collection.find({"status": "shortlisted"}).to_list(
            100
        )
        shortlisted = [serialize_mongo_doc(s) for s in shortlisted]

        if not shortlisted:
            return {"bought": [], "not_triggered": []} if manual else None

        bought = []
        not_triggered = []

        # Check Nifty condition
        if not await is_nifty_above_50ema():
            for stock in shortlisted:
                await trades_collection.update_one(
                    {"_id": stock["_id"]},
                    {
                        "$set": {
                            "status": "not_triggered",
                            "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        }
                    },
                )
                if manual:
                    not_triggered.append(
                        {"symbol": stock["symbol"], "status": "not_triggered"}
                    )
            return (
                {"bought": bought, "not_triggered": not_triggered} if manual else None
            )

        # Check individual stocks
        for stock in shortlisted:
            if await check_stock_above_50ema(stock["symbol"]):
                await buy_stock(stock)
                if manual:
                    bought.append(stock)
            else:
                await trades_collection.update_one(
                    {"_id": stock["_id"]},
                    {
                        "$set": {
                            "status": "not_triggered",
                            "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        }
                    },
                )
                if manual:
                    not_triggered.append(
                        {"symbol": stock["symbol"], "status": "not_triggered"}
                    )

        return {"bought": bought, "not_triggered": not_triggered} if manual else None

    except Exception as e:
        logger.error(f"Error in /buy endpoint: {e}")
        return {"error": "Failed to buy stocks"}


@router.post("/check_to_sell")
async def check_to_sell(manual: bool = Query(False)):
    """Manually check EOD sell conditions (6 PM)."""
    try:
        await mark_to_sell_eod()
        if manual:
            stocks = await trades_collection.find({"status": "to_sell"}).to_list(100)
            stocks = [serialize_mongo_doc(s) for s in stocks]
            return {"to_sell": stocks}
        return {"message": "EOD sell check completed"}
    except Exception as e:
        logger.error(f"Error in /check_to_sell endpoint: {e}")
        return {"error": "Failed to check EOD sell"}


@router.post("/sell_next_day")
async def sell_next_day(manual: bool = Query(False)):
    """Manually sell all stocks marked 'to_sell' (9:16 AM)."""
    try:
        await execute_sell_next_day()
        if manual:
            sold_stocks = await trades_collection.find({"status": "sold"}).to_list(100)
            sold_stocks = [serialize_mongo_doc(s) for s in sold_stocks]
            return {"sold": sold_stocks}
        return {"message": "Next day sell executed"}
    except Exception as e:
        logger.error(f"Error in /sell_next_day endpoint: {e}")
        return {"error": "Failed to execute next day sell"}
