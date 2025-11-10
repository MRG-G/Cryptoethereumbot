# handlers/admin.py
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
import logging

from utils.texts import texts
from utils.db import log_request, update_request, get_request_by_id
from config import ENABLE_SQLITE, ENABLE_GOOGLE_SHEETS

log = logging.getLogger("ethereum_platform.handlers.admin")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
	query = update.callback_query
	if not query:
		return
	await query.answer()
	data = (query.data or "")
	# формат: action:order_id
	parts = data.split(":", 1)
	if len(parts) != 2:
		await query.edit_message_text("Некорректное действие.")
		return
	action, order_id = parts
	order = get_request_by_id(order_id)
	if not order:
		await query.edit_message_text("Заказ не найден.")
		return

	if action == "approve":
		update_request(order_id, status="APPROVED")
		await query.edit_message_text(f"Заказ {order_id} подтверждён. Статус: APPROVED.")
		# уведомить пользователя
		try:
			uid = order["user_id"]
			await context.bot.send_message(chat_id=uid, text=f"Ваш заказ {order_id} подтверждён оператором. Ожидайте выплату.")
		except Exception:
			log.exception("Не удалось уведомить пользователя %s о APPROVE", order["user_id"])
	elif action == "reject":
		update_request(order_id, status="REJECTED")
		await query.edit_message_text(f"Заказ {order_id} отклонён. Статус: REJECTED.")
		try:
			uid = order["user_id"]
			# Удаляем временный pending (если есть)
			pending = context.bot_data.get("pending", {})
			pending.pop(int(uid), None)
			context.bot_data["pending"] = pending
			# Отправляем пользователю сообщение о отклонении и кнопку /start (видимая)
			start_kb = ReplyKeyboardMarkup([["/start"]], resize_keyboard=True, one_time_keyboard=False)
			await context.bot.send_message(
				chat_id=uid,
				text=f"Ваш заказ {order_id} отклонён оператором. Нажмите /start чтобы вернуться в начало.",
				reply_markup=start_kb
			)
		except Exception:
			log.exception("Не удалось уведомить пользователя %s о REJECT", order["user_id"])
	else:
		await query.edit_message_text("Неизвестное действие.")
