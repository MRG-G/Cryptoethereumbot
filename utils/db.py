# utils/db.py
import sqlite3
from datetime import datetime
import uuid
import logging

log = logging.getLogger("ethereum_platform.db")

DB_CONN = None
DB_PATH = None

def init_sqlite(path: str):
	global DB_CONN, DB_PATH
	DB_PATH = path
	DB_CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
	c = DB_CONN.cursor()
	c.execute(
		"""
		CREATE TABLE IF NOT EXISTS orders (
			id TEXT PRIMARY KEY,
			user_id INTEGER,
			asset TEXT,
			amount TEXT,
			wallet TEXT,
			status TEXT,
			created_at TEXT,
			updated_at TEXT,
			operator_msg_id INTEGER
		)
	"""
	)
	DB_CONN.commit()
	log.info("SQLite DB initialized at %s", DB_PATH)

# Заглушка для Google Sheets (если включено в config)
def init_google_sheets(json_path: str, sheet_name: str):
	# ...existing code...
	log.info("Google Sheets init called (stub)")

def _now_iso():
	return datetime.utcnow().isoformat()

def log_request(user_id: int, asset: str, amount, wallet: str, status: str = "CREATED"):
	"""
	Создаёт запись заказа и возвращает id (UUID).
	amount сохраняется как строка (Decimal поддерживается).
	"""
	global DB_CONN
	if DB_CONN is None:
		raise RuntimeError("SQLite not initialized")
	oid = str(uuid.uuid4())
	c = DB_CONN.cursor()
	c.execute(
		"INSERT INTO orders (id, user_id, asset, amount, wallet, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
		(oid, int(user_id), asset, str(amount), wallet, status, _now_iso(), _now_iso()),
	)
	DB_CONN.commit()
	log.info("Order logged id=%s user=%s asset=%s amount=%s", oid, user_id, asset, amount)
	return oid

def update_request(order_id: str, **fields):
	"""Обновляет поля заказа; fields может содержать status, operator_msg_id и т.д."""
	global DB_CONN
	if DB_CONN is None:
		raise RuntimeError("SQLite not initialized")
	cols = []
	vals = []
	for k, v in fields.items():
		cols.append(f"{k} = ?")
		vals.append(v)
	if not cols:
		return
	vals.append(order_id)
	sql = f"UPDATE orders SET {', '.join(cols)}, updated_at = ? WHERE id = ?"
	# добавляем updated_at перед id
	vals.insert(-1, _now_iso())
	c = DB_CONN.cursor()
	c.execute(sql, vals)
	DB_CONN.commit()
	log.info("Order %s updated: %s", order_id, fields)

def get_request_by_id(order_id: str):
	global DB_CONN
	if DB_CONN is None:
		raise RuntimeError("SQLite not initialized")
	c = DB_CONN.cursor()
	c.execute("SELECT id, user_id, asset, amount, wallet, status, created_at, updated_at, operator_msg_id FROM orders WHERE id = ?", (order_id,))
	row = c.fetchone()
	if not row:
		return None
	keys = ["id", "user_id", "asset", "amount", "wallet", "status", "created_at", "updated_at", "operator_msg_id"]
	return dict(zip(keys, row))

def get_pending():
	global DB_CONN
	if DB_CONN is None:
		raise RuntimeError("SQLite not initialized")
	c = DB_CONN.cursor()
	c.execute("SELECT id, user_id, asset, amount, wallet, status, created_at FROM orders WHERE status = 'AWAITING_OPERATOR' ORDER BY created_at DESC")
	rows = c.fetchall()
	return rows
