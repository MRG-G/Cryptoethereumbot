# utils/validate.py
from datetime import datetime
import piexif
import re
from decimal import Decimal, InvalidOperation

def basic_eth_format(addr: str) -> bool:
    return isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42 and \
           all(c in "0123456789abcdefABCDEF" for c in addr[2:])

def strong_checksum(addr: str) -> bool:
    try:
        from eth_utils import is_checksum_address
        return is_checksum_address(addr)
    except Exception:
        return True  # мягкое поведение если eth_utils не установлен

def exif_check_is_today(file_bytes: bytes) -> tuple[bool, bool]:
    """
    Возвращает (is_today, exif_missing)
      - is_today: True если дата фото (EXIF DateTimeOriginal/DateTime) — сегодня.
      - exif_missing: True если EXIF вообще отсутствует или нет полей с датой.
    Логика для Telegram (EXIF часто пропадает):
      - Нет EXIF или нет даты -> (True, True)    # принимаем, но помечаем для оператора
      - Если дата есть и не сегодня -> (False, False)
      - Если дата есть и сегодня -> (True, False)
    """
    try:
        exif_dict = piexif.load(file_bytes)
        exif = exif_dict.get("Exif", {})
        zeroth = exif_dict.get("0th", {})
        cand = []

        for key in (piexif.ExifIFD.DateTimeOriginal, piexif.ExifIFD.DateTimeDigitized):
            v = exif.get(key)
            if isinstance(v, bytes):
                cand.append(v.decode(errors="ignore"))
            elif isinstance(v, str):
                cand.append(v)

        v0 = zeroth.get(piexif.ImageIFD.DateTime)
        if isinstance(v0, bytes):
            cand.append(v0.decode(errors="ignore"))
        elif isinstance(v0, str):
            cand.append(v0)

        def parse_dt(s: str):
            try:
                return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
            except Exception:
                return None

        for s in cand:
            dt = parse_dt(s)
            if dt:
                if dt.date() == datetime.now().date():
                    return True, False
                else:
                    return False, False

        return True, True  # EXIF есть, но без валидной даты
    except Exception:
        return True, True  # нет EXIF — принимаем, но помечаем

# Простые правила валидации и минимумы
MIN_AMOUNTS = {
	"ETH": Decimal("0.001"),
	"BTC": Decimal("0.0001"),
	"USDT": Decimal("1")
}

eth_re = re.compile(r"^0x[a-fA-F0-9]{40}$")
btc_re = re.compile(r"^(1|3|bc1)[A-Za-z0-9]{25,39}$")  # упрощённо

def validate_amount(asset: str, amount_str: str):
	"""
	Проверяет и парсит сумму. Возвращает (Decimal(amount), None) при успехе,
	или (None, "error message") при ошибке.
	"""
	asset = (asset or "").upper()
	try:
		amt = Decimal(str(amount_str).replace(",", ".").strip())
	except (InvalidOperation, AttributeError):
		return None, "Неверный формат суммы."

	if amt <= 0:
		return None, "Сумма должна быть больше нуля."

	min_amt = MIN_AMOUNTS.get(asset)
	if min_amt and amt < min_amt:
		return None, f"Минимальная сумма для {asset}: {min_amt}."

	return amt, None

def validate_wallet(asset: str, wallet: str) -> bool:
	"""
	Простая валидация адреса в зависимости от ассета.
	ETH/USDT (ERC20) — проверка 0x..., BTC — упрощённая проверка.
	"""
	if not wallet or not isinstance(wallet, str):
		return False
	asset = (asset or "").upper()
	w = wallet.strip()
	if asset in ("ETH", "USDT"):
		return bool(eth_re.match(w))
	if asset == "BTC":
		return bool(btc_re.match(w))
	# по умолчанию допускаем любую непустую строку
	return True
