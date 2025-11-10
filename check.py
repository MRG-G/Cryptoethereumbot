# handlers/check.py
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from decimal import Decimal
from utils.pricing import calculate_settlement
import logging

log = logging.getLogger("ethereum_platform.handlers.check")

def _fmt_currency_dot(value: Decimal) -> str:
	"""Например: 1000258.5 -> '1.000.258,50'"""
	try:
		v = Decimal(value).quantize(Decimal("0.01"))
	except Exception:
		return str(value)
	s = f"{v:.2f}"
	integer, frac = s.split(".")
	parts = []
	while integer:
		parts.append(integer[-3:])
		integer = integer[:-3]
	int_with_dots = ".".join(reversed(parts)) if parts else "0"
	return f"{int_with_dots},{frac}"

async def receive_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
	"""
	Обработка фото/сообщения как подтверждения платежа — формируем чек для оператора.
	Ожидается pending в context.bot_data["pending"][user_id].
	"""
	user = update.effective_user
	if not user:
		return
	user_id = user.id

	pending = context.bot_data.get("pending", {})
	order = pending.get(user_id)
	if not order:
		if update.message:
			await update.message.reply_text("Нет активного запроса для формирования чека.")
		return

	order_id = order["order_id"]
	# обновляем статус в БД
	try:
		update_request(order_id, status="AWAITING_OPERATOR")
	except Exception:
		log.exception("Failed to update order status to AWAITING_OPERATOR for %s", order_id)

	asset = order.get("asset", "ETH")
	amount = order.get("amount", Decimal("0"))
	wallet = order.get("wallet", "—")

	# Рассчитать по курсу
	try:
		settlement = calculate_settlement(asset, amount)
	except Exception as e:
		log.exception("Ошибка расчёта для чека user_id=%s: %s", user_id, e)
		settlement = {
			"amount_crypto": amount,
			"price_usd": Decimal("0"),
			"total_usd": Decimal("0"),
			"fee_usd": Decimal("0"),
			"to_transfer_usd": Decimal("0"),
		}

	amount_str = f"{settlement['amount_crypto']:.6f}".rstrip("0").rstrip(".")
	price_str = f"{_fmt_currency_dot(settlement['price_usd'])} $"  # цена за 1
	total_str = f"{_fmt_currency_dot(settlement['total_usd'])} $"
	fee_str = f"{_fmt_currency_dot(settlement['fee_usd'])} $"
	to_transfer_str = f"{_fmt_currency_dot(settlement['to_transfer_usd'])} $"

	check_text = (
		f"🔔 Новый чек продажи крипто\n\n"
		f"Пользователь: {user.full_name} (id: {user_id})\n"
		f"Ассет: {asset}\n"
		f"Кол-во: {amount_str} {asset}\n"
		f"Курс: {price_str} за 1 {asset}\n\n"
		f"Итого (USD): {total_str}\n"
		f"Комиссия платформы (3%): {fee_str}\n"
		f"К выплате пользователю (оператор должен перевести): {to_transfer_str}\n\n"
		f"Адрес/кошелёк пользователя: {wallet}\n\n"
		f"📌 Проверьте перевод и подтвердите операцию."
	)

	# Inline кнопки для оператора
	kb = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("✅ Approve", callback_data=f"approve:{order_id}"),
			 InlineKeyboardButton("❌ Reject", callback_data=f"reject:{order_id}")]
		]
	)

	# Отправка в канал операторов (CHANNEL_USERNAME из bot_data)
	channel = context.bot_data.get("CHANNEL_USERNAME")
	try:
		if channel:
			msg = await context.bot.send_message(chat_id=channel, text=check_text, reply_markup=kb)
			# Сохраняем id сообщения оператора в БД для ссылок/логов
			try:
				update_request(order_id, operator_msg_id=msg.message_id)
			except Exception:
				log.exception("Failed to save operator_msg_id for %s", order_id)
		else:
			await update.message.reply_text("Operator channel not configured. Чек: \n" + check_text)
	except Exception:
		log.exception("Не удалось отправить чек в канал для order %s", order_id)
		await update.message.reply_text("Ошибка отправки чека оператору. Попробуйте позже.")
		return

	# Уведомление пользователю
	try:
		await update.message.reply_text("Чек сформирован и отправлен оператору для проверки.")
	except Exception:
		log.exception("Не удалось уведомить пользователя %s", user_id)

	# Обновляем статус в pending
	order["status"] = "AWAITING_OPERATOR"
	pending[user_id] = order
	context.bot_data["pending"] = pending
	log.info("Чек сформирован для user_id=%s asset=%s amount=%s", user_id, asset, amount)

	lang = context.user_data.get("lang", "Русский")

	if not update.message.photo:
		await update.message.reply_text(texts[lang]["only_photo"])
		return ACTION

	# Скачиваем bytes для EXIF
	photo = update.message.photo[-1]
	f = await photo.get_file()
	file_bytes = await f.download_as_bytearray()
	is_today, exif_missing = exif_check_is_today(bytes(file_bytes))

	if not is_today:
		# Авто-отклонение + возврат к выбору языка
		await update.message.reply_text(texts[lang]["auto_reject_user"])
		await update.message.reply_text(
			texts["Русский"]["start_greet"]  # текст с выбором языка
		)
		return LANGUAGE

	# Счётчик повторных чеков
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

	exif_line = texts[lang]["exif_missing"] if exif_missing else texts[lang]["exif_ok"]

	kb = InlineKeyboardMarkup([
		[InlineKeyboardButton(texts[lang].get("approve_button", "✅"), callback_data="approve"),
		 InlineKeyboardButton(texts[lang].get("reject_button", "❌"), callback_data="reject")]
	])

	cap_key = "channel_caption_buy" if flow == "buy" else "channel_caption_sell"
	# include merchant_wallet for sell flow if present
	merchant_wallet = u.get("merchant_wallet")
	caption = texts[lang][cap_key].format(
		asset=asset, username=username, asset_amount=asset_amount,
		base=base, fee=fee, total=total, wallet=wallet, exif=exif_line,
		merchant_wallet=merchant_wallet
	)
	if retry_note:
		caption = retry_note + caption

	# Отправка фото в канал
	sent = await context.bot.send_photo(
		chat_id=context.bot_data["CHANNEL_USERNAME"],
		photo=photo.file_id,
		caption=caption,
		reply_markup=kb
	)

	# Лог в БД/Sheets
	log_request({
		"ts": datetime.utcnow().isoformat(),
		"flow": flow, "asset": asset, "asset_amount": asset_amount,
		"base_usdt": base, "fee_usdt": fee, "total_usdt": total,
		"username": username, "user_id": update.effective_user.id,
		"wallet": wallet, "status": "pending"
	}, enable_sqlite=ENABLE_SQLITE, enable_gs=ENABLE_GOOGLE_SHEETS)

	# Сохранить в pending
	pending = context.bot_data.setdefault("pending", {})
	pending[sent.message_id] = {
		"lang": lang, "user_chat_id": update.effective_chat.id,
		"asset": asset, "asset_amount": asset_amount, "usdt_total": total,
		"wallet": wallet, "flow": flow, "merchant_wallet": merchant_wallet
	}

	await update.message.reply_text(texts[lang]["after_check_wait"])
	return ACTION
