import requests
from app.utils.helpers import generate_id, current_date
from app.utils.logger import logger
from app.config import settings
from bs4 import BeautifulSoup

def scrape_chartink():
    """
    Scrape Chartink screener via POST request with CSRF token and session.
    Stores extra fields: per_chg, volume, bsecode
    """
    session = requests.Session()

    # Step 1: GET request to fetch CSRF token and cookies
    try:
        get_resp = session.get(settings.CHARTINK_URL, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": settings.CHARTINK_URL
        })
        if get_resp.status_code != 200:
            logger.error(f"Failed initial GET: {get_resp.status_code}")
            return []

        # CSRF token is in meta tag
        soup = BeautifulSoup(get_resp.text, "html.parser")
        csrf_meta = soup.find("meta", {"name": "csrf-token"})
        csrf_token = csrf_meta.get("content") if csrf_meta else None

        if not csrf_token:
            logger.error("CSRF token not found on Chartink page")
            return []

    except Exception as e:
        logger.error(f"Error fetching CSRF token: {e}")
        return []

    # Step 2: POST request to fetch screener data
    payload = {
        "scan_clause": settings.CHARTINK_SCAN_CLAUSE
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": settings.CHARTINK_URL,
        "User-Agent": "Mozilla/5.0",
        "X-CSRF-Token": csrf_token
    }

    try:
        post_resp = session.post(
            "https://chartink.com/screener/process",
            data=payload,
            headers=headers
        )
        if post_resp.status_code != 200:
            logger.error(f"Failed POST request: {post_resp.status_code}")
            return []

        data = post_resp.json()
        stocks = []

        for row in data.get("data", []):
            stock = {
                "id": generate_id(),
                "stock_name": row.get("name"),
                "symbol": row.get("nsecode"),
                "bsecode": row.get("bsecode"),
                "per_chg": row.get("per_chg"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "status": "shortlisted",
                "shortlisted_date": current_date(),
            }
            stocks.append(stock)

        logger.info(f"Scraped {len(stocks)} stocks from Chartink successfully")
        return stocks

    except Exception as e:
        logger.error(f"Error fetching or parsing screener data: {e}")
        return []
