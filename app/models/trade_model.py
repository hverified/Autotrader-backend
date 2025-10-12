# app/models/trade_model.py
from pydantic import BaseModel
from typing import Optional


class Trade(BaseModel):
    id: str
    stock_name: str
    symbol: str
    bsecode: Optional[str]
    per_chg: Optional[float]
    close: Optional[float]
    volume: Optional[int]
    status: str  # shortlisted | bought | to_sell | sold
    shortlisted_date: str
    buy_price: Optional[float] = None
    buy_date: Optional[str] = None
    sell_price: Optional[float] = None
    sell_date: Optional[str] = None
    quantity: Optional[int] = None


class StockSymbol(BaseModel):
    symbol: str
