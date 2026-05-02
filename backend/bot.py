import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from urllib import request

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonDefault, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters


FIRST_NAME, AGE, QUESTION = range(3)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://example.com").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite://backend/chat.db")
ADMIN_CHAT_ID_VALUE = str(os.getenv("ADMIN_CHAT_ID") or "").strip()
ADMIN_TELEGRAM_ID_VALUE = str(os.getenv("ADMIN_TELEGRAM_ID") or "").strip()
ADMIN_TELEGRAM_ID = ADMIN_CHAT_ID_VALUE or ADMIN_TELEGRAM_ID_VALUE
ADMIN_TELEGRAM_IDS = {value for value in [ADMIN_CHAT_ID_VALUE, ADMIN_TELEGRAM_ID_VALUE] if value}
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://localhost:3000").rstrip("/")

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
UPLOADS_DIR = Path.cwd() / "backend" / "uploads"


def init_db() -> None:
    """Create database tables when the backend has not run yet."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                receiver_id TEXT NOT NULL,
                content TEXT,
                type TEXT NOT NULL CHECK(type IN ('text', 'image', 'video', 'file')),
                file_url TEXT,
                file_name TEXT,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_read INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def get_user(telegram_id: int) -> dict | None:
    """Return a registered user profile by Telegram ID."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT telegram_id, first_name, age FROM users WHERE telegram_id = ?",
            (str(telegram_id),),
        ).fetchone()
        return dict(row) if row else None


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


def save_message(sender_id: int, content: str, message_type: str = "text", file_url: str | None = None, file_name: str | None = None) -> int:
    """Save a user message for the doctor/admin."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (sender_id, receiver_id, content, type, file_url, file_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(sender_id), ADMIN_TELEGRAM_ID, content or None, message_type, file_url, file_name),
        )
        conn.commit()
        return int(cursor.lastrowid)


def notify_backend(message_id: int) -> None:
    """Tell the Node server to emit a newly saved bot message to admin sockets."""
    if not INTERNAL_API_TOKEN:
        return

    req = request.Request(
        f"{INTERNAL_API_BASE_URL}/api/internal/messages/{message_id}/notify",
        method="POST",
        headers={"x-internal-api-token": INTERNAL_API_TOKEN},
    )

    try:
        request.urlopen(req, timeout=3).close()
    except Exception as error:
        logger.warning("Could not notify backend about message %s: %s", message_id, error)


def admin_web_app_markup() -> InlineKeyboardMarkup:
    """Return an inline Telegram Web App button for the doctor."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🩺 Admin Mini App", web_app=WebAppInfo(url=BASE_URL))]]
    )


def has_valid_web_app_url() -> bool:
    """Telegram Web App buttons require a public HTTPS URL."""
    return BASE_URL.startswith("https://")


def is_admin(update: Update) -> bool:
    """Return True when this Telegram user is the configured doctor/admin."""
    return str(update.effective_user.id) in ADMIN_TELEGRAM_IDS


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send the admin-only Mini App button."""
    context.user_data.clear()

    if not has_valid_web_app_url():
        await update.message.reply_text(
            "Mini App URL hali HTTPS emas. BASE_URL ni HTTPS tunnel yoki hosting URL ga sozlang."
        )
        return ConversationHandler.END

    await context.bot.set_chat_menu_button(
        chat_id=update.effective_chat.id,
        menu_button=MenuButtonWebApp(text="🩺 Admin Mini App", web_app=WebAppInfo(url=BASE_URL)),
    )
    await update.message.reply_text(
        "Admin panel tayyor. Mini App orqali foydalanuvchilar xabarlarini ko'rishingiz mumkin.",
        reply_markup=admin_web_app_markup(),
    )
    return ConversationHandler.END


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start user onboarding, or show the admin Mini App."""
    if is_admin(update):
        return await admin_start(update, context)

    await context.bot.set_chat_menu_button(
        chat_id=update.effective_chat.id,
        menu_button=MenuButtonDefault(),
    )
    context.user_data.clear()
    profile = get_user(update.effective_user.id)

    if profile:
        context.user_data["first_name"] = profile["first_name"]
        context.user_data["age"] = profile["age"]
        await update.message.reply_text("Savolingizni yozing. Shifokorga yuboramiz:")
        return QUESTION

    await update.message.reply_text("Assalomu alaykum! Iltimos, ismingizni yozing:")
    return FIRST_NAME


async def route_incoming_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Route plain user messages: admin gets Mini App, registered users send directly, new users onboard."""
    if is_admin(update):
        await update.message.reply_text("Xabarlarni Mini App admin panelidan boshqaring.")
        return ConversationHandler.END

    await context.bot.set_chat_menu_button(
        chat_id=update.effective_chat.id,
        menu_button=MenuButtonDefault(),
    )
    if get_user(update.effective_user.id):
        return await receive_question(update, context)

    await update.message.reply_text("Avval ro'yxatdan o'tish uchun /start bosing.")
    return ConversationHandler.END


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
    """Save age and ask the user to send their first question."""
    age = update.message.text.strip()
    if not age:
        await update.message.reply_text("Iltimos, yoshingizni matn ko'rinishida yozing:")
        return AGE

    context.user_data["age"] = age
    save_user(update.effective_user.id, context.user_data["first_name"], age)
    await context.bot.set_chat_menu_button(
        chat_id=update.effective_chat.id,
        menu_button=MenuButtonDefault(),
    )
    await update.message.reply_text("Ma'lumotlaringiz saqlandi. Endi savolingizni yozing:")
    return QUESTION


async def save_telegram_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str, str | None, str | None]:
    """Download a Telegram attachment into backend/uploads and return message metadata."""
    message = update.message
    attachment = None
    message_type = "file"
    file_name = None

    if message.photo:
        attachment = message.photo[-1]
        message_type = "image"
        file_name = f"photo-{message.message_id}.jpg"
    elif message.video:
        attachment = message.video
        message_type = "video"
        file_name = message.video.file_name or f"video-{message.message_id}.mp4"
    elif message.document:
        attachment = message.document
        file_name = message.document.file_name or f"file-{message.message_id}"

    if not attachment:
        return "text", None, None

    telegram_file = await context.bot.get_file(attachment.file_id)
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in file_name)
    local_name = f"telegram-{update.effective_user.id}-{message.message_id}-{safe_name}"
    local_path = UPLOADS_DIR / local_name
    await telegram_file.download_to_drive(custom_path=local_path)
    return message_type, f"/uploads/{local_name}", file_name


async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save a user message from Telegram and notify the admin dashboard."""
    profile = get_user(update.effective_user.id)

    if not profile and "first_name" not in context.user_data:
        await update.message.reply_text("Avval /start bosing va ism/yoshingizni yozing.")
        return ConversationHandler.END

    if profile:
        context.user_data["first_name"] = profile["first_name"]
        context.user_data["age"] = profile["age"]

    message_type, file_url, file_name = await save_telegram_attachment(update, context)
    content = (update.message.text or update.message.caption or "").strip()

    if not content and not file_url:
        await update.message.reply_text("Iltimos, savolingizni matn, rasm, video yoki fayl ko'rinishida yuboring.")
        return QUESTION

    message_id = save_message(
        update.effective_user.id,
        content,
        message_type,
        file_url,
        file_name,
    )
    await asyncio.to_thread(notify_backend, message_id)
    await update.message.reply_text("✅ Xabaringiz shifokorga yuborildi. Javobni shu bot orqali olasiz.")
    return ConversationHandler.END


async def ask_current_step_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle unexpected non-text input during onboarding."""
    await update.message.reply_text("Iltimos, javobni matn ko'rinishida yozing.")
    return FIRST_NAME if "first_name" not in context.user_data else AGE


def main() -> None:
    """Run the Telegram bot with long polling."""
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to .env.")
    if not ADMIN_TELEGRAM_IDS:
        raise RuntimeError("ADMIN_TELEGRAM_ID or ADMIN_CHAT_ID is missing. Add it to .env.")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(
                filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                route_incoming_user_message,
            ),
        ],
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
            QUESTION: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, receive_question),
                MessageHandler(filters.ALL, receive_question),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=False,
    )

    application.add_handler(conversation)
    logger.info("Starting bot-to-admin-dashboard bridge...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
