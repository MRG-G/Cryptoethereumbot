# utils/pricing.py
import aiohttp
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional
from decimal import Decimal, ROUND_DOWN
import json

log = logging.getLogger("pricing")

# Fallback цены на случай, если все API недоступны
FALLBACK = {"BTC": Decimal("55832.25"), "ETH": Decimal("3433.91"), "USDT": Decimal("1")}

# Кэш цен и lock для асинхронной безопасности
price_cache = {
    "last_update": None,
    "prices": None
}
price_cache_lock = asyncio.Lock()

# Безопасный импорт конфигурации
try:
    from config import BINANCE_API_KEY, BINANCE_API_SECRET, COINGECKO_API_KEY
except Exception:
    BINANCE_API_KEY = ""
    BINANCE_API_SECRET = ""
    COINGECKO_API_KEY = ""

# Конфигурация API
BINANCE_URLS = {
    "BTC": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    "ETH": "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT"
}

COINGECKO_URLS = {
    "BTC": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
    "ETH": "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
}

# Заголовки для API запросов
BINANCE_HEADERS = {"X-MBX-APIKEY": BINANCE_API_KEY} if BINANCE_API_KEY else {}
COINGECKO_HEADERS = {"x-cg-pro-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}

# Попытка использовать requests, иначе urllib
try:
    import requests
except Exception:
    requests = None
    import urllib.request as _urllib

def _fetch_price_coingecko(asset_id: str) -> Optional[Decimal]:
    """Синхронный fetch цены с Coingecko (fallback на None при ошибке)."""
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={asset_id}&vs_currencies=usd"
    try:
        if requests:
            r = requests.get(url, timeout=5, headers=COINGECKO_HEADERS or None)
            r.raise_for_status()
            data = r.json()
        else:
            with _urllib.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
        value = data.get(asset_id, {}).get("usd")
        if value is None:
            return None
        return Decimal(str(value))
    except Exception as e:
        log.debug("Coingecko sync fetch failed for %s: %s", asset_id, e)
        return None

# Простой маппинг и fallback цены
_ASSET_MAP = {
    "ETH": "ethereum",
    "BTC": "bitcoin",
    "USDT": "tether"
}

_FIXED_PRICES = {
    "ETH": Decimal("1800"),  # USD за 1 ETH (fallback)
    "BTC": Decimal("30000"),
    "USDT": Decimal("1")
}

FEE_PERCENT = Decimal("0.03")  # 3%
ROUND_QUANT = Decimal("0.01")

def get_price(asset: str) -> Decimal:
    """Синхронный доступ к цене (пытается Coingecko sync, иначе фикс. Возвращает Decimal)."""
    asset = (asset or "").upper()
    asset_id = _ASSET_MAP.get(asset)
    if not asset_id:
        return Decimal("0")
    price = _fetch_price_coingecko(asset_id)
    if price is None:
        price = _FIXED_PRICES.get(asset, FALLBACK.get(asset, Decimal("0")))
    # Нормализуем до 2 знаков (USD)
    try:
        return price.quantize(ROUND_QUANT, rounding=ROUND_DOWN)
    except Exception:
        return Decimal(str(price))

def calculate_settlement(asset: str, amount_crypto) -> dict:
    """
    amount_crypto: Decimal или числовая строка
    Возвращает словарь:
    {
     'asset': 'ETH',
     'amount_crypto': Decimal(...),
     'price_usd': Decimal(...),
     'total_usd': Decimal(...),
     'fee_usd': Decimal(...),         # комиссия — ваша польза
     'to_transfer_usd': Decimal(...), # сколько должен перевести оператор
    }
    """
    amount = Decimal(str(amount_crypto))
    price = get_price(asset)
    total = (amount * price).quantize(ROUND_QUANT, rounding=ROUND_DOWN)
    fee = (total * FEE_PERCENT).quantize(ROUND_QUANT, rounding=ROUND_DOWN)
    to_transfer = (total - fee).quantize(ROUND_QUANT, rounding=ROUND_DOWN)

    return {
        "asset": (asset or "UNKNOWN").upper(),
        "amount_crypto": amount,
        "price_usd": price,
        "total_usd": total,
        "fee_usd": fee,
        "to_transfer_usd": to_transfer,
    }

async def fetch_binance_prices() -> Dict[str, float]:
    """Получение цен с Binance"""
    out = {}
    timeout = aiohttp.ClientTimeout(total=6)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=BINANCE_HEADERS) as session:
            for sym, url in BINANCE_URLS.items():
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            # безопасность: data может содержать price
                            price = data.get("price") or data.get("lastPrice")
                            if price is not None:
                                out[sym] = float(price)
                except Exception as e:
                    log.warning("Binance %s fetch failed: %s", sym, e)
        return out
    except Exception as e:
        log.warning("Binance session failed: %s", e)
        return {}

async def fetch_coingecko_prices() -> Dict[str, float]:
    """Получение цен с Coingecko"""
    symbol_to_id = {"BTC": "bitcoin", "ETH": "ethereum"}
    out = {}
    timeout = aiohttp.ClientTimeout(total=6)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=COINGECKO_HEADERS) as session:
            for sym, url in COINGECKO_URLS.items():
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            crypto_id = symbol_to_id.get(sym)
                            if crypto_id and data.get(crypto_id) and data[crypto_id].get("usd") is not None:
                                out[sym] = float(data[crypto_id]["usd"])
                except Exception as e:
                    log.warning("Coingecko %s fetch failed: %s", sym, e)
        return out
    except Exception as e:
        log.warning("Coingecko session failed: %s", e)
        return {}

def average_prices(prices_list: list[Dict[str, float]]) -> Dict[str, float]:
    """Усреднение цен из разных источников"""
    result = {}
    for symbol in ["BTC", "ETH"]:
        prices = [p[symbol] for p in prices_list if symbol in p]
        if prices:
            # Убираем экстремальные значения если больше 2 источников
            if len(prices) > 2:
                try:
                    prices.remove(max(prices))
                    prices.remove(min(prices))
                except ValueError:
                    pass
            result[symbol] = round(sum(prices) / len(prices), 4)
    return result

async def fetch_prices() -> Dict[str, float]:
    """Получение актуальных цен с кэшированием на 30 секунд"""
    global price_cache

    async with price_cache_lock:
        # Проверяем кэш
        if price_cache["last_update"] is not None:
            age = datetime.now() - price_cache["last_update"]
            if age < timedelta(seconds=30) and price_cache["prices"] is not None:
                return price_cache["prices"]

        # Получаем цены из всех источников параллельно
        prices_list = await asyncio.gather(
            fetch_binance_prices(),
            fetch_coingecko_prices()
        )

        # Фильтруем пустые результаты
        prices_list = [p for p in prices_list if p]

        if prices_list:
            # Усредняем цены из разных источников
            prices = average_prices(prices_list)

            # Обновляем кэш
            price_cache["last_update"] = datetime.now()
            price_cache["prices"] = prices

            return prices
        else:
            # Если все API недоступны, используем резервные цены
            log.warning("All price sources failed. Using fallback prices.")
            fallback = {k: float(v) for k, v in FALLBACK.items()}
            price_cache["last_update"] = datetime.now()
            price_cache["prices"] = fallback
            return fallback

async def warm_cache():
    """Явно прогреть кэш цен (можно вызвать при старте бота)."""
    try:
        await fetch_prices()
        log.info("Price cache warmed")
    except Exception as e:
        log.warning("Warm cache failed: %s", e)

async def get_price_async(asset: str) -> Decimal:
    """Асинхронно получить цену в Decimal, используя кэш и агрегаторы."""
    asset = (asset or "").upper()
    if asset not in _ASSET_MAP:
        return Decimal("0")
    try:
        prices = await fetch_prices()
        # prices содержит float для BTC/ETH; для USDT используем 1
        if asset == "USDT":
            return Decimal("1.00")
        price = prices.get(asset)
        if price is None:
            # fallback
            return _FIXED_PRICES.get(asset, FALLBACK.get(asset, Decimal("0")))
        return Decimal(str(price)).quantize(ROUND_QUANT, rounding=ROUND_DOWN)
    except Exception as e:
        log.debug("get_price_async failed for %s: %s", asset, e)
        return _FIXED_PRICES.get(asset, FALLBACK.get(asset, Decimal("0")))
