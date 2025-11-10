# handlers/menu.py
from decimal import Decimal
from telegram import Update
from telegram.ext import ContextTypes
from utils.validate import validate_amount, validate_wallet
from utils.pricing import calculate_settlement
import logging

log = logging.getLogger("ethereum_platform.handlers.menu")

# Форматирование: точка как разделитель тысяч, запятая как десятичный разделитель
def _fmt_currency_dot(value: Decimal) -> str:
	"""Например: 1000258.5 -> '1.000.258,50'"""
	try:
		v = Decimal(value).quantize(Decimal("0.01"))
	except Exception:
		return str(value)
	s = f"{v:.2f}"  # "1000258.50"
	integer, frac = s.split(".")
	parts = []
	while integer:
		parts.append(integer[-3:])
		integer = integer[:-3]
	int_with_dots = ".".join(reversed(parts)) if parts else "0"
	return f"{int_with_dots},{frac}"

def get_lang(context) -> str:
    return context.user_data.get("lang", "Русский")

def parse_float(s: str):
    try:
        return float((s or "").replace(",", "."))
    except Exception:
        return None

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
        from handlers.start import start
        return await start(update, context)

    await update.message.reply_text(texts[lang]["menu_info"])
    return ACTION

async def pick_asset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    asset = (update.message.text or "").upper().strip()
    if asset not in ALLOWED_ASSETS:
        await update.message.reply_text(texts[lang]["pick_asset"])
        return PICK_ASSET

    context.user_data["asset"] = asset
    flow = context.user_data.get("flow")

    if flow == "buy":
        await update.message.reply_text(texts[lang]["enter_amount_buy"].format(asset=asset))
    else:
        await update.message.reply_text(texts[lang]["enter_amount_sell"].format(asset=asset))
    return ENTER_AMOUNT

async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
	"""
	Ввод суммы: валидируем и сохраняем в pending.
	Ожидается, что asset выбран и хранится в context.user_data['asset'].
	"""
	user = update.effective_user
	if not user or not update.message:
		return
	user_id = user.id
	asset = context.user_data.get("asset", "ETH")
	amt_str = (update.message.text or "").strip()

	amount, err = validate_amount(asset, amt_str)
	if err:
		await update.message.reply_text(err)
		return ENTER_AMOUNT

	# Сохраняем временно в bot_data pending
	pending = context.bot_data.setdefault("pending", {})
	entry = pending.get(user_id, {})
	entry.update({"asset": asset.upper(), "amount": amount, "status": "AWAITING_WALLET"})
	pending[user_id] = entry
	context.bot_data["pending"] = pending

	await update.message.reply_text(f"Вы хотите продать {amount} {asset}. Введите адрес кошелька для получения средств:")
	return ENTER_WALLET

async def enter_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
	"""
	Ввод кошелька: валидируем, сохраняем, показываем пользователю резюме и просим отправить чек.
	"""
	user = update.effective_user
	if not user or not update.message:
		return
	user_id = user.id
	wallet = (update.message.text or "").strip()

	pending = context.bot_data.setdefault("pending", {})
	entry = pending.get(user_id, {})
	asset = entry.get("asset", context.user_data.get("asset", "ETH"))

	if not validate_wallet(asset, wallet):
		await update.message.reply_text("Неверный формат адреса. Проверьте и введите снова.")
		return ENTER_WALLET

	# Логируем заказ в БД и обновляем pending
	try:
		order_id = log_request(user_id=user_id, asset=asset, amount=entry.get("amount"), wallet=wallet, status="AWAITING_CHECK")
		entry.update({"wallet": wallet, "status": "AWAITING_CHECK", "order_id": order_id})
		pending[user_id] = entry
		context.bot_data["pending"] = pending
	except Exception as e:
		log.exception("DB error when creating order for user %s: %s", user_id, e)
		await update.message.reply_text("Ошибка сервера при создании заказа. Попробуйте позже.")
		return

	# Показать предварительный расчёт
	try:
		settlement = calculate_settlement(asset, entry.get("amount"))
		total = settlement['total_usd']
		fee = settlement['fee_usd']
		to_transfer = settlement['to_transfer_usd']
		await update.message.reply_text(
			f"Краткое резюме:\nАссет: {asset}\nСумма: {entry['amount']}\nИтого (USD): { _fmt_currency_dot(total) }\nКомиссия (3%): { _fmt_currency_dot(fee) }\nК выплате пользователю: { _fmt_currency_dot(to_transfer) }\n\nОтправьте чек (фото/сообщение) для подтверждения оплаты."
		)
	except Exception as e:
		log.exception("Ошибка расчёта для user_id=%s: %s", user_id, e)
		await update.message.reply_text("Заказ создан. Отправьте чек (фото/сообщение) для подтверждения оплаты.")
	# Переход в состояние ожидания чека
	return None
