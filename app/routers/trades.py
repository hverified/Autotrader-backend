# app/routers/trades.py
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime, time
from app.services.scraping import scrape_chartink
from app.services.trading import (
    is_nifty_above_50ema,
    check_stock_above_50ema,
    mark_to_sell_eod,
    execute_sell_next_day,
)
from app.database import trades_collection
from app.utils.logger import logger
from app.utils.helpers import current_date, fetch_intraday_15m_for_today
from app.models.trade_model import StockSymbol
from app.config import settings

from bson import ObjectId
import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

router = APIRouter()


def ensure_objectid(_id):
    """Convert string _id to ObjectId if needed."""
    try:
        return ObjectId(_id)
    except Exception:
        return _id


def serialize_mongo_doc(doc):
    """Convert ObjectId to string for JSON serialization."""
    doc["_id"] = str(doc["_id"])
    return doc


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


@router.post("/update_shortlist")
async def update_shortlist():
    """
    Scrapes stocks from Chartink and inserts them into the DB.
    Avoids inserting duplicates for the same day.
    Only runs if Nifty 50 is trading above its 50 EMA.
    """
    try:
        # 🔹 Check Nifty 50 50EMA condition
        above_50ema = await is_nifty_above_50ema()
        if not above_50ema:
            return {"message": "Nifty 50 is below 50 EMA. Shortlist not updated."}

        # 🔹 Scrape stocks
        stocks = scrape_chartink()
        if not stocks:
            return {"message": "No stocks scraped"}

        today_str = current_date()
        inserted_count = 0

        for stock in stocks:
            stock.setdefault("shortlisted_date", today_str)
            exists = await trades_collection.find_one(
                {
                    "symbol": stock["symbol"],
                    "shortlisted_date": stock["shortlisted_date"],
                }
            )

            if not exists:
                result = await trades_collection.insert_one(stock)
                stock["_id"] = str(result.inserted_id)
                inserted_count += 1
            else:
                stock["_id"] = str(exists["_id"])

        return {
            "message": f"{inserted_count} new stocks inserted, {len(stocks) - inserted_count} skipped (already exists)"
        }

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


@router.post("/mark_not_triggered")
async def mark_not_triggered(payload: StockSymbol):
    symbol = payload.symbol
    try:
        stock = await trades_collection.find_one(
            {"symbol": symbol, "status": "shortlisted"}
        )
        if not stock:
            return {
                "success": False,
                "message": "Stock not found or not in shortlisted status",
            }

        await trades_collection.update_one(
            {"_id": stock["_id"]},
            {
                "$set": {
                    "status": "not_triggered",
                    "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            },
        )

        logger.info(f"Stock {symbol} marked as not_triggered")
        return {"success": True, "message": f"{symbol} marked as not_triggered"}

    except Exception as e:
        logger.error(f"Error marking stock {symbol} as not_triggered: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to mark stock as not_triggered"
        )


@router.post("/buy_stock")
async def buy_stock_api(payload: StockSymbol):
    symbol = payload.symbol
    try:
        stock = await trades_collection.find_one(
            {"symbol": symbol, "status": "shortlisted"}
        )
        if not stock:
            return {
                "success": False,
                "message": "Stock not found or not in shortlisted status",
            }

        # Check Nifty condition
        if not await is_nifty_above_50ema():
            await trades_collection.update_one(
                {"_id": stock["_id"]},
                {
                    "$set": {
                        "status": "not_triggered",
                        "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                },
            )
            return {
                "success": False,
                "message": "Nifty below 50 EMA, stock not triggered",
            }

        # Check individual stock EMA
        if not await check_stock_above_50ema(symbol):
            await trades_collection.update_one(
                {"_id": stock["_id"]},
                {
                    "$set": {
                        "status": "not_triggered",
                        "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                },
            )
            return {
                "success": False,
                "message": f"{symbol} below 50 EMA, not triggered",
            }

        # Buy stock
        bought_stock = await execute_buy_stock(stock)
        if bought_stock:
            return {
                "success": True,
                "message": f"{symbol} bought",
                "stock": bought_stock,
            }
        else:
            return {"success": False, "message": f"Failed to buy {symbol}"}

    except Exception as e:
        logger.error(f"Error buying stock {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Failed to buy stock")


async def execute_buy_stock(stock):
    symbol = stock["symbol"]
    try:
        data = yf.download(f"{symbol}.NS", period="1d", interval="1m")
        if data.empty:
            data = yf.download(f"{symbol}.NS", period="5d", interval="1d")

        if data.empty:
            return None

        price = float(data.iloc[-1]["Close"])
        qty = int(settings.TRADE_CAP // price)
        if qty == 0:
            return None

        update_fields = {
            "buy_price": price,
            "quantity": qty,
            "buy_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status": "bought",
            "per_chg": stock.get("per_chg"),
            "volume": stock.get("volume"),
            "bsecode": stock.get("bsecode"),
            "close": stock.get("close"),
        }

        await trades_collection.update_one(
            {"_id": stock["_id"]}, {"$set": update_fields}
        )
        stock.update(update_fields)

        # Convert _id to string for JSON serialization
        stock["_id"] = str(stock["_id"])

        logger.info(f"Bought {symbol} at {price} (qty {qty})")
        return stock
    except Exception as e:
        logger.error(f"Error in execute_buy_stock for {symbol}: {e}")
        return None


@router.post("/run_buy_shortlisted")
async def buy_shortlisted():
    """
    Cron job: evaluate shortlisted stocks and buy if condition met.
    """
    try:
        shortlisted = await trades_collection.find({"status": "shortlisted"}).to_list(
            100
        )
        if not shortlisted:
            logger.info("No shortlisted stocks found.")
            return {"bought": [], "not_triggered": []}

        bought, not_triggered = [], []

        for stock in shortlisted:
            res = await evaluate_and_buy(stock)
            if res and res.get("status") == "bought":
                bought.append(res)
            else:
                not_triggered.append(
                    {"symbol": stock.get("symbol"), "status": "not_triggered"}
                )

        return {"bought": bought, "not_triggered": not_triggered}

    except Exception as e:
        logger.error(f"Error in /buy endpoint: {e}")
        return {"error": "Failed to buy stocks"}


async def evaluate_and_buy(stock):
    """
    For a stock:
    - Fetch today's 15m intraday (IST).
    - Find the 9:15–9:30 candle (or first market candle fallback).
    - Compare day's high vs that candle's high.
    - If day_high > first_candle_high => buy at 1.002 * first_high (rounded).
    - Else mark not_triggered.
    """
    symbol = stock.get("symbol")
    if not symbol:
        return None

    try:
        data_today = await fetch_intraday_15m_for_today(symbol, lookback_days=5)
        if data_today is None or data_today.empty:
            logger.warning(f"No intraday today data for {symbol}")
            return None

        # pick 9:15–9:30 candle (inclusive start, exclusive end)
        mask_915 = [
            (t.time() >= time(9, 15)) and (t.time() < time(9, 30))
            for t in data_today.index
        ]
        df_915 = data_today[mask_915]

        if df_915.empty:
            # fallback to earliest market candle between 9:00 and 10:00
            mask_market_open = [
                (t.time() >= time(9, 0)) and (t.time() <= time(10, 0))
                for t in data_today.index
            ]
            df_market = data_today[mask_market_open]
            if df_market.empty:
                logger.warning(
                    f"No market-open candles found for {symbol} in today's data."
                )
                return None
            first_row = df_market.iloc[0]
            logger.info(
                f"For {symbol} no exact 9:15 row; falling back to first market candle at {first_row.name}"
            )
        else:
            first_row = df_915.iloc[0]
            logger.info(f"For {symbol} selected 9:15 candle at {first_row.name}")

        # explicit floats from scalar values
        first_high = float(first_row["High"])
        day_high = float(data_today["High"].max())

        logger.info(
            f"{symbol} | first_candle_time={first_row.name} | first_high={first_high} | day_high={day_high}"
        )

        # Decision
        if day_high > first_high:
            buy_price = round(first_high * 1.002, 2)
            qty = int(settings.TRADE_CAP // buy_price)
            if qty == 0:
                logger.warning(f"Skipping buy for {symbol}: qty=0 at price {buy_price}")
                return None

            update_fields = {
                "buy_price": buy_price,
                "quantity": qty,
                "buy_date": datetime.now(ZoneInfo("Asia/Kolkata")).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "status": "bought",
                "checked_date": datetime.now(ZoneInfo("Asia/Kolkata")).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "first_candle_time": str(first_row.name),
                "first_candle_high": first_high,
                "day_high": day_high,
            }

            await trades_collection.update_one(
                {"_id": ensure_objectid(stock["_id"])},
                {"$set": update_fields},
            )

            # update returned dict for API response
            stock.update(update_fields)
            stock["_id"] = str(stock["_id"])
            logger.info(f"Bought {symbol} at {buy_price} (qty {qty})")
            return stock

        else:
            await trades_collection.update_one(
                {"_id": ensure_objectid(stock["_id"])},
                {
                    "$set": {
                        "status": "not_triggered",
                        "checked_date": datetime.now(ZoneInfo("Asia/Kolkata")).strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "first_candle_time": str(first_row.name),
                        "first_candle_high": first_high,
                        "day_high": day_high,
                    }
                },
            )
            logger.info(
                f"{symbol} not triggered (day_high <= first_high). first_high={first_high}, day_high={day_high}"
            )
            return None

    except Exception as e:
        logger.error(f"Error in evaluate_and_buy for {symbol}: {e}")
        return None


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
