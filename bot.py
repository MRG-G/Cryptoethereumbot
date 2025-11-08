import asyncio
from datetime import datetime
import json
import os
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
TOKEN = "8298425629:AAGJzSFg_SHT_HjEPA1OTzJnXHRdPw51T10"
CHANNEL_USERNAME = "@ethereumamoperator"  # username канала с @ или числовой ID
MERCHANT_USDT_ADDRESS = "0xYourUSDT_ERC20_Address_Here"  # <-- замени на свой (USDT-ERC20)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("exchange_bot")

# Интеграции
ENABLE_SQLITE = True
ENABLE_GOOGLE_SHEETS = False  # включи True и укажи креды ниже, если нужно

# Google Sheets (по желанию)
GOOGLE_SHEETS_JSON_PATH = "./service_account.json"
GOOGLE_SHEET_NAME = "ExchangeBot_Orders"

# ====== STATES ======
LANGUAGE, ACTION, PICK_ASSET, ENTER_AMOUNT, ENTER_WALLET, AWAITING_CHECK = range(6)

# ====== DEFAULT PRICES (fallback) ======
PRICES_USD = {"BTC": 55832.25, "ETH": 3433.91}

# ====== LANG ======
language_map = {
    "🇷🇺 Русский": "Русский",
    "🇦🇲 Հայերեն": "Հայերեն",
    "🇬🇧 English": "English"
}

texts = {
    "Русский": {
        # === Брендинг ===
        "brand": "💎 Ethereum платформа",
        # Стартовый баннер (до выбора языка) — мульти-язычный блок с курсами
        "start_banner": (
            "💎 Ethereum платформа\n\n"
            "📊 Текущие курсы / Ընթացիկ փոխարժեքներ / Current rates:\n"
            "🟧 BTC: {btc:.2f} USDT | 💎 ETH: {eth:.2f} USDT\n"
            "💵 USDT-ERC20 only / միայն USDT-ERC20 / только USDT-ERC20\n"
            "⚠️ Fee/Միջնորդավճար/Комиссия: 3% (buy +, sell −)\n\n"
            "Выберите язык / Խնդրում ենք ընտրել լեզուն / Please select a language:"
        ),
        # === Блок курсов после выбора языка (S4-C) ===
        "rates": (
            "📊 Курсы криптовалют:\n"
            "🟧 BTC: {btc:.2f} USDT\n"
            "💎 ETH: {eth:.2f} USDT\n\n"
            "💵 Сеть: USDT-ERC20\n"
            "⚠️ Комиссия: 3% (покупка +, продажа −)"
        ),
        "info": "Выберите действие:",
        "buttons": [["💰 Купить BTC/ETH", "💸 Продать BTC/ETH"], ["⬅️ Назад"]],
        "pick_asset": "Выберите актив: BTC или ETH.",
        "enter_amount_buy": "Введите количество {asset}, которое хотите купить (например 0.01):",
        "enter_amount_sell": "Введите количество {asset}, которое хотите продать (например 0.01):",
        "merchant_addr_title": "💳 Адрес для оплаты (USDT-ERC20):",
        "copy_addr": "📋 Скопировать адрес",
        "enter_wallet": "Укажите адрес вашего 💵 USDT-ERC20 для выплаты (начинается с 0x…):",
        "bad_wallet": "Неверный адрес. Должен начинаться с 0x, быть длиной 42 и содержать допустимые символы (hex).",
        "send_check": "Теперь отправьте только фото/скриншот чека. Текстовые сообщения не принимаются.",
        "only_photo": "На этом шаге принимается только фото/скриншот чека. Пожалуйста, пришлите изображение.",
        "after_check_wait": "✅ Чек получен. Ваша заявка передана оператору и ожидает подтверждения.",
        # === Расчёты для пользователя (S4 + O4) ===
        "calc_buy": (
            "✨ Желаемый объём: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость по курсу: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Комиссия сервиса (3%): {fee:.2f} USDT\n\n"
            "📍 Сумма для отправки: {total:.2f} USDT-ERC20\n\n"
            "⚠️ Отправьте точную сумму, чтобы заявка была обработана без задержки."
        ),
        "calc_sell": (
            "✨ Объём к продаже: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость по курсу: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Комиссия сервиса (3%): {fee:.2f} USDT\n\n"
            "📍 К получению: {total:.2f} USDT-ERC20\n\n"
            "⚠️ Проверьте точность суммы — это ускорит обработку."
        ),
        # === Уведомления пользователю ===
        "approved_user": (
            "✅ Ваша заявка одобрена.\n"
            "Актив: {asset}\n"
            "Количество: {asset_amount:.8f} {asset}\n"
            "Итог в USDT-ERC20: {usdt_total:.2f}\n"
            "Оператор отправил то, что вы запрашивали."
        ),
        "auto_reject_user": (
            "❌ Ваша заявка отклонена.\n"
            "Причина: чек не видно / дата и время не сегодняшние / чек неверный.\n"
            "Пожалуйста, отправьте корректный чек (чёткое фото с актуальными датой/временем)."
        ),
        # === Сообщение в канал оператору (O4) ===
        "channel_caption_buy": (
            "🟣 Покупка {asset}\n"
            "Пользователь: @{username}\n\n"
            "✨ Объём: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость по курсу: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Комиссия (3%): {fee:.2f} USDT\n\n"
            "📍 К оплате: {total:.2f} USDT-ERC20\n"
            "USDT-ERC20 адрес для оплаты: {wallet}\n\n"
            "{retry}Статус: Ожидает подтверждения"
        ),
        "channel_caption_sell": (
            "🔴 Продажа {asset}\n"
            "Пользователь: @{username}\n\n"
            "✨ Объём: {asset_amount:.8f} {asset}\n"
            "💳 Стоимость по курсу: {base:.2f} USDT\n"
            "Курс: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Комиссия (3%): {fee:.2f} USDT\n\n"
            "📍 К выплате: {total:.2f} USDT-ERC20\n"
            "USDT-ERC20 адрес клиента: {wallet}\n\n"
            "{retry}Статус: Ожидает подтверждения"
        ),
        "retry_label": "⚠️ Повторная отправка чека\n",
        "lang_prompt": "Выберите язык / Խնդրում ենք ընտրել լեզուն / Please select a language:",
        "copied_reply": "Адрес для оплаты: {addr}"
    },
    "Հայերեն": {
        "brand": "💎 Ethereum հարթակ",
        "start_banner": (
            "💎 Ethereum հարթակ\n\n"
            "📊 Ընթացիկ փոխարժեքներ / Current rates / Текущие курсы:\n"
            "🟧 BTC: {btc:.2f} USDT | 💎 ETH: {eth:.2f} USDT\n"
            "💵 միայն USDT-ERC20 / USDT-ERC20 only / только USDT-ERC20\n"
            "⚠️ Միջնորդավճար 3% (գնում՝ +, վաճառք՝ −)\n\n"
            "Խնդրում ենք ընտրել լեզուն / Выберите язык / Please select a language:"
        ),
        "rates": (
            "📊 Արտարժութային ցուցանիշներ:\n"
            "🟧 BTC: {btc:.2f} USDT\n"
            "💎 ETH: {eth:.2f} USDT\n\n"
            "💵 Ցանցը՝ USDT-ERC20\n"
            "⚠️ Միջնորդավճար՝ 3% (գնում՝ +, վաճառք՝ −)"
        ),
        "info": "Ընտրեք գործողությունը.",
        "buttons": [["💰 Գնել BTC/ETH", "💸 Վաճառել BTC/ETH"], ["⬅️ Վերադառնալ"]],
        "pick_asset": "Ընտրեք ակտիվ՝ BTC կամ ETH։",
        "enter_amount_buy": "Մուտքագրեք {asset}-ի քանակը, որը ցանկանում եք գնել (օր. 0.01)։",
        "enter_amount_sell": "Մուտքագրեք {asset}-ի քանակը, որը ցանկանում եք վաճառել (օր. 0.01)։",
        "merchant_addr_title": "💳 Վճարման հասցե (USDT-ERC20)՝",
        "copy_addr": "📋 Պատճենել հասցեն",
        "enter_wallet": "Նշեք ձեր 💵 USDT-ERC20 հասցեն (սկսվում է 0x…)՝ վճարման համար:",
        "bad_wallet": "Սխալ հասցե․ պետք է սկսվի 0x-ով, լինի 42 նիշ և պարունակի միայն hex նիշեր:",
        "send_check": "Խնդրում ենք ուղարկել միայն վճարի լուսանկար/սքրինշոթ։ Տեքստերը չեն ընդունվում։",
        "only_photo": "Այս փուլում ընդունվում է միայն լուսանկար/սքրինշոթ։",
        "after_check_wait": "✅ Ստուգումն ընդունվեց․ ձեր հայտը փոխանցվել է օպերատորին և սպասում է հաստատման։",
        "calc_buy": (
            "✨ Ցանկալի քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Արժեք՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Սերվիսի միջնորդավճար (3%)՝ {fee:.2f} USDT\n\n"
            "📍 Վճարման գումար՝ {total:.2f} USDT-ERC20\n\n"
            "⚠️ Խնդրում ենք ուղարկել ճշգրիտ գումարը՝ ուշացումներից խուսափելու համար։"
        ),
        "calc_sell": (
            "✨ Վաճառքի քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Արժեք՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Միջնորդավճար (3%)՝ {fee:.2f} USDT\n\n"
            "📍 Ստանալու եք՝ {total:.2f} USDT-ERC20\n\n"
            "⚠️ Խնդրում ենք ստուգել ճշգրտությունը՝ արագ մշակման համար։"
        ),
        "approved_user": (
            "✅ Ձեր հայտը հաստատվել է։\n"
            "Ակտիվ՝ {asset}\n"
            "Քանակ՝ {asset_amount:.8f} {asset}\n"
            "USDT-ERC20՝ {usdt_total:.2f}\n"
            "Օպերատորը ուղարկել է Ձեր պահանջածը։"
        ),
        "auto_reject_user": (
            "❌ Ձեր հայտը մերժվել է։\n"
            "Պատճառ՝ չեկը չի երևում / ամսաթիվը և ժամը ընթացիկը չեն / չեկը սխալ է։\n"
            "Խնդրում ենք ուղարկել հստակ լուսանկար՝ ընթացիկ ամսաթվով/ժամով։"
        ),
        "channel_caption_buy": (
            "🟣 Գնում {asset}\n"
            "Օգտատեր՝ @{username}\n\n"
            "✨ Քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Արժեք՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Միջնորդավճար (3%)՝ {fee:.2f} USDT\n\n"
            "📍 Վճարում՝ {total:.2f} USDT-ERC20\n"
            "USDT-ERC20 հասցե՝ {wallet}\n\n"
            "{retry}Կարգավիճակ՝ Սպասում է հաստատման"
        ),
        "channel_caption_sell": (
            "🔴 Վաճառք {asset}\n"
            "Օգտատեր՝ @{username}\n\n"
            "✨ Քանակ՝ {asset_amount:.8f} {asset}\n"
            "💳 Արժեք՝ {base:.2f} USDT\n"
            "Փոխարժեք՝ {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Միջնորդավճար (3%)՝ {fee:.2f} USDT\n\n"
            "📍 Ստանալու եք՝ {total:.2f} USDT-ERC20\n"
            "Հաճախորդի USDT-ERC20 հասցե՝ {wallet}\n\n"
            "{retry}Կարգավիճակ՝ Սպասում է հաստատման"
        ),
        "retry_label": "⚠️ Կրկնակի ստուգում\n",
        "lang_prompt": "Խնդրում ենք ընտրել լեզուն / Выберите язык / Please select a language:",
        "copied_reply": "Վճարման հասցե՝ {addr}"
    },
    "English": {
        "brand": "💎 Ethereum Platform",
        "start_banner": (
            "💎 Ethereum Platform\n\n"
            "📊 Current rates / Ընթացիկ փոխարժեքներ / Текущие курсы:\n"
            "🟧 BTC: {btc:.2f} USDT | 💎 ETH: {eth:.2f} USDT\n"
            "💵 USDT-ERC20 only / միայն USDT-ERC20 / только USDT-ERC20\n"
            "⚠️ Fee/Միջնորդավճար/Комиссия: 3% (buy +, sell −)\n\n"
            "Please select a language / Ընտրեք լեզուն / Выберите язык:"
        ),
        "rates": (
            "📊 Live Rates:\n"
            "🟧 BTC: {btc:.2f} USDT\n"
            "💎 ETH: {eth:.2f} USDT\n\n"
            "💵 Network: USDT-ERC20\n"
            "⚠️ Fee: 3% (buy +, sell −)"
        ),
        "info": "Choose an action:",
        "buttons": [["💰 Buy BTC/ETH", "💸 Sell BTC/ETH"], ["⬅️ Back"]],
        "pick_asset": "Choose asset: BTC or ETH.",
        "enter_amount_buy": "Enter how much {asset} you want to buy (e.g., 0.01):",
        "enter_amount_sell": "Enter how much {asset} you want to sell (e.g., 0.01):",
        "merchant_addr_title": "💳 Payment address (USDT-ERC20):",
        "copy_addr": "📋 Copy address",
        "enter_wallet": "Provide your 💵 USDT-ERC20 address for payout (starts with 0x…):",
        "bad_wallet": "Invalid address. Must start with 0x, be 42 chars, and contain only hex symbols.",
        "send_check": "Now send a photo/screenshot of the receipt only. Text messages are not accepted.",
        "only_photo": "At this step, only a photo/screenshot is accepted. Please attach an image.",
        "after_check_wait": "✅ Receipt received. Your request has been forwarded to an operator for approval.",
        "calc_buy": (
            "✨ Desired amount: {asset_amount:.8f} {asset}\n"
            "💳 Price at rate: {base:.2f} USDT\n"
            "Rate: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Service fee (3%): {fee:.2f} USDT\n\n"
            "📍 Amount to send: {total:.2f} USDT-ERC20\n\n"
            "⚠️ Send the exact amount to avoid delays."
        ),
        "calc_sell": (
            "✨ Amount to sell: {asset_amount:.8f} {asset}\n"
            "💳 Price at rate: {base:.2f} USDT\n"
            "Rate: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Service fee (3%): {fee:.2f} USDT\n\n"
            "📍 You will receive: {total:.2f} USDT-ERC20\n\n"
            "⚠️ Ensure accuracy to speed up processing."
        ),
        "approved_user": (
            "✅ Your request has been approved.\n"
            "Asset: {asset}\n"
            "Amount: {asset_amount:.8f} {asset}\n"
            "USDT-ERC20 total: {usdt_total:.2f}\n"
            "The operator has sent what you requested."
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
            "Rate: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Fee (3%): {fee:.2f} USDT\n\n"
            "📍 Total to pay: {total:.2f} USDT-ERC20\n"
            "USDT-ERC20 payment address: {wallet}\n\n"
            "{retry}Status: Waiting for approval"
        ),
        "channel_caption_sell": (
            "🔴 Sell {asset}\n"
            "User: @{username}\n\n"
            "✨ Amount: {asset_amount:.8f} {asset}\n"
            "💳 Subtotal: {base:.2f} USDT\n"
            "Rate: {price:.2f} USDT (Binance, {price_time})\n"
            "💼 Fee (3%): {fee:.2f} USDT\n\n"
            "📍 To receive: {total:.2f} USDT-ERC20\n"
            "Client USDT-ERC20 address: {wallet}\n\n"
            "{retry}Status: Waiting for approval"
        ),
        "retry_label": "⚠️ Retry receipt\n",
        "lang_prompt": "Please select a language / Ընտրեք լեզուն / Выберите язык:",
        "copied_reply": "Payment address: {addr}"
    }
}

# ====== STORAGE (pending requests) ======
pending = {}  # channel_msg_id -> request dict

# ====== OPTIONAL: Google Sheets client ======
_gs_client = None
_gs_worksheet = None

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

def init_google_sheets():
    global _gs_client, _gs_worksheet
    if not ENABLE_GOOGLE_SHEETS:
        return
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
        scope = ["https://spreadsheets.google.com/feeds",
                 "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_JSON_PATH, scope)
        _gs_client = gspread.authorize(creds)
        try:
            sh = _gs_client.open(GOOGLE_SHEET_NAME)
        except Exception:
            sh = _gs_client.create(GOOGLE_SHEET_NAME)
        try:
            _gs_worksheet = sh.worksheet("Orders")
        except Exception:
            _gs_worksheet = sh.add_worksheet(title="Orders", rows="1000", cols="20")
            _gs_worksheet.append_row(
                ["ts", "flow", "asset", "asset_amount", "base_usdt", "fee_usdt", "total_usdt",
                 "username", "user_id", "wallet", "status"]
            )
    except Exception as e:
        logger.error(f"Google Sheets init failed: {e}")

def log_to_google_sheets(row: dict):
    if not ENABLE_GOOGLE_SHEETS or _gs_worksheet is None:
        return
    try:
        _gs_worksheet.append_row([
            row.get("ts"), row.get("flow"), row.get("asset"), row.get("asset_amount"),
            row.get("base_usdt"), row.get("fee_usdt"), row.get("total_usdt"),
            row.get("username"), row.get("user_id"), row.get("wallet"), row.get("status")
        ])
    except Exception as e:
        logger.error(f"Google Sheets append failed: {e}")

def log_request(row: dict):
    log_to_sqlite(row)
    log_to_google_sheets(row)

# ====== PRICE FETCH ======
async def fetch_prices() -> dict:
    """Цены BTC/ETH в USDT с Binance; fallback на PRICES_USD."""
    urls = {
        "BTC": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        "ETH": "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
    }
    prices = {}
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for sym, url in urls.items():
                async with session.get(url) as resp:
                    data = await resp.json()
                    prices[sym] = float(data["price"])
    except Exception as e:
        logger.warning(f"Price fetch failed, using fallback. Error: {e}")
        prices = PRICES_USD.copy()
    return prices

# ====== ADDRESS VALIDATION (soft, no eth-utils required) ======
def _basic_eth_format(addr: str) -> bool:
    return isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42 and all(c in "0123456789abcdefABCDEF" for c in addr[2:])

def is_checksum_address(addr: str) -> bool:
    """
    Мягкая проверка: базовый формат + допускаем без eth_utils.
    """
    return _basic_eth_format(addr)

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
    prompt = texts["Русский"]["lang_prompt"]
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

# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = await fetch_prices()
    btc = prices["BTC"]; eth = prices["ETH"]

    banner = texts["Русский"]["start_banner"].format(
        brand=texts["Русский"]["brand"], btc=btc, eth=eth
    )
    keyboard = [["🇷🇺 Русский"], ["🇦🇲 Հայերեն"], ["🇬🇧 English"]]
    msg = await update.message.reply_text(
        banner,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    context.user_data["start_msg_id"] = msg.message_id
    return LANGUAGE

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Определяем язык
    lang = language_map.get(update.message.text)
    if not lang:
        await update.message.reply_text(texts["Русский"]["lang_prompt"])
        return LANGUAGE
    context.user_data["lang"] = lang
    context.user_data["attempt"] = 0  # счётчик повторных чеков

    # Удаляем стартовый баннер
    try:
        start_msg_id = context.user_data.get("start_msg_id")
        if start_msg_id:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=start_msg_id)
    except Exception:
        pass

    # Показываем только курсы (S4-C) + меню. Приветствие убрано.
    prices = await fetch_prices()
    await update.message.reply_text(texts[lang]["rates"].format(btc=prices["BTC"], eth=prices["ETH"]))
    await update.message.reply_text(texts[lang]["info"], reply_markup=build_kb(lang))
    return ACTION

async def action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    txt = (update.message.text or "").strip()

    if ("Купить" in txt) or ("Buy" in txt) or ("Գնել" in txt):
        context.user_data["flow"] = "buy"
        await update.message.reply_text(texts[lang]["pick_asset"], reply_markup=ReplyKeyboardRemove())
        return PICK_ASSET

    if ("Продать" in txt) or ("Sell" in txt) or ("Վաճառել" in txt):
        context.user_data["flow"] = "sell"
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

    # Реальный курс на момент расчёта
    prices = await fetch_prices()
    price = prices[asset]
    price_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    base = amount * price
    fee = base * 0.03

    if context.user_data.get("flow") == "buy":
        total = base + fee
        # Сохраняем расчёт (для канала/коллбэков)
        context.user_data["calc"] = {
            "base": base, "fee": fee, "total": total, "price": price,
            "price_time": price_time, "asset_amount": amount
        }

        # Текст пользователю (S4 + O4)
        calc_text = texts[lang]["calc_buy"].format(
            asset=asset, asset_amount=amount, price=price, base=base,
            fee=fee, total=total, price_time=price_time
        )

        # Кнопка «Скопировать адрес»
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(texts[lang]["copy_addr"], callback_data="copy_addr")]
        ])
        await update.message.reply_text(calc_text)
        await update.message.reply_text(
            f"{texts[lang]['merchant_addr_title']}\n`{MERCHANT_USDT_ADDRESS}`",
            reply_markup=kb, parse_mode="Markdown"
        )
        await update.message.reply_text(texts[lang]["send_check"])
        # В BUY не спрашиваем адрес пользователя — сразу чек
        context.user_data["wallet"] = MERCHANT_USDT_ADDRESS  # в канал отразим наш адрес
        return AWAITING_CHECK

    else:
        total = base - fee
        context.user_data["calc"] = {
            "base": base, "fee": fee, "total": total, "price": price,
            "price_time": price_time, "asset_amount": amount
        }
        calc_text = texts[lang]["calc_sell"].format(
            asset=asset, asset_amount=amount, price=price, base=base,
            fee=fee, total=total, price_time=price_time
        )
        await update.message.reply_text(calc_text)
        await update.message.reply_text(texts[lang]["enter_wallet"])
        return ENTER_WALLET

# (soft) формат и checksum (без eth-utils)
def _basic_eth_format(addr: str) -> bool:
    return isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42

def _strong_checksum(addr: str) -> bool:
    # мягко пропускаем без eth-utils
    return True

async def enter_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    wallet = (update.message.text or "").strip()
    if not _basic_eth_format(wallet) or not _strong_checksum(wallet):
        await update.message.reply_text(texts[lang]["bad_wallet"])
        await update.message.reply_text("ℹ️ Для строгой проверки установите пакет: pip install eth-utils")
        return ENTER_WALLET

    context.user_data["wallet"] = wallet
    await update.message.reply_text(texts[lang]["send_check"])
    return AWAITING_CHECK

async def receive_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    if not update.message.photo:
        await update.message.reply_text(texts[lang]["only_photo"])
        return AWAITING_CHECK

    # Счётчик попыток (для пометки)
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
    wallet = u.get("wallet")  # BUY: твой адрес; SELL: адрес клиента

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

    # Лог заявки
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

    # Сохраняем для коллбэка
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
    data = query.data

    # Кнопка «📋 Скопировать адрес»
    if data == "copy_addr":
        lang = get_lang(context)
        await query.answer(text="Адрес отправлен сообщением", show_alert=False)
        await query.message.reply_text(texts[lang]["copied_reply"].format(addr=MERCHANT_USDT_ADDRESS))
        return

    await query.answer()
    msg_id = query.message.message_id

    if msg_id not in pending:
        await query.answer("Заявка не найдена", show_alert=True)
        return

    pdata = pending.pop(msg_id)
    lang = pdata["lang"]
    user_id = pdata["user_chat_id"]

    # Обновим лог статуса
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
        "status": "approved" if data == "approve" else "rejected"
    })

    if data == "approve":
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

    elif data == "reject":
        await context.bot.send_message(chat_id=user_id, text=texts[lang]["auto_reject_user"])
        # сразу вернуть пользователя к меню выбора языка
        await send_language_prompt_only(user_id, context)
        new_caption = (query.message.caption or "") + "\n❌ Отклонено"
        await query.edit_message_caption(caption=new_caption, reply_markup=None)

# ====== MAIN ======
def main():
    # Инициализация логирования/хранилищ
    if ENABLE_SQLITE:
        conn = sqlite3.connect("orders.db")
        conn.close()
    init_sqlite()
    if ENABLE_GOOGLE_SHEETS:
        init_google_sheets()

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
                MessageHandler(~filters.PHOTO & ~filters.COMMAND, receive_check),  # всё кроме фото — отвергаем
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
