import uuid
from datetime import datetime
import aiohttp
import asyncio
import yfinance as yf
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from bson import ObjectId
from app.utils.logger import logger


def generate_id():
    return str(uuid.uuid4())[:8]


def current_date():
    return datetime.now().strftime("%Y-%m-%d")


def ensure_objectid(id_value):
    """Ensure _id is an ObjectId instance (convert from string if needed)."""
    if isinstance(id_value, ObjectId):
        return id_value
    try:
        return ObjectId(id_value)
    except Exception:
        logger.warning(f"Invalid ObjectId: {id_value}")
        return id_value


async def fetch_from_nse(symbol: str, retries: int = 3, delay: float = 1.5):
    """
    Fetch 15m intraday candles for the current day using NSE API with retries.
    Returns a DataFrame with ['Datetime','Open','High','Low','Close','Volume'].
    """
    url = f"https://www.nseindia.com/api/chart-databyindex?index={symbol}&indices=false&interval=15minute"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Referer": "https://www.nseindia.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for attempt in range(1, retries + 1):
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                # Initial request to get NSE cookies
                async with session.get("https://www.nseindia.com", timeout=10) as _:
                    pass

                # Fetch the intraday 15m data
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        json_data = await resp.json()
                        candles = json_data.get("candles", [])
                        if not candles:
                            logger.info(f"No candles returned by NSE for {symbol}")
                            return None

                        df = pd.DataFrame(
                            candles,
                            columns=[
                                "timestamp",
                                "Open",
                                "High",
                                "Low",
                                "Close",
                                "Volume",
                            ],
                        )

                        # Convert timestamp (ms) → datetime IST
                        df["Datetime"] = pd.to_datetime(
                            df["timestamp"], unit="ms", utc=True
                        ).dt.tz_convert(ZoneInfo("Asia/Kolkata"))
                        df.set_index("Datetime", inplace=True)
                        df.drop(columns=["timestamp"], inplace=True)
                        df = df.sort_index()

                        # Only today's rows
                        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date()
                        df_today = df[pd.to_datetime(df.index).date == today_ist]

                        if df_today.empty:
                            logger.info(f"NSE returned no rows for today for {symbol}")
                            return None

                        return df_today

                    elif resp.status == 401:
                        logger.warning(
                            f"NSE API 401 for {symbol}, attempt {attempt}/{retries}"
                        )
                    else:
                        logger.warning(
                            f"NSE API returned {resp.status} for {symbol}, attempt {attempt}/{retries}"
                        )

        except Exception as e:
            logger.warning(
                f"NSE fetch error for {symbol}, attempt {attempt}/{retries}: {e}"
            )

        await asyncio.sleep(delay)  # wait before retry

    logger.info(f"NSE fetch failed for {symbol} after {retries} attempts")
    return None


async def fetch_intraday_15m_for_today(symbol, lookback_days=3):
    """
    Try NSE API first (retry-safe). If unavailable, fallback to yfinance 15m data.
    """
    df = await fetch_from_nse(symbol)
    if df is not None and not df.empty:
        logger.info(f"Fetched {len(df)} rows for {symbol} from NSE API.")
        return df

    logger.info(f"Falling back to yfinance for {symbol}...")
    try:
        data = yf.download(
            f"{symbol}.NS",
            period=f"{lookback_days}d",
            interval="15m",
            progress=False,
            auto_adjust=False,
        )

        if data.empty:
            logger.warning(f"No 15m data returned for {symbol} (yfinance fallback).")
            return None

        # Fix timezone
        if data.index.tz is None:
            data.index = data.index.tz_localize("UTC").tz_convert(
                ZoneInfo("Asia/Kolkata")
            )
        else:
            data.index = data.index.tz_convert(ZoneInfo("Asia/Kolkata"))

        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        dates = pd.to_datetime(data.index).date
        data_today = data[dates == today_ist]

        if data_today.empty:
            last_day = dates[-1]
            logger.info(f"No data for today; using last available day {last_day}")
            data_today = data[dates == last_day]

        return data_today.sort_index()

    except Exception as e:
        logger.error(f"Error fetching 15m data from yfinance for {symbol}: {e}")
        return None
