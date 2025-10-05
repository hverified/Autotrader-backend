# backend/app/services/trading.py
import yfinance as yf
from datetime import datetime
from app.config import settings
from app.utils.logger import logger
from app.database import trades_collection


async def is_nifty_above_50ema():
    nifty = yf.download("^NSEI", period="6mo", interval="1d", auto_adjust=False)
    if nifty.empty:
        return False
    nifty["50ema"] = nifty["Close"].ewm(span=50, adjust=False).mean()
    last = nifty.iloc[-1]
    return float(last["Close"]) > float(last["50ema"])


async def check_stock_above_50ema(symbol: str) -> bool:
    data = yf.download(f"{symbol}.NS", period="6mo", interval="1d", auto_adjust=False)
    if data.empty or len(data) < 50:
        return False
    data["50ema"] = data["Close"].ewm(span=50, adjust=False).mean()
    last = data.iloc[-1]
    return float(last["Close"]) > float(last["50ema"])


async def buy_stock(stock):
    symbol = stock["symbol"]
    try:
        # Try intraday first
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

        if "_id" in stock:
            await trades_collection.update_one(
                {"_id": stock["_id"]}, {"$set": update_fields}
            )
        else:
            result = await trades_collection.insert_one({**stock, **update_fields})
            stock["_id"] = result.inserted_id

        stock.update(update_fields)
        logger.info(f"Bought {symbol} at {price} (qty {qty})")
        return stock
    except Exception as e:
        logger.error(f"Error in buy_stock for {symbol}: {e}")
        return None


async def check_stock_for_to_sell(stock):
    """
    Check if stock should be marked 'to_sell' at EOD.
    Condition: price ≥ 6% above buy price OR price < 50 EMA
    """
    symbol = stock["symbol"]
    data = yf.download(f"{symbol}.NS", period="6mo", interval="1d")
    if data.empty:
        return False

    data["50ema"] = data["Close"].ewm(span=50).mean()
    last = data.iloc[-1]
    bought_price = stock.get("buy_price")
    if bought_price is None:
        return False

    # % change since buy
    up_percent = ((last["Close"] - bought_price) / bought_price) * 100

    # Sell conditions
    if last["Close"] < last["50ema"] or up_percent >= 6:
        return True
    return False


async def mark_to_sell_eod():
    """6 PM job: check all bought stocks and mark as 'to_sell' if condition met."""
    bought_stocks = await trades_collection.find({"status": "bought"}).to_list(100)
    for stock in bought_stocks:
        if await check_stock_for_to_sell(stock):
            await trades_collection.update_one(
                {"_id": stock["_id"]}, {"$set": {"status": "to_sell"}}
            )
            logger.info(f"Marked {stock['symbol']} as to_sell")


async def sell_stock(stock):
    """Sell a stock at current price and mark as sold."""
    symbol = stock["symbol"]
    data = yf.download(f"{symbol}.NS", period="1d", interval="1m")
    if data.empty:
        data = yf.download(f"{symbol}.NS", period="5d", interval="1d")
    if data.empty:
        return None

    sell_price = float(data.iloc[-1]["Close"])
    buy_price = stock.get("buy_price", 0)
    profit_pct = ((sell_price - buy_price) / buy_price) * 100 if buy_price else None

    update_fields = {
        "status": "sold",
        "sell_price": sell_price,
        "sell_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "profit_pct": profit_pct,
    }

    await trades_collection.update_one({"_id": stock["_id"]}, {"$set": update_fields})
    stock.update(update_fields)
    logger.info(f"Sold {symbol} at {sell_price} (P/L: {profit_pct:.2f}%)")
    return stock


async def execute_sell_next_day():
    """9:16 AM job: sell all stocks marked 'to_sell'."""
    to_sell_stocks = await trades_collection.find({"status": "to_sell"}).to_list(100)
    for stock in to_sell_stocks:
        await sell_stock(stock)
