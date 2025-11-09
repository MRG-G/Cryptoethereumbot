# config.py
TOKEN = "8298425629:AAGJzSFg_SHT_HjEPA1OTzJnXHRdPw51T10"
CHANNEL_USERNAME = "@ethereumamoperator"             # @username канала/чата модерации

# API ключи для получения курсов
BINANCE_API_KEY = "bTL2h9ufsfbSBSE1hLeVDiRmyZmaW20ofIAyPogbboAMNTzfn5P79piwy86PliA1"            # <-- Ваш API ключ Binance
BINANCE_API_SECRET = "YOUR_BINANCE_API_SECRET"      # <-- Ваш API секрет Binance
COINGECKO_API_KEY = "YOUR_COINGECKO_API_KEY"       # <-- Ваш API ключ CoinGecko

# Адреса для приема криптовалют
MERCHANT_USDT_ADDRESS = "0xYourUSDT_ERC20_Address_Here"  # <-- ВАШ адрес USDT-ERC20
MERCHANT_BTC_ADDRESS = "YourBTCAddressHere"              # <-- ВАШ адрес BTC
MERCHANT_ETH_ADDRESS = "0xYourETHAddressHere"           # <-- ВАШ адрес ETH

# Логи/хранилища
ENABLE_SQLITE = True
ENABLE_GOOGLE_SHEETS = True                          # Включено по вашему запросу
GOOGLE_SHEETS_JSON_PATH = "./service_account.json"   # путь к ключу сервис-аккаунта
GOOGLE_SHEET_NAME = "EthereumPlatform_Orders"

# Комиссия
FEE_RATE = 0.03  # 3%

# Разрешённые активы
ALLOWED_ASSETS = ("BTC", "ETH")
