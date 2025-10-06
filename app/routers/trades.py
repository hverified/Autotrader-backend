from fastapi import APIRouter, Query, Body, HTTPException
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
from app.utils.helpers import current_date
from app.models.trade_model import StockSymbol
from app.config import settings
import yfinance as yf

router = APIRouter()


def serialize_mongo_doc(doc):
    """Convert ObjectId to string for JSON serialization."""
    doc["_id"] = str(doc["_id"])
    return doc


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


# ------------------------ Mark Not Triggered ------------------------
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


# ------------------------ Buy Stock ------------------------
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


# @router.post("/buy_stock")
# async def buy_stock_api(symbol: str = Body(..., embed=True)):
#     """
#     Buy a single shortlisted stock if Nifty 50 and stock EMA conditions pass.
#     """
#     try:
#         stock_doc = await trades_collection.find_one(
#             {"symbol": symbol, "status": "shortlisted"}
#         )
#         if not stock_doc:
#             return {
#                 "success": False,
#                 "message": f"Stock {symbol} not found or already bought.",
#             }

#         stock = serialize_mongo_doc(stock_doc)

#         # Check Nifty 50 EMA
#         if not await is_nifty_above_50ema():
#             await trades_collection.update_one(
#                 {"_id": stock["_id"]},
#                 {
#                     "$set": {
#                         "status": "not_triggered",
#                         "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
#                     }
#                 },
#             )
#             return {
#                 "success": False,
#                 "message": "Nifty 50 below 50 EMA. Stock marked as not_triggered.",
#                 "stock": stock,
#             }

#         # Check individual stock EMA
#         if not await check_stock_above_50ema(symbol):
#             await trades_collection.update_one(
#                 {"_id": stock["_id"]},
#                 {
#                     "$set": {
#                         "status": "not_triggered",
#                         "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
#                     }
#                 },
#             )
#             return {
#                 "success": False,
#                 "message": f"{symbol} below 50 EMA. Stock marked as not_triggered.",
#                 "stock": stock,
#             }

#         # Buy the stock
#         bought_stock = await buy_stock(stock)
#         if not bought_stock:
#             return {
#                 "success": False,
#                 "message": f"Failed to buy {symbol}.",
#                 "stock": stock,
#             }

#         bought_stock["_id"] = str(bought_stock["_id"])
#         return {
#             "success": True,
#             "message": f"{symbol} bought successfully.",
#             "stock": bought_stock,
#         }

#     except Exception as e:
#         logger.error(f"Error buying stock {symbol}: {e}")
#         return {"success": False, "message": f"Error buying stock {symbol}."}


# @router.post("/mark_not_triggered")
# async def mark_not_triggered(symbol: str):
#     """
#     Mark a shortlisted stock as 'not_triggered'.
#     """
#     try:
#         # Find the stock by symbol and status 'shortlisted'
#         stock = await trades_collection.find_one(
#             {"symbol": symbol, "status": "shortlisted"}
#         )
#         if not stock:
#             return {
#                 "success": False,
#                 "message": "Stock not found or not in shortlisted status",
#             }

#         # Update status
#         await trades_collection.update_one(
#             {"_id": stock["_id"]},
#             {
#                 "$set": {
#                     "status": "not_triggered",
#                     "checked_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
#                 }
#             },
#         )

#         logger.info(f"Stock {symbol} marked as not_triggered")
#         return {"success": True, "message": f"{symbol} marked as not_triggered"}

#     except Exception as e:
#         logger.error(f"Error marking stock {symbol} as not_triggered: {e}")
#         raise HTTPException(
#             status_code=500, detail="Failed to mark stock as not_triggered"
#         )


@router.post("/buy")
async def buy_shortlisted():
    """Buy shortlisted stocks based on Nifty and stock EMA conditions."""
    try:
        shortlisted = await trades_collection.find({"status": "shortlisted"}).to_list(
            100
        )
        shortlisted = [serialize_mongo_doc(s) for s in shortlisted]

        if not shortlisted:
            return {"bought": [], "not_triggered": []}

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
                not_triggered.append(
                    {"symbol": stock["symbol"], "status": "not_triggered"}
                )
            return {"bought": bought, "not_triggered": not_triggered}

        # Check individual stocks
        for stock in shortlisted:
            if await check_stock_above_50ema(stock["symbol"]):
                await buy_stock(stock)
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
                not_triggered.append(
                    {"symbol": stock["symbol"], "status": "not_triggered"}
                )

        return {"bought": bought, "not_triggered": not_triggered}

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
