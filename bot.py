import asyncio
from datetime import datetime
import sqlite3
import aiohttp
import logging

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters, CallbackQueryHandler
)

# ====== CONFIG ======
TOKEN = "8298425629:AAGJzSFg_SHT_HjEPA1OTzJnXHRdPw51T10"  # <- замени на свой токен
CHANNEL_USERNAME = "@ethereumamoperator"                  # канал операторов
MERCHANT_USDT_ADDRESS = "0xYourUSDT_ERC20_Address_Here"   # <- замени на свой адрес USDT-ERC20

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("exchange_bot")

# Интеграции
ENABLE_SQLITE = True
ENABLE_GOOGLE_SHEETS = False  # включи True и укажи креды, если нужно

# Google Sheets (по желанию)
GOOGLE_SHEETS_JSON_PATH = "./service_account.json"
GOOGLE_SHEET_NAME = "ExchangeBot_Orders"

# ====== STATES ======
LANGUAGE, ACTION, PICK_ASSET, ENTER_AMOUNT, ENTER_WALLET, AWAITING_CHECK = range(6)

# ====== LANG MAP и ТЕКСТЫ ======
language_map = {
    "🇷🇺 Русский": "Русский",
    "🇦🇲 Հայերեն": "Հայերեն",
    "🇬🇧 English": "English"
}

# Тексты (RU / AM / EN) — сокращённо, но включают все нужные строки
texts = {
    "Русский": {
        "brand": "💎 Ethereum платформа",
        "start_banner": (
            "💎 Ethereum платформа\n\n"
            "📊 Текущие курсы / Ընթացիկ փոխարժեքներ / Current rates:\n"
            "🟧 BTC: {btc:.2f} USDT | 💎 ETH: {eth:.2f} USDT\n"
            "💵 USDT-ERC20 only\n"
            "⚠️ Комиссия: 3% (покупка +, продажа −)\n\n"
            "Выберите язык / Խնդրում ենք ընտրել լեզուն / Please select a language:"
        ),
        "rates_block_header": "⏱ Курс — Обновляется в Реальном Времени",
        "rates_block_footer": "Источник: Binance + exchangerate.host (CBA-подобный курс)",
        "rates": (
            "📊 Курсы криптовалют:\n"
            "₿ BTC: {btc:.2f} USDT\n"
            "💎 ETH: {eth:.2f} USDT\n"
            "💵 USDT: {usdt_amd:.2f} AMD\n\n"
            "⚠️ Комиссия: всего 3% — ниже рынка и покрывает безопасность и скорость."
        ),
        "info": "Выберите действие:",
        "buttons": [["💰 Купить BTC/ETH", "💸 Продать BTC/ETH"], ["⬅️ Назад"]],
        "pick_asset": "Выберите актив: BTC или ETH.",
        "enter_amount_buy": "Введите количество {asset}, которое хотите купить (например 0.01):",
        "enter_amount_sell": "Введите количество {asset}, которое хотите продать (например 0.01):",
        "merchant_addr_title": "💳 Адрес для оплаты (USDT-ERC20):",
        "enter_wallet": "Укажите адрес вашего USDT-ERC20 для выплаты (начинается с 0x…):",
        "bad_wallet": "Неверный адрес. Должен начинаться с 0x и быть длиной 42 символа.",
        "send_check": "Теперь отправьте только фото/скриншот чека. Текст не принимается.",
        "only_photo": "На этом шаге принимается только фото/скриншот чека.",
        "after_check_wait": "✅ Чек получен. Ваша заявка передана оператору и ожидает подтверждения.",
        "calc_buy": (
            "✨ Желаемый объём: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Комиссия (3%): {fee:.2f} USDT\n\n"
            "📍 К оплате: {total:.2f} USDT-ERC20"
        ),
        "calc_sell": (
            "✨ Объём к продаже: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Комиссия (3%): {fee:.2f} USDT\n\n"
            "📍 К получению: {total:.2f} USDT-ERC20"
        ),
        "approved_user": (
            "✅ Ваша заявка одобрена.\n"
            "Актив: {asset}\n"
            "Количество: {asset_amount:.8f} {asset}\n"
            "Итог в USDT-ERC20: {usdt_total:.2f}"
        ),
        "auto_reject_user": (
            "❌ Ваша заявка отклонена.\n"
            "Причина: чек не видно / дата и время не сегодняшние / чек неверный.\n"
            "Пожалуйста, отправьте корректный чек (чёткое фото с актуальными датой/временем)."
        ),
        "channel_caption_buy": (
            "🟣 Покупка {asset}\n"
            "Пользователь: @{username}\n\n"
            "✨ Объём: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT ({price_time})\n"
            "💼 Комиссия (3%): {fee:.2f} USDT\n\n"
            "📍 К оплате: {total:.2f} USDT-ERC20\n"
            "Адрес оплаты: {wallet}\n\n{retry}Статус: Ожидает подтверждения"
        ),
        "channel_caption_sell": (
            "🔴 Продажа {asset}\n"
            "Пользователь: @{username}\n\n"
            "✨ Объём: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT ({price_time})\n"
            "💼 Комиссия (3%): {fee:.2f} USDT\n\n"
            "📍 К выплате: {total:.2f} USDT-ERC20\n"
            "Адрес клиента: {wallet}\n\n{retry}Статус: Ожидает подтверждения"
        ),
        "retry_label": "⚠️ Повторная отправка чека\n"
    },
    "Հայերեն": {
        "brand": "💎 Ethereum հարթակ",
        "start_banner": (
            "💎 Ethereum հարթակ\n\n"
            "📊 Ընթացիկ փոխարժեքներ:\n"
            "🟧 BTC: {btc:.2f} USDT | 💎 ETH: {eth:.2f} USDT\n"
            "💵 միայն USDT-ERC20\n"
            "⚠️ Միջնորդավճար 3%\n\n"
            "Խնդրում ենք ընտրել լեզուն:"
        ),
        "rates_block_header": "⏱ Ցուցանիշ — Արտնաժամկետ թարմացում",
        "rates_block_footer": "Առաջդիմություն: Binance + exchangerate.host",
        "rates": (
            "📊 Փոխարժեքներ:\n"
            "₿ BTC: {btc:.2f} USDT\n"
            "💎 ETH: {eth:.2f} USDT\n"
            "💵 USDT: {usdt_amd:.2f} AMD\n\n"
            "⚠️ Միջնորդավճար՝ 3% — ավելի ցածր քան շուկան։"
        ),
        "info": "Ընտրեք գործողությունը:",
        "buttons": [["💰 Գնել BTC/ETH", "💸 Վաճառել BTC/ETH"], ["⬅️ Վերադառնալ"]],
        "pick_asset": "Ընտրեք ակտիվ՝ BTC կամ ETH։",
        "enter_amount_buy": "Մուտքագրեք {asset}-ի քանակը (օր. 0.01):",
        "enter_amount_sell": "Մուտքագրեք {asset}-ի քանակը (օր. 0.01):",
        "merchant_addr_title": "💳 Վճարումների հասցե (USDT-ERC20):",
        "enter_wallet": "Ներբեռնեք ձեր USDT-ERC20 հասցեն (սկսվում է 0x…):",
        "bad_wallet": "Սխալ հասցե․ պետք է սկսվի 0x-ով և ունենա 42 նիշ։",
        "send_check": "Խնդրում ենք ուղարկել միայն լուսանկար/սքրինշոթ։",
        "only_photo": "Այս փուլում ընդունվում է միայն լուսանկար/սքրինշոթ։",
        "after_check_wait": "✅ Ստուգումը ստացվեց։ Ձեր հայտը սպասում է հաստատմանը։",
        "calc_buy": (
            "✨ Քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Գումար՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT ({price_time})\n"
            "💼 Միջնորդավճար (3%): {fee:.2f} USDT\n\n"
            "📍 Վճարման համար՝ {total:.2f} USDT-ERC20"
        ),
        "calc_sell": (
            "✨ Վաճառքի քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Գումար՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT ({price_time})\n"
            "💼 Միջնորդավճար (3%): {fee:.2f} USDT\n\n"
            "📍 Ստանալու համար՝ {total:.2f} USDT-ERC20"
        ),
        "approved_user": (
            "✅ Ձեր հայտը հաստատվել է։\n"
            "Ակտիվ՝ {asset}\n"
            "Քանակ՝ {asset_amount:.8f} {asset}\n"
            "USDT-ERC20՝ {usdt_total:.2f}"
        ),
        "auto_reject_user": (
            "❌ Ձեր հայտը մերժվել է։\n"
            "Պատճառը՝ չեկը չի երևում / ամսաթիվը ճիշտ չէ / չեկը սխալ է։\n"
            "Խնդրում ենք ուղարկել ճիշտ լուսանկար՝ ընթացիկ ամսաթվով/ժամով։"
        ),
        "channel_caption_buy": (
            "🟣 Գնում {asset}\n"
            "Օգտատեր՝ @{username}\n\n"
            "✨ Քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Արժեք՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT ({price_time})\n"
            "💼 Միջնորդավճար (3%): {fee:.2f} USDT\n\n"
            "📍 Վճարման համար՝ {total:.2f} USDT-ERC20\n"
            "Վճարային հասցե՝ {wallet}\n\n{retry}Կարգավիճակ՝ Սպասում է հաստատման"
        ),
        "channel_caption_sell": (
            "🔴 Վաճառք {asset}\n"
            "Օգտատեր՝ @{username}\n\n"
            "✨ Քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Արժեք՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT ({price_time})\n"
            "💼 Միջնորդավճար (3%): {fee:.2f} USDT\n\n"
            "📍 Կստանաք՝ {total:.2f} USDT-ERC20\n"
            "Հաճախորդի հասցե՝ {wallet}\n\n{retry}Կարգավիճակ՝ Սպասում է հաստատման"
        ),
        "retry_label": "⚠️ Կրկնակի ստուգում\n"
    },
    "English": {
        "brand": "💎 Ethereum Platform",
        "start_banner": (
            "💎 Ethereum Platform\n\n"
            "📊 Current rates:\n"
            "🟧 BTC: {btc:.2f} USDT | 💎 ETH: {eth:.2f} USDT\n"
            "💵 USDT-ERC20 only\n"
            "⚠️ Fee: 3% (buy +, sell −)\n\n"
            "Please select a language:"
        ),
        "rates_block_header": "⏱ Live Rates (Real-Time)",
        "rates_block_footer": "Source: Binance + exchangerate.host",
        "rates": (
            "📊 Live rates:\n"
            "₿ BTC: {btc:.2f} USDT\n"
            "💎 ETH: {eth:.2f} USDT\n"
            "💵 USDT: {usdt_amd:.2f} AMD\n\n"
            "⚠️ Fee: only 3% — lower than many exchangers."
        ),
        "info": "Choose an action:",
        "buttons": [["💰 Buy BTC/ETH", "💸 Sell BTC/ETH"], ["⬅️ Back"]],
        "pick_asset": "Choose asset: BTC or ETH.",
        "enter_amount_buy": "Enter the amount of {asset} you want to buy (e.g., 0.01):",
        "enter_amount_sell": "Enter the amount of {asset} you want to sell (e.g., 0.01):",
        "merchant_addr_title": "💳 Payment address (USDT-ERC20):",
        "enter_wallet": "Provide your USDT-ERC20 address for payout (starts with 0x…):",
        "bad_wallet": "Invalid address. Must start with 0x and be 42 chars long.",
        "send_check": "Now send a photo/screenshot of the receipt only. Text is not accepted.",
        "only_photo": "Only photo/screenshot is accepted at this step.",
        "after_check_wait": "✅ Receipt received. Your request has been forwarded to an operator for approval.",
        "calc_buy": (
            "✨ Desired amount: {asset_amount:.8f} {asset}\n"
            "💳 Subtotal: {base:.2f} USDT\n"
            "Rate: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Fee (3%): {fee:.2f} USDT\n\n"
            "📍 Amount to send: {total:.2f} USDT-ERC20"
        ),
        "calc_sell": (
            "✨ Amount to sell: {asset_amount:.8f} {asset}\n"
            "💳 Subtotal: {base:.2f} USDT\n"
            "Rate: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Fee (3%): {fee:.2f} USDT\n\n"
            "📍 You will receive: {total:.2f} USDT-ERC20"
        ),
        "approved_user": (
            "✅ Your request has been approved.\n"
            "Asset: {asset}\n"
            "Amount: {asset_amount:.8f} {asset}\n"
            "USDT-ERC20 total: {usdt_total:.2f}"
        ),
        "auto_reject_user": (
            "❌ Your request was rejected.\n"
            "Reason: receipt not visible / not today's date & time / invalid receipt.\n"
            "Please send a correct, clear receipt with current date/time."
        ),
        "channel_caption_buy": (
            "🟣 Buy {asset}\n"
            "User: @{username}\n\n"
            "✨ Amount: {asset_amount:.8f} {asset}\n"
            "💳 Subtotal: {base:.2f} USDT\n"
            "Rate: {price:.2f} USDT ({price_time})\n"
            "💼 Fee (3%): {fee:.2f} USDT\n\n"
            "📍 Total to pay: {total:.2f} USDT-ERC20\n"
            "Payment address: {wallet}\n\n{retry}Status: Waiting for approval"
        ),
        "channel_caption_sell": (
            "🔴 Sell {asset}\n"
            "User: @{username}\n\n"
            "✨ Amount: {asset_amount:.8f} {asset}\n"
            "💳 Subtotal: {base:.2f} USDT\n"
            "Rate: {price:.2f} USDT ({price_time})\n"
            "💼 Fee (3%): {fee:.2f} USDT\n\n"
            "📍 To receive: {total:.2f} USDT-ERC20\n"
            "Client address: {wallet}\n\n{retry}Status: Waiting for approval"
        ),
        "retry_label": "⚠️ Retry receipt\n"
    }
}

# ====== STORAGE (pending requests) ======
pending = {}  # channel_msg_id -> request dict

# ====== DB / Google Sheets helpers ======
def init_sqlite():
    if not ENABLE_SQLITE:
        return
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            flow TEXT,
            asset TEXT,
            asset_amount REAL,
            base_usdt REAL,
            fee_usdt REAL,
            total_usdt REAL,
            username TEXT,
            user_id INTEGER,
            wallet TEXT,
            status TEXT
        );
    """)
    conn.commit()
    conn.close()

def log_to_sqlite(row: dict):
    if not ENABLE_SQLITE:
        return
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (ts, flow, asset, asset_amount, base_usdt, fee_usdt, total_usdt,
                            username, user_id, wallet, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        row.get("ts"), row.get("flow"), row.get("asset"), row.get("asset_amount"),
        row.get("base_usdt"), row.get("fee_usdt"), row.get("total_usdt"),
        row.get("username"), row.get("user_id"), row.get("wallet"), row.get("status")
    ))
    conn.commit()
    conn.close()

def log_request(row: dict):
    log_to_sqlite(row)
    # Google Sheets optional (not implemented here unless ENABLE_GOOGLE_SHEETS=True)

# ====== PRICE FETCH (Binance + exchangerate.host) ======
async def fetch_prices_and_rate():
    """
    Возвращает dict: { 'BTC': float, 'ETH': float, 'usdt_amd': float, 'time': str }
    BTC/ETH цены берутся с Binance (в USDT).
    USDT->AMD берётся через exchangerate.host (USD->AMD), т.к. USDT ~ USD.
    """
    result = {}
    timeout = aiohttp.ClientTimeout(total=6)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Binance prices
            binance_urls = {
                "BTC": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
                "ETH": "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
            }
            for sym, url in binance_urls.items():
                async with session.get(url) as r:
                    j = await r.json()
                    result[sym] = float(j.get("price", 0.0))
            # exchangerate.host USD -> AMD
            # use latest endpoint: https://api.exchangerate.host/latest?base=USD&symbols=AMD
            async with session.get("https://api.exchangerate.host/latest?base=USD&symbols=AMD") as r2:
                j2 = await r2.json()
                rate = j2.get("rates", {}).get("AMD")
                if rate:
                    result["usdt_amd"] = float(rate)
                else:
                    result["usdt_amd"] = None
            result["time"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    except Exception as e:
        logger.warning(f"Price fetch failed: {e}")
        # fallback
        result["BTC"] = 55832.25
        result["ETH"] = 3433.91
        result["usdt_amd"] = 389.5
        result["time"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return result

# ====== HELPERS ======
def build_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(texts[lang]["buttons"], resize_keyboard=True)

def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "Русский")

def parse_float(s: str):
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None

async def send_language_prompt_only(user_id_or_update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🇷🇺 Русский"], ["🇦🇲 Հայերեն"], ["🇬🇧 English"]]
    prompt = texts["Русский"]["start_banner"].split("\n\n")[-1]  # last part contains select language text
    if isinstance(user_id_or_update, Update):
        await user_id_or_update.effective_chat.send_message(
            prompt,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
    else:
        await context.bot.send_message(
            chat_id=user_id_or_update,
            text=prompt,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )

def premium_course_block(lang_key: str, btc: float, eth: float, usdt_amd: float, price_time: str) -> str:
    # build premium (colored-frame) block per chosen language
    header = texts[lang_key].get("rates_block_header", "⏱ Live Rates")
    footer = texts[lang_key].get("rates_block_footer", "")
    if lang_key == "Русский":
        body = texts[lang_key]["rates"].format(btc=btc, eth=eth, usdt_amd=usdt_amd)
    elif lang_key == "Հայերեն":
        body = texts[lang_key]["rates"].format(btc=btc, eth=eth, usdt_amd=usdt_amd)
    else:
        body = texts[lang_key]["rates"].format(btc=btc, eth=eth, usdt_amd=usdt_amd)
    block = (
        f"🟦┌──────────────────────────────────────🟦\n"
        f"│ {header}\n"
        f"│\n"
        f"{body}\n\n"
        f"│ {footer}\n"
        f"🟦└──────────────────────────────────────🟦"
    )
    return block

# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = await fetch_prices_and_rate()
    btc = prices["BTC"]; eth = prices["ETH"]; usdt_amd = prices.get("usdt_amd") or 0.0
    banner = texts["Русский"]["start_banner"].format(btc=btc, eth=eth)
    keyboard = [["🇷🇺 Русский"], ["🇦🇲 Հայերեն"], ["🇬🇧 English"]]
    msg = await update.message.reply_text(
        banner,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    context.user_data["start_msg_id"] = msg.message_id
    return LANGUAGE

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = language_map.get(update.message.text)
    if not lang:
        await update.message.reply_text(texts["Русский"]["start_banner"].split("\n\n")[-1])
        return LANGUAGE
    context.user_data["lang"] = lang
    context.user_data["attempt"] = 0
    # delete start message if present
    try:
        start_msg_id = context.user_data.get("start_msg_id")
        if start_msg_id:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg_id)
    except Exception:
        pass
    # show only rates block + menu (no greeting)
    prices = await fetch_prices_and_rate()
    btc = prices["BTC"]; eth = prices["ETH"]; usdt_amd = prices.get("usdt_amd") or 0.0
    price_time = prices.get("time", "")
    block = premium_course_block(lang, btc, eth, usdt_amd, price_time)
    await update.message.reply_text(block)
    await update.message.reply_text(texts[lang]["info"], reply_markup=build_kb(lang))
    return ACTION

async def action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    txt = (update.message.text or "").strip()
    # if user pressed buy/sell - show rates block (premium) then proceed
    if ("Купить" in txt) or ("Buy" in txt) or ("Գնել" in txt):
        context.user_data["flow"] = "buy"
        # show rates in premium style
        prices = await fetch_prices_and_rate()
        block = premium_course_block(lang, prices["BTC"], prices["ETH"], prices.get("usdt_amd") or 0.0, prices.get("time",""))
        await update.message.reply_text(block)
        await update.message.reply_text(texts[lang]["pick_asset"], reply_markup=ReplyKeyboardRemove())
        return PICK_ASSET

    if ("Продать" in txt) or ("Sell" in txt) or ("Վաճառել" in txt):
        context.user_data["flow"] = "sell"
        prices = await fetch_prices_and_rate()
        block = premium_course_block(lang, prices["BTC"], prices["ETH"], prices.get("usdt_amd") or 0.0, prices.get("time",""))
        await update.message.reply_text(block)
        await update.message.reply_text(texts[lang]["pick_asset"], reply_markup=ReplyKeyboardRemove())
        return PICK_ASSET

    if ("⬅️" in txt) or ("Back" in txt) or ("Վերադառնալ" in txt):
        return await start(update, context)

    await update.message.reply_text(texts[lang]["info"], reply_markup=build_kb(lang))
    return ACTION

async def pick_asset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    asset = (update.message.text or "").upper().strip()
    if asset not in ("BTC", "ETH"):
        await update.message.reply_text(texts[lang]["pick_asset"])
        return PICK_ASSET
    context.user_data["asset"] = asset
    # show rates again (brief) after choosing asset
    prices = await fetch_prices_and_rate()
    price = prices.get(asset)
    price_time = prices.get("time","")
    # build brief info + continue
    if context.user_data.get("flow") == "buy":
        await update.message.reply_text(texts[lang]["enter_amount_buy"].format(asset=asset))
    else:
        await update.message.reply_text(texts[lang]["enter_amount_sell"].format(asset=asset))
    return ENTER_AMOUNT

async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    amount = parse_float(update.message.text or "")
    if not amount or amount <= 0:
        asset = context.user_data.get("asset", "BTC")
        if context.user_data.get("flow") == "buy":
            await update.message.reply_text(texts[lang]["enter_amount_buy"].format(asset=asset))
        else:
            await update.message.reply_text(texts[lang]["enter_amount_sell"].format(asset=asset))
        return ENTER_AMOUNT

    context.user_data["asset_amount"] = amount
    asset = context.user_data.get("asset", "BTC")
    prices = await fetch_prices_and_rate()
    price = prices.get(asset, 0.0)
    price_time = prices.get("time","")
    base = amount * price
    fee = base * 0.03
    if context.user_data.get("flow") == "buy":
        total = base + fee
        context.user_data["calc"] = {"base": base, "fee": fee, "total": total, "price": price, "price_time": price_time}
        calc_text = texts[lang]["calc_buy"].format(
            asset=asset, asset_amount=amount, price=price, base=base, fee=fee, total=total, price_time=price_time
        )
        await update.message.reply_text(calc_text)
        # show merchant address for payment (no copy button)
        await update.message.reply_text(f"{texts[lang]['merchant_addr_title']}\n`{MERCHANT_USDT_ADDRESS}`", parse_mode="Markdown")
        await update.message.reply_text(texts[lang]["send_check"])
        context.user_data["wallet"] = MERCHANT_USDT_ADDRESS
        return AWAITING_CHECK
    else:
        total = base - fee
        context.user_data["calc"] = {"base": base, "fee": fee, "total": total, "price": price, "price_time": price_time}
        calc_text = texts[lang]["calc_sell"].format(
            asset=asset, asset_amount=amount, price=price, base=base, fee=fee, total=total, price_time=price_time
        )
        await update.message.reply_text(calc_text)
        await update.message.reply_text(texts[lang]["enter_wallet"])
        return ENTER_WALLET

def _basic_eth_format(addr: str) -> bool:
    return isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42 and all(c in "0123456789abcdefABCDEF" for c in addr[2:])

def is_checksum_address(addr: str) -> bool:
    # мягкая проверка (без eth-utils)
    return _basic_eth_format(addr)

async def enter_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    wallet = (update.message.text or "").strip()
    if not is_checksum_address(wallet):
        await update.message.reply_text(texts[lang]["bad_wallet"])
        await update.message.reply_text("ℹ️ Для строгой проверки установите пакет: pip install eth-utils")
        return ENTER_WALLET
    context.user_data["wallet"] = wallet
    await update.message.reply_text(texts[lang]["send_check"])
    return AWAITING_CHECK

async def receive_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    # only accept photos
    if not update.message.photo:
        await update.message.reply_text(texts[lang]["only_photo"])
        return AWAITING_CHECK

    # attempt counter
    context.user_data["attempt"] = context.user_data.get("attempt", 0) + 1
    is_retry = context.user_data["attempt"] > 1

    photo_id = update.message.photo[-1].file_id
    u = context.user_data
    flow = u.get("flow")
    asset = u.get("asset")
    asset_amount = u.get("asset_amount", 0.0)
    base = u.get("calc", {}).get("base", 0.0)
    fee = u.get("calc", {}).get("fee", 0.0)
    total = u.get("calc", {}).get("total", 0.0)
    price = u.get("calc", {}).get("price", 0.0)
    price_time = u.get("calc", {}).get("price_time", "")
    username = update.effective_user.username or update.effective_user.first_name
    wallet = u.get("wallet")
    retry_note = texts[lang]["retry_label"] if is_retry else ""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="approve"),
         InlineKeyboardButton("❌ Отклонить", callback_data="reject")]
    ])

    if flow == "buy":
        caption = texts[lang]["channel_caption_buy"].format(
            asset=asset, username=username, asset_amount=asset_amount,
            base=base, fee=fee, total=total, wallet=wallet, retry=retry_note,
            price=price, price_time=price_time
        )
    else:
        caption = texts[lang]["channel_caption_sell"].format(
            asset=asset, username=username, asset_amount=asset_amount,
            base=base, fee=fee, total=total, wallet=wallet, retry=retry_note,
            price=price, price_time=price_time
        )

    sent = await context.bot.send_photo(
        chat_id=CHANNEL_USERNAME,
        photo=photo_id,
        caption=caption,
        reply_markup=keyboard
    )

    # log request
    log_request({
        "ts": datetime.utcnow().isoformat(),
        "flow": flow,
        "asset": asset,
        "asset_amount": asset_amount,
        "base_usdt": base,
        "fee_usdt": fee,
        "total_usdt": total,
        "username": username,
        "user_id": update.effective_user.id,
        "wallet": wallet,
        "status": "pending"
    })

    # save pending for callback
    pending[sent.message_id] = {
        "lang": lang,
        "user_chat_id": update.effective_chat.id,
        "asset": asset,
        "asset_amount": asset_amount,
        "usdt_total": total,
        "wallet": wallet,
        "flow": flow,
        "photo_id": photo_id
    }

    await update.message.reply_text(texts[lang]["after_check_wait"])
    return ACTION

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg_id = query.message.message_id

    if msg_id not in pending:
        await query.answer("Заявка не найдена", show_alert=True)
        return

    pdata = pending.pop(msg_id)
    lang = pdata["lang"]
    user_id = pdata["user_chat_id"]

    # log status change
    log_request({
        "ts": datetime.utcnow().isoformat(),
        "flow": pdata["flow"],
        "asset": pdata["asset"],
        "asset_amount": pdata["asset_amount"],
        "base_usdt": None,
        "fee_usdt": None,
        "total_usdt": pdata["usdt_total"],
        "username": None,
        "user_id": user_id,
        "wallet": pdata["wallet"],
        "status": "approved" if query.data == "approve" else "rejected"
    })

    if query.data == "approve":
        # send simple approval to user (no operator name)
        await context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]["approved_user"].format(
                asset=pdata["asset"],
                asset_amount=pdata["asset_amount"],
                usdt_total=pdata["usdt_total"]
            )
        )
        new_caption = (query.message.caption or "") + "\n✅ Заявка подтверждена"
        await query.edit_message_caption(caption=new_caption, reply_markup=None)

    elif query.data == "reject":
        # send automatic reject message to user with reason template
        await context.bot.send_message(chat_id=user_id, text=texts[lang]["auto_reject_user"])
        # return user to language selection so he can retry
        await send_language_prompt_only(user_id, context)
        new_caption = (query.message.caption or "") + "\n❌ Отклонено"
        await query.edit_message_caption(caption=new_caption, reply_markup=None)

# ====== MAIN ======
def main():
    if ENABLE_SQLITE:
        init_sqlite()
    # Google Sheets init optional
    # if ENABLE_GOOGLE_SHEETS:
    #     init_google_sheets()

    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)],
            ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, action)],
            PICK_ASSET: [MessageHandler(filters.TEXT & ~filters.COMMAND, pick_asset)],
            ENTER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTER_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_wallet)],
            AWAITING_CHECK: [
                MessageHandler(filters.PHOTO, receive_check),
                MessageHandler(~filters.PHOTO & ~filters.COMMAND, receive_check),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_callback))

    print("✅ Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
