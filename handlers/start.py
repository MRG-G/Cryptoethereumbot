# handlers/start.py
from telegram import Update
from telegram.ext import ContextTypes
from utils.texts import texts, language_map
from utils.keyboards import build_lang_kb
from utils.pricing import fetch_prices
from utils.states import LANGUAGE, ACTION

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Приветствие БЕЗ курса + выбор языка (универсальный текст RU-блока уже содержит 3-язычную строку выбора)
    m = await update.message.reply_text(
        texts["Русский"]["start_greet"],
        reply_markup=build_lang_kb(texts["Русский"])
    )
    context.user_data["start_msg_id"] = m.message_id
    return LANGUAGE

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = language_map.get(update.message.text)
    if not lang:
        await update.message.reply_text(
            texts["Русский"]["start_greet"],
            reply_markup=build_lang_kb(texts["Русский"])
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

    # Показать курс (один раз) на выбранном языке + меню
    prices = await fetch_prices()
    await update.message.reply_text(
        texts[lang]["rates_once"].format(btc=prices["BTC"], eth=prices["ETH"])
    )
    from utils.keyboards import build_menu_kb
    await update.message.reply_text(
        texts[lang]["menu_info"],
        reply_markup=build_menu_kb(texts[lang])
    )
    return ACTION
