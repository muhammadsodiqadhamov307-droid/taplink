<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Dr. Link Bio

A static link-in-bio page for a doctor profile. It is ready to deploy on Netlify.

## Configure Links

Edit `app-config.js` to update the public profile data and links:

- Telegram bot link
- Telegram channel link
- Instagram link
- Footer social links
- Contact email
- Avatar image

## Run Locally

You can open `index.html` directly in a browser.

If you prefer using Vite:

1. Install dependencies:
   `npm install`
2. Run the app:
   `npm run dev`

## Telegram Bot

The Telegram bot lives in `bot.py` and uses `python-telegram-bot` v20+.

1. Create a Python virtual environment.
2. Install bot dependencies:
   `pip install -r requirements.txt`
3. Copy `.env.example` to `.env`.
4. Set `BOT_TOKEN` and `ADMIN_CHAT_ID` in `.env`.
5. Run the bot:
   `python bot.py`

The bot username is `@ginekolog_maslahati_bot`.

## Deploy on Netlify

Push this project to GitHub, then connect the repository in Netlify. `netlify.toml` is already set to publish the project root, so no build command is required.
