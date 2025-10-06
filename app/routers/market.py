from fastapi import APIRouter
import yfinance as yf
from app.utils.logger import logger


router = APIRouter()


@router.get("/nifty")
async def get_nifty_details():
    """
    Fetches Nifty 50 index details using yfinance.
    Includes latest price, % change, and 20/50 EMA values.
    Works even when market is closed.
    """
    try:
        ticker = yf.Ticker("^NSEI")
        data = ticker.history(period="3mo")

        if data.empty:
            return {"error": "Failed to fetch Nifty 50 data"}

        # Calculate 20 EMA and 50 EMA
        data["EMA20"] = data["Close"].ewm(span=20, adjust=False).mean()
        data["EMA50"] = data["Close"].ewm(span=50, adjust=False).mean()

        latest = data.iloc[-1]
        previous_close = data["Close"].iloc[-2] if len(data) > 1 else latest["Close"]
        change = latest["Close"] - previous_close
        percent_change = (change / previous_close) * 100 if previous_close else 0

        result = {
            "symbol": "NIFTY 50",
            "current": round(latest["Close"], 2),
            "open": round(latest["Open"], 2),
            "high": round(latest["High"], 2),
            "low": round(latest["Low"], 2),
            "previous_close": round(previous_close, 2),
            "change": round(change, 2),
            "percent_change": round(percent_change, 2),
            "ema20": round(latest["EMA20"], 2),
            "ema50": round(latest["EMA50"], 2),
        }

        return result

    except Exception as e:
        logger.error(f"Error in /get_nifty_details endpoint: {e}")
        return {"error": "Failed to fetch Nifty details"}
