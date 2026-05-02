# Dr. Farangisxon Telegram Mini App

This project now contains two pieces:

- A Telegram bot that collects the user's first name and age, then opens the Mini App.
- A real-time Telegram Mini App chat where users and the doctor can exchange text, images, videos, and files.

The Mini App uses Node.js, Express, Socket.IO, SQLite, and a plain HTML/CSS/JS frontend.

## Project Structure

```text
backend/
  server.js
  bot.py
  uploads/
frontend/
  index.html
  style.css
  app.js
bot.py
requirements.txt
package.json
.env.example
```

## Environment

Copy `.env.example` to `.env` and set:

```env
BOT_TOKEN="your_telegram_bot_token"
ADMIN_TELEGRAM_ID="your_telegram_user_id"
BASE_URL="https://yourdomain.com"
DATABASE_URL="sqlite://backend/chat.db"
PORT=3000
```

`ADMIN_CHAT_ID` is also accepted for backwards compatibility, but `ADMIN_TELEGRAM_ID` is preferred.

## Install

Install Node dependencies:

```bash
npm install
```

Install Python bot dependencies:

```bash
pip install -r requirements.txt
```

## Run Locally

Start the Mini App backend:

```bash
npm run dev
```

Start the Telegram bot in another terminal:

```bash
python bot.py
```

Telegram Mini Apps must be opened over HTTPS. For local testing, expose port `3000` with ngrok or another HTTPS tunnel, then set `BASE_URL` to that HTTPS URL.

## Behavior

Bot:

- `/start` asks for first name.
- Then it asks for age.
- It stores the user in SQLite.
- It sends a Telegram Web App button: `💬 Doctor bilan chat`.

Mini App:

- Regular users see one WhatsApp-style chat with the doctor.
- The doctor sees a two-panel admin interface with all users on the left and the selected chat on the right.
- Text, images, videos, and files are stored in SQLite and served from `backend/uploads`.
- Socket.IO updates both sides in real time.
- Telegram `initData` is validated on the backend before trusting identity.

## Deploy

This is no longer a Netlify-only static app. The Mini App needs a server that can run Node.js, WebSockets, SQLite/PostgreSQL, and file uploads. Deploy it to a VPS, Render, Railway, Fly.io, or another backend-capable host, then set `BASE_URL` to the HTTPS deployment URL.
