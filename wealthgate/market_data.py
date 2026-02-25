"""Market data fetching with yfinance and mock fallback."""

import logging
from typing import Optional

from .mock_data import MOCK_PRICES

logger = logging.getLogger(__name__)

_price_cache: dict[str, float] = {}


async def get_price(symbol: str) -> float:
    """Get current price for a symbol. Tries yfinance first, falls back to mock."""
    if symbol in _price_cache:
        return _price_cache[symbol]

    price = await _fetch_live_price(symbol)
    if price is None:
        price = MOCK_PRICES.get(symbol, 0.0)
        if price == 0.0:
            logger.warning(f"No price data available for {symbol}")

    _price_cache[symbol] = price
    return price


async def _fetch_live_price(symbol: str) -> Optional[float]:
    """Attempt to fetch live price via yfinance."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        if price and price > 0:
            return round(float(price), 2)

        # Fallback: try history
        hist = ticker.history(period="1d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)

        return None
    except Exception as e:
        logger.debug(f"yfinance failed for {symbol}: {e}")
        return None


async def get_prices(symbols: list[str]) -> dict[str, float]:
    """Get prices for multiple symbols."""
    prices = {}
    for symbol in symbols:
        prices[symbol] = await get_price(symbol)
    return prices


def clear_cache():
    """Clear the price cache."""
    _price_cache.clear()
