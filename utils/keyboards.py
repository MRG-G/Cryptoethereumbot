# utils/keyboards.py
from telegram import ReplyKeyboardMarkup

def build_menu_kb(texts_lang: dict) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(texts_lang["buttons"], resize_keyboard=True)

def build_lang_kb(texts_lang: dict) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(texts_lang["lang_keyboard"], resize_keyboard=True, one_time_keyboard=True)
