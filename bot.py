# bot.py
import logging
from logging.handlers import RotatingFileHandler
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, filters
)

from config import TOKEN, CHANNEL_USERNAME, ENABLE_SQLITE, ENABLE_GOOGLE_SHEETS, GOOGLE_SHEETS_JSON_PATH, GOOGLE_SHEET_NAME
from utils.states import LANGUAGE, ACTION, PICK_ASSET, ENTER_AMOUNT, ENTER_WALLET, AWAITING_CHECK
from utils.db import init_sqlite, init_google_sheets
from handlers.start import start, set_language
from handlers.menu import action, pick_asset, enter_amount, enter_wallet
from handlers.check import receive_check
from handlers.admin import button_callback
from utils.pricing import fetch_prices  # добавлено

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ethereum_platform")

def main():
	# Настройка логирования: файл + консоль
	# Инициализация хранилищ
	if ENABLE_SQLITE:
		try:
			init_sqlite("orders.db")
			log.info("SQLite initialized")
		except Exception as e:
			log.exception("SQLite initialization failed: %s", e)

	if ENABLE_GOOGLE_SHEETS:
		try:
			init_google_sheets(GOOGLE_SHEETS_JSON_PATH, GOOGLE_SHEET_NAME)
			log.info("Google Sheets initialized")
		except Exception as e:
			log.exception("Google Sheets initialization failed: %s", e)

	logger = logging.getLogger("ethereum_platform")
	logger.setLevel(logging.INFO)
	# Файловый лог с ротацией
	file_handler = RotatingFileHandler("ethereum_platform.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
	file_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
	file_handler.setFormatter(file_fmt)
	logger.addHandler(file_handler)
	# Консольный логер (если не установлен)
	console = logging.StreamHandler()
	console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
	logger.addHandler(console)

	app = Application.builder().token(TOKEN).build()

	# Данные доступные всем хендлерам
	app.bot_data.setdefault("CHANNEL_USERNAME", CHANNEL_USERNAME)
	app.bot_data.setdefault("pending", {})

	# Периодическое обновление кэша цен (job_queue)
	async def periodic_refresh_prices(context):
		try:
			await fetch_prices()
			logger.debug("Prices refreshed by periodic job")
		except Exception as e:
			logger.exception("Periodic price refresh failed: %s", e)

	# Запустить job обновления цен каждые 30 секунд (первый запуск сразу)
	app.job_queue.run_repeating(periodic_refresh_prices, interval=30, first=0)

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

	log.info("✅ Bot is starting...")
	try:
		app.run_polling()
	except KeyboardInterrupt:
		log.info("Bot stopped by KeyboardInterrupt")
	except Exception:
		log.exception("Unhandled exception in bot")

if __name__ == "__main__":
	main()
