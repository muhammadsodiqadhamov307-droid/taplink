import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters


FIRST_NAME, AGE = range(2)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://example.com").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite://backend/chat.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


def sqlite_path_from_url(database_url: str) -> Path:
    """Convert sqlite://DATABASE_URL into a local filesystem path."""
    if not database_url.startswith("sqlite://"):
        raise RuntimeError("Only sqlite:// DATABASE_URL is supported by the bot")

    db_path = database_url.replace("sqlite://", "")
    path = Path(db_path)
    return path if path.is_absolute() else Path.cwd() / path


DB_PATH = sqlite_path_from_url(DATABASE_URL)


def init_db() -> None:
    """Create the users table when the backend has not run yet."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id TEXT PRIMARY KEY,
                first_name TEXT NOT NULL,
                age TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def save_user(telegram_id: int, first_name: str, age: str) -> None:
    """Store or update the Telegram user's onboarding profile."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_id, first_name, age)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id)
            DO UPDATE SET
                first_name = excluded.first_name,
                age = excluded.age,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(telegram_id), first_name, age),
        )
        conn.commit()


def web_app_markup() -> InlineKeyboardMarkup:
    """Return an inline Telegram Web App button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Doctor bilan chat", web_app=WebAppInfo(url=BASE_URL))]]
    )


def has_valid_web_app_url() -> bool:
    """Telegram Web App buttons require a public HTTPS URL."""
    return BASE_URL.startswith("https://")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start onboarding by asking for first name."""
    context.user_data.clear()
    await update.message.reply_text("Assalomu alaykum! Iltimos, ismingizni yozing:")
    return FIRST_NAME


async def receive_first_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save first name and ask for age."""
    first_name = update.message.text.strip()
    if not first_name:
        await update.message.reply_text("Iltimos, ismingizni matn ko'rinishida yozing:")
        return FIRST_NAME

    context.user_data["first_name"] = first_name
    await update.message.reply_text("Yoshingizni yozing:")
    return AGE


async def receive_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save age, configure the menu button, and send the Mini App link."""
    age = update.message.text.strip()
    if not age:
        await update.message.reply_text("Iltimos, yoshingizni matn ko'rinishida yozing:")
        return AGE

    first_name = context.user_data["first_name"]
    save_user(update.effective_user.id, first_name, age)

    if not has_valid_web_app_url():
        await update.message.reply_text(
            "Ma'lumotlaringiz saqlandi, lekin Mini App URL hali HTTPS emas. "
            "Iltimos, serverni ngrok yoki hosting orqali HTTPS qilib, BASE_URL ni yangilang."
        )
        context.user_data.clear()
        return ConversationHandler.END

    await context.bot.set_chat_menu_button(
        chat_id=update.effective_chat.id,
        menu_button=MenuButtonWebApp(text="💬 Chat with Doctor", web_app=WebAppInfo(url=BASE_URL)),
    )
    await update.message.reply_text(
        "Ma'lumotlaringiz saqlandi. Endi Mini App orqali shifokor bilan yozishishingiz mumkin.",
        reply_markup=web_app_markup(),
    )

    context.user_data.clear()
    return ConversationHandler.END


async def ask_current_step_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle non-text input during onboarding."""
    await update.message.reply_text("Iltimos, javobni matn ko'rinishida yozing.")
    return FIRST_NAME if "first_name" not in context.user_data else AGE


def main() -> None:
    """Run the onboarding bot with long polling."""
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to .env.")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            FIRST_NAME: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_first_name),
                MessageHandler(filters.ALL, ask_current_step_again),
            ],
            AGE: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_age),
                MessageHandler(filters.ALL, ask_current_step_again),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    application.add_handler(conversation)
    logger.info("Starting onboarding bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
