# bot.py
import asyncio
from datetime import datetime
import json
import os
import sqlite3
import logging

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters, CallbackQueryHandler
)

from config import (
    TOKEN, CHANNEL_USERNAME, MERCHANT_USDT_ADDRESS,
    ENABLE_SQLITE, ENABLE_GOOGLE_SHEETS, GOOGLE_SHEETS_JSON_PATH, GOOGLE_SHEET_NAME
)
from utils.pricing import fetch_prices
from utils.eth import basic_eth_format, strong_checksum
from utils.exif_check import check_photo_fresh_judgement

# ====== Логирование ======
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eth_platform")

# ====== STATES ======
LANGUAGE, ACTION, PICK_ASSET, ENTER_AMOUNT, ENTER_WALLET, AWAITING_CHECK = range(6)

# ====== LANG MAP ======
language_map = {
    "🇷🇺 Русский": "Русский",
    "🇦🇲 Հայերեն": "Հայերեն",
    "🇬🇧 English": "English"
}

# ====== Тексты ======
texts = {
    "Русский": {
        "brand": "💎 Ethereum Платформа®",
        "start_greet": "👋 Добро пожаловать!\nВы используете 💎 Ethereum Платформа® — безопасный и удобный сервис для обмена USDT, BTC и ETH.",
        "lang_prompt": "Выберите язык / Խնդրում ենք ընտրել լեզուն / Please select a language:",
        "rates_once": "📊 Текущие курсы:\n₿ BTC: {btc:.4f} USDT | Ξ ETH: {eth:.4f} USDT\n💵 Оплата и выплаты: только USDT-ERC20\n⚠️ Комиссия 3% (покупка +, продажа −)",
        "menu_info": "Выберите действие:",
        "buttons": [["💰 Купить BTC/ETH", "💸 Продать BTC/ETH"], ["⬅️ Назад"]],
        "pick_asset": "Выберите актив: BTC или ETH.",
        "enter_amount_buy": "Введите количество {asset}, которое хотите купить (например 0.01):",
        "enter_amount_sell": "Введите количество {asset}, которое хотите продать (например 0.01):",
        "merchant_addr_title": "💳 Адрес для оплаты (USDT-ERC20):\n`{addr}`\n(нажмите, чтобы скопировать)",
        "enter_wallet": "Отправьте ваш 💵 USDT-ERC20 адрес для выплаты (начинается с 0x…):",
        "bad_wallet": "Неверный адрес. Должен начинаться с 0x, быть длиной 42 и иметь корректный формат (EIP-55 рекомендуется).",
        "send_check": "Теперь пришлите **только фото/скриншот** чека. Текст, документы и файлы не принимаются.",
        "only_photo": "Принимается **только фото/скриншот** чека. Пришлите изображение.",
        "after_check_wait": "✅ Чек получен. Ваша заявка ждёт подтверждения оператора.",
        "calc_buy": "Курс {asset}: {price:.4f} USDT\nСумма: {base:.2f} USDT\nКомиссия (3%): {fee:.2f} USDT\n**Итого к оплате:** {total:.2f} USDT",
        "calc_sell": "Курс {asset}: {price:.4f} USDT\nСумма: {base:.2f} USDT\nКомиссия (3%): {fee:.2f} USDT\n**К получению:** {total:.2f} USDT",
        "approved_user": "✅ Ваша заявка одобрена.\nАктив: {asset}\nКоличество: {asset_amount:.8f} {asset}\nUSDT-ERC20: {usdt_total:.2f}\nОператор отправил то, что вы запрашивали.",
        "auto_reject_user": "❌ Ваша заявка отклонена.\nПричина: чек не видно / дата и время не сегодняшние / чек неверный.\nПожалуйста, отправьте корректный чек (чёткое фото с актуальными датой/временем).",
        "retry_label": "⚠️ Повторная отправка чека\n",
        "channel_caption_buy": ("🟢 Покупка {asset}\n"
                                "Пользователь: @{username}\n"
                                "Количество: {asset_amount:.8f} {asset}\n\n"
                                "Сумма: {base:.2f} USDT\nКомиссия (3%): {fee:.2f} USDT\n"
                                "Итого к оплате: {total:.2f} USDT\n\n"
                                "USDT-ERC20 адрес: {wallet}\n"
                                "{exif}\nСтатус: Ожидает подтверждения"),
        "channel_caption_sell": ("🔴 Продажа {asset}\n"
                                 "Пользователь: @{username}\n"
                                 "Количество: {asset_amount:.8f} {asset}\n\n"
                                 "Сумма: {base:.2f} USDT\nКомиссия (3%): {fee:.2f} USDT\n"
                                 "К выплате: {total:.2f} USDT\n\n"
                                 "USDT-ERC20 адрес (клиента): {wallet}\n"
                                 "{exif}\nСтатус: Ожидает подтверждения")
    },
    "Հայերեն": {
        "brand": "💎 Ethereum Հարթակ®",
        "start_greet": "👋 Բարի գալուստ։\nԴուք օգտագործում եք 💎 Ethereum Հարթակ® — անվտանգ և հարմար ծառայություն USDT, BTC և ETH փոխանակման համար։",
        "lang_prompt": "Խնդրում ենք ընտրել լեզուն / Выберите язык / Please select a language:",
        "rates_once": "📊 Ընթացիկ փոխարժեքներ:\n₿ BTC: {btc:.4f} USDT | Ξ ETH: {eth:.4f} USDT\n💵 Վճարումները՝ միայն USDT-ERC20\n⚠️ Միջնորդավճար 3% (գնման դեպքում՝ +, վաճառքի՝ −)",
        "menu_info": "Ընտրեք գործողությունը՝",
        "buttons": [["💰 Գնել BTC/ETH", "💸 Վաճառել BTC/ETH"], ["⬅️ Վերադառնալ"]],
        "pick_asset": "Ընտրեք ակտիվ՝ BTC կամ ETH։",
        "enter_amount_buy": "Մուտքագրեք {asset}-ի քանակը, որը ցանկանում եք գնել (օր. 0.01)։",
        "enter_amount_sell": "Մուտքագրեք {asset}-ի քանակը, որը ցանկանում եք վաճառել (օր. 0.01)։",
        "merchant_addr_title": "💳 Վճարման հասցե (USDT-ERC20):\n`{addr}`\n(սեղմեք՝ պատճենելու համար)",
        "enter_wallet": "Ուղարկեք ձեր 💵 USDT-ERC20 հասցեն (սկսվում է 0x…)՝ վճարման համար:",
        "bad_wallet": "Սխալ հասցե․ պետք է սկսվի 0x-ով, լինի 42 նիշ և ունենա ճիշտ EIP-55 ֆորմատ։",
        "send_check": "Այժմ ուղարկեք **միայն լուսանկար/սքրինշոթ**՝ որպես չեկ։ Տեքստերը չեն ընդունվում։",
        "only_photo": "Ընդունվում է **միայն լուսանկար/սքրինշոթ**։",
        "after_check_wait": "✅ Ստուգումը ստացվեց։ Ձեր հայտը սպասում է հաստատման։",
        "calc_buy": "Գին {asset}: {price:.4f} USDT\nԳումար: {base:.2f} USDT\nՄիջնորդավճար (3%): {fee:.2f} USDT\n**Վճարում:** {total:.2f} USDT",
        "calc_sell": "Գին {asset}: {price:.4f} USDT\nԳումար: {base:.2f} USDT\nՄիջնորդավճար (3%): {fee:.2f} USDT\n**Կստանաք:** {total:.2f} USDT",
        "approved_user": "✅ Ձեր հայտը հաստատվել է։\nԱկտիվ՝ {asset}\nՔանակ՝ {asset_amount:.8f} {asset}\nUSDT-ERC20՝ {usdt_total:.2f}։",
        "auto_reject_user": "❌ Ձեր հայտը մերժվել է։\nՊատճառ՝ չեկը չի երևում / ամսաթիվը և ժամը այսօրը չեն / չեկը սխալ է։",
        "retry_label": "⚠️ Կրկնակի ստուգում\n",
        "channel_caption_buy": ("🟢 Գնում {asset}\n"
                                "Օգտատեր՝ @{username}\n"
                                "Քանակ՝ {asset_amount:.8f} {asset}\n\n"
                                "Գումար՝ {base:.2f} USDT\nՄիջնորդավճար (3%)՝ {fee:.2f} USDT\n"
                                "Վճարում՝ {total:.2f} USDT\n\n"
                                "USDT-ERC20 հասցե՝ {wallet}\n"
                                "{exif}\nԿարգավիճակ՝ Սպասում է հաստատման"),
        "channel_caption_sell": ("🔴 Վաճառք {asset}\n"
                                 "Օգտատեր՝ @{username}\n"
                                 "Քանակ՝ {asset_amount:.8f} {asset}\n\n"
                                 "Գումար՝ {base:.2f} USDT\nՄիջնորդավճար (3%)՝ {fee:.2f} USDT\n"
                                 "Ստանալու եք՝ {total:.2f} USDT\n\n"
                                 "USDT-ERC20 (հաճախորդի)՝ {wallet}\n"
                                 "{exif}\nԿարգավիճակ՝ Սպասում է հաստատման")
    },
    "English": {
        "brand": "💎 Ethereum Platform®",
        "start_greet": "👋 Welcome!\nYou are using 💎 Ethereum Platform® — a safe and convenient service for exchanging USDT, BTC and ETH.",
        "lang_prompt": "Please select a language / Խնդրում ենք ընտրել լեզուն / Выберите язык:",
        "rates_once": "📊 Current rates:\n₿ BTC: {btc:.4f} USDT | Ξ ETH: {eth:.4f} USDT\n💵 Settlement: USDT-ERC20 only\n⚠️ Fee 3% (buy +, sell −)",
        "menu_info": "Choose an action:",
        "buttons": [["💰 Buy BTC/ETH", "💸 Sell BTC/ETH"], ["⬅️ Back"]],
        "pick_asset": "Choose asset: BTC or ETH.",
        "enter_amount_buy": "Enter how much {asset} you want to buy (e.g., 0.01):",
        "enter_amount_sell": "Enter how much {asset} you want to sell (e.g., 0.01):",
        "merchant_addr_title": "💳 Payment address (USDT-ERC20):\n`{addr}`\n(tap to copy)",
        "enter_wallet": "Send your 💵 USDT-ERC20 payout address (starts with 0x…):",
        "bad_wallet": "Invalid address. Must start with 0x, be 42 chars, and follow EIP-55 format.",
        "send_check": "Now send **photo/screenshot only** of the receipt. Text/files are not accepted.",
        "only_photo": "Only **photo/screenshot** is accepted at this step.",
        "after_check_wait": "✅ Receipt received. Your request is pending operator approval.",
        "calc_buy": "{asset} price: {price:.4f} USDT\nSubtotal: {base:.2f} USDT\nFee (3%): {fee:.2f} USDT\n**To pay:** {total:.2f} USDT",
        "calc_sell": "{asset} price: {price:.4f} USDT\nSubtotal: {base:.2f} USDT\nFee (3%): {fee:.2f} USDT\n**You will receive:** {total:.2f} USDT",
        "approved_user": "✅ Your request has been approved.\nAsset: {asset}\nAmount: {asset_amount:.8f} {asset}\nUSDT-ERC20: {usdt_total:.2f}.",
        "auto_reject_user": "❌ Your request was rejected.\nReason: receipt not visible / not today’s date/time / invalid receipt.",
        "retry_label": "⚠️ Retry receipt\n",
        "channel_caption_buy": ("🟢 Buy {asset}\n"
                                "User: @{username}\n"
                                "Amount: {asset_amount:.8f} {asset}\n\n"
                                "Subtotal: {base:.2f} USDT\nFee (3%): {fee:.2f} USDT\n"
                                "Total to pay: {total:.2f} USDT\n\n"
                                "USDT-ERC20 address: {wallet}\n"
                                "{exif}\nStatus: Waiting for approval"),
        "channel_caption_sell": ("🔴 Sell {asset}\n"
                                 "User: @{username}\n"
                                 "Amount: {asset_amount:.8f} {asset}\n\n"
                                 "Subtotal: {base:.2f} USDT\nFee (3%): {fee:.2f} USDT\n"
                                 "To receive: {total:.2f} USDT\n\n"
                                 "Client USDT-ERC20 address: {wallet}\n"
                                 "{exif}\nStatus: Waiting for approval")
    }
}

# ====== Pending ======
pending = {}  # channel_msg_id -> data

# ====== Storage (SQLite + Sheets, опционально) ======
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

_gs_client = None
_gs_worksheet = None

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
        log.error(f"Google Sheets init failed: {e}")

def log_request(row: dict):
    if ENABLE_SQLITE:
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
    if ENABLE_GOOGLE_SHEETS and _gs_worksheet is not None:
        try:
            _gs_worksheet.append_row([
                row.get("ts"), row.get("flow"), row.get("asset"), row.get("asset_amount"),
                row.get("base_usdt"), row.get("fee_usdt"), row.get("total_usdt"),
                row.get("username"), row.get("user_id"), row.get("wallet"), row.get("status")
            ])
        except Exception as e:
            log.error(f"GS append failed: {e}")

# ====== Helpers ======
def build_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(texts[lang]["buttons"], resize_keyboard=True)

def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "Русский")

def parse_float(s: str):
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None

# ====== Handlers ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Приветствие БЕЗ курса + выбор языка
    keyboard = [["🇷🇺 Русский"], ["🇦🇲 Հայերեն"], ["🇬🇧 English"]]
    greet = (
        f"{texts['Русский']['start_greet']}\n\n"
        f"{texts['Русский']['lang_prompt']}"
    )
    m = await update.message.reply_text(
        greet,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    context.user_data["start_msg_id"] = m.message_id
    return LANGUAGE

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = language_map.get(update.message.text)
    if not lang:
        keyboard = [["🇷🇺 Русский"], ["🇦🇲 Հայերեն"], ["🇬🇧 English"]]
        await update.message.reply_text(
            texts["Русский"]["lang_prompt"],
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return LANGUAGE

    context.user_data["lang"] = lang
    context.user_data["attempt"] = 0

    # Удалим стартовый баннер (если есть)
    try:
        msg_id = context.user_data.get("start_msg_id")
        if msg_id:
            await context.bot.delete_message(update.effective_chat.id, msg_id)
    except Exception:
        pass

    # Показываем курс (1 раз) на выбранном языке + меню
    prices = await fetch_prices()
    await update.message.reply_text(
        texts[lang]["rates_once"].format(btc=prices["BTC"], eth=prices["ETH"])
    )
    await update.message.reply_text(texts[lang]["menu_info"], reply_markup=build_kb(lang))
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

    await update.message.reply_text(texts[lang]["menu_info"], reply_markup=build_kb(lang))
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

    prices = await fetch_prices()
    price = prices[asset]
    base = amount * price
    fee = base * 0.03

    if context.user_data.get("flow") == "buy":
        total = base + fee
        await update.message.reply_text(
            texts[lang]["calc_buy"].format(asset=asset, price=price, base=base, fee=fee, total=total),
            parse_mode="Markdown"
        )
        # Показать адрес мерчанта (кликабельный код-блок)
        await update.message.reply_text(
            texts[lang]["merchant_addr_title"].format(addr=MERCHANT_USDT_ADDRESS),
            parse_mode="Markdown"
        )
        await update.message.reply_text(texts[lang]["send_check"])
        context.user_data["wallet"] = MERCHANT_USDT_ADDRESS
        context.user_data["calc"] = {"base": base, "fee": fee, "total": total, "price": price}
        return AWAITING_CHECK
    else:
        total = base - fee
        context.user_data["calc"] = {"base": base, "fee": fee, "total": total, "price": price}
        await update.message.reply_text(
            texts[lang]["calc_sell"].format(asset=asset, price=price, base=base, fee=fee, total=total),
            parse_mode="Markdown"
        )
        await update.message.reply_text(texts[lang]["enter_wallet"])
        return ENTER_WALLET

async def enter_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    wallet = (update.message.text or "").strip()
    if not basic_eth_format(wallet) or not strong_checksum(wallet):
        await update.message.reply_text(texts[lang]["bad_wallet"])
        return ENTER_WALLET

    context.user_data["wallet"] = wallet
    await update.message.reply_text(texts[lang]["send_check"])
    return AWAITING_CHECK

async def receive_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    if not update.message.photo:
        await update.message.reply_text(texts[lang]["only_photo"])
        return AWAITING_CHECK

    # Скачиваем фото для EXIF-проверки
    photo = update.message.photo[-1]
    f = await photo.get_file()
    file_bytes = await f.download_as_bytearray()

    is_today, exif_missing = check_photo_fresh_judgement(bytes(file_bytes))
    if not is_today:
        # Авто-отклонение + возврат к языку
        await update.message.reply_text(texts[lang]["auto_reject_user"])
        # Вернуть к выбору языка
        keyboard = [["🇷🇺 Русский"], ["🇦🇲 Հայերեն"], ["🇬🇧 English"]]
        await update.message.reply_text(
            texts["Русский"]["lang_prompt"],
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return LANGUAGE

    # Счётчик попыток — пометка
    context.user_data["attempt"] = context.user_data.get("attempt", 0) + 1
    retry_note = texts[lang]["retry_label"] if context.user_data["attempt"] > 1 else ""

    u = context.user_data
    flow = u.get("flow")
    asset = u.get("asset")
    asset_amount = u.get("asset_amount", 0.0)
    base = u.get("calc", {}).get("base", 0.0)
    fee = u.get("calc", {}).get("fee", 0.0)
    total = u.get("calc", {}).get("total", 0.0)
    username = update.effective_user.username or update.effective_user.first_name
    wallet = u.get("wallet")

    exif_line = "⚠️ EXIF отсутствует — проверь внимательно" if exif_missing else "EXIF OK"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="approve"),
         InlineKeyboardButton("❌ Отклонить", callback_data="reject")]
    ])

    caption_tpl = "channel_caption_buy" if flow == "buy" else "channel_caption_sell"
    caption = texts[lang][caption_tpl].format(
        asset=asset, username=username, asset_amount=asset_amount,
        base=base, fee=fee, total=total, wallet=wallet, exif=exif_line
    )
    if retry_note:
        caption = retry_note + caption

    # Отправляем чек в канал (с фото)
    sent = await context.bot.send_photo(
        chat_id=CHANNEL_USERNAME,
        photo=photo.file_id,
        caption=caption,
        reply_markup=kb
    )

    # Лог
    log_request({
        "ts": datetime.utcnow().isoformat(),
        "flow": flow, "asset": asset, "asset_amount": asset_amount,
        "base_usdt": base, "fee_usdt": fee, "total_usdt": total,
        "username": username, "user_id": update.effective_user.id,
        "wallet": wallet, "status": "pending"
    })

    pending[sent.message_id] = {
        "lang": lang, "user_chat_id": update.effective_chat.id,
        "asset": asset, "asset_amount": asset_amount, "usdt_total": total,
        "wallet": wallet, "flow": flow
    }

    await update.message.reply_text(texts[lang]["after_check_wait"])
    return ACTION

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    msg_id = q.message.message_id

    if msg_id not in pending:
        await q.answer("Заявка не найдена", show_alert=True)
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
        "status": "approved" if q.data == "approve" else "rejected"
    })

    if q.data == "approve":
        await context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]["approved_user"].format(
                asset=pdata["asset"], asset_amount=pdata["asset_amount"], usdt_total=pdata["usdt_total"]
            )
        )
        new_caption = (q.message.caption or "") + "\n✅ Заявка подтверждена"
        await q.edit_message_caption(caption=new_caption, reply_markup=None)

    elif q.data == "reject":
        await context.bot.send_message(chat_id=user_id, text=texts[lang]["auto_reject_user"])
        # Вернуть к выбору языка
        keyboard = [["🇷🇺 Русский"], ["🇦🇲 Հայերեն"], ["🇬🇧 English"]]
        await context.bot.send_message(
            chat_id=user_id,
            text=texts["Русский"]["lang_prompt"],
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        new_caption = (q.message.caption or "") + "\n❌ Отклонено"
        await q.edit_message_caption(caption=new_caption, reply_markup=None)

def main():
    if ENABLE_SQLITE:
        conn = sqlite3.connect("orders.db"); conn.close()
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
