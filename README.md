# Dr. Farangisxon Telegram Admin Mini App

This project contains:

- A Telegram bot where regular users send their name, age, and messages.
- A doctor/admin-only Telegram Mini App dashboard where the doctor sees all user chats and replies.

The backend uses Node.js, Express, Socket.IO, SQLite, and file uploads. The bot uses `python-telegram-bot`.

## Environment

Copy `.env.example` to `.env` and set:

```env
BOT_TOKEN="your_telegram_bot_token"
ADMIN_TELEGRAM_ID="your_telegram_user_id"
BASE_URL="https://yourdomain.com"
DATABASE_URL="sqlite://backend/chat.db"
INTERNAL_API_TOKEN="change_me_to_a_random_secret"
INTERNAL_API_BASE_URL="http://localhost:3000"
PORT=3000
```

`ADMIN_CHAT_ID` is also accepted for backwards compatibility, but `ADMIN_TELEGRAM_ID` is preferred.

## Install

```bash
npm install
pip install -r requirements.txt
```

## Run Locally

Build the React admin Mini App:

```bash
npm run build
```

Start the Mini App backend:

```bash
npm run dev
```

Start the Telegram bot in another terminal:

```bash
python bot.py
```

Telegram Mini Apps require HTTPS. For local testing, expose port `3000` with Cloudflare Tunnel or ngrok, then set `BASE_URL` to that HTTPS URL.

## Behavior

Regular users:

- Use the Telegram bot only.
- `/start` asks for first name and age.
- Then the bot asks for the user's message.
- Future messages sent to the bot are saved and shown in the doctor Mini App.
- Doctor replies from the Mini App are sent back through the Telegram bot.

Doctor/admin:

- Sends `/start` to the bot.
- Receives an admin Mini App button.
- Opens a two-panel dashboard: users on the left, selected chat on the right.
- Can reply from the Mini App; replies go to the user in Telegram.

Security:

- Mini App auth validates Telegram `initData`.
- Admin dashboard is shown only when Telegram user ID matches `ADMIN_TELEGRAM_ID`.
- Bot-to-backend live updates use `INTERNAL_API_TOKEN`.

## Deploy

This is not a Netlify-only static app. It needs a backend host that supports Node.js, WebSockets, SQLite/PostgreSQL, and file uploads. Use a VPS, Render, Railway, Fly.io, or another backend-capable host, then set `BASE_URL` to the HTTPS deployment URL.
