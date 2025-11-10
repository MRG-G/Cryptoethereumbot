# 🤖 AI Assistant Instructions for Ethereum Platform

## Project Overview
This is a Telegram bot for cryptocurrency exchange platform supporting USDT (ERC20), BTC and ETH with 3% fee. The bot is multilingual (Russian, Armenian, English).

## Architecture
- `bot.py` - Main entry point, sets up conversation handlers and routes
- `handlers/` - Command and callback handlers organized by functionality
  - `start.py` - Initial language selection and welcome flow
  - `menu.py` - Main menu and exchange flow (asset selection, amount, wallet)
  - `check.py` - Payment verification flow
  - `admin.py` - Admin panel and request management
- `utils/` - Shared utilities and helpers
  - `db.py` - Database operations (SQLite + Google Sheets support)
  - `keyboards.py` - Telegram keyboard layouts
  - `pricing.py` - Cryptocurrency price calculations
  - `states.py` - Conversation state definitions
  - `texts.py` - Multilingual text content
  - `validate.py` - Input validation helpers

## Key Patterns
1. **State Management**
   - Uses `ConversationHandler` with states defined in `utils/states.py`
   - Flow: LANGUAGE -> ACTION -> PICK_ASSET -> ENTER_AMOUNT -> ENTER_WALLET -> AWAITING_CHECK

2. **Data Storage**
   - Hybrid storage with SQLite and Google Sheets support
   - Toggle via `ENABLE_SQLITE` and `ENABLE_GOOGLE_SHEETS` in `config.py`
   - Example logging: `log_request()` in `utils/db.py`

3. **Multilingual Support**
   - Text strings stored in `utils/texts.py` dictionary
   - Access pattern: `texts[language_code][text_key]`

## Development Workflow
1. Setup Virtual Environment:
   ```powershell
   python3 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Configuration:
   - Copy example config and set required values:
     - Telegram Bot Token (`TOKEN`)
     - Channel Username (`CHANNEL_USERNAME`)
     - Storage options (`ENABLE_SQLITE`, `ENABLE_GOOGLE_SHEETS`)
     - Google Sheets credentials if enabled

## Common Tasks
1. **Adding New Language**:
   - Add language code to language keyboard in `keyboards.py`
   - Add translations to `texts.py` dictionary

2. **Adding New Cryptocurrency**:
   - Add asset to menu keyboard in `keyboards.py`
   - Add pricing logic in `pricing.py`

3. **Modifying Exchange Flow**:
   - Update conversation states in `states.py`
   - Modify handler chain in `bot.py`
   - Update relevant handler in `handlers/` directory