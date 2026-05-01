import logging
import os
import json
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


# Conversation states for the user question form.
NAME, LOCATION, AGE, QUESTION = range(4)

# The admin's next message is routed to the selected user through this map.
pending_responses = {}

# Persist remembered user names locally. This file is ignored by git.
PROFILE_STORE_PATH = Path("user_profiles.json")


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID_RAW = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW) if ADMIN_CHAT_ID_RAW else None

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Keep third-party HTTP logs quiet so Telegram API URLs are not written to logs.
logging.getLogger("httpx").setLevel(logging.WARNING)


def load_profiles() -> dict:
    """Load remembered user names from disk."""
    if not PROFILE_STORE_PATH.exists():
        return {}

    try:
        return json.loads(PROFILE_STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read user profile store; starting with an empty profile map.")
        return {}


def save_profiles(profiles: dict) -> None:
    """Save remembered user names to disk."""
    PROFILE_STORE_PATH.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_saved_profile(chat_id: int) -> dict:
    """Return remembered user profile fields for this Telegram chat."""
    profile = load_profiles().get(str(chat_id), {})
    return profile if isinstance(profile, dict) else {}


def get_profile_value(profile: dict, key: str) -> str | None:
    """Return a clean profile value when it exists."""
    value = profile.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def remember_profile_field(chat_id: int, key: str, value: str) -> None:
    """Remember one profile field so future forms can skip repeated questions."""
    profiles = load_profiles()
    chat_key = str(chat_id)
    profile = profiles.get(chat_key, {})

    if not isinstance(profile, dict):
        profile = {}

    profile[key] = value
    profiles[chat_key] = profile
    save_profiles(profiles)


def with_admin_status(message_text: str, status: str) -> str:
    """Replace the first line of the admin card with a status label."""
    lines = message_text.splitlines()
    if not lines:
        return status

    lines[0] = status
    return "\n".join(lines)


def extract_admin_card_value(message_text: str, label: str) -> str | None:
    """Extract a value from the formatted admin question card."""
    prefix = f"{label}: "

    for line in message_text.splitlines():
        if line.startswith(prefix):
            value = line.removeprefix(prefix).strip()
            return value or None

    return None


def new_question_markup() -> InlineKeyboardMarkup:
    """Return the reusable new-question inline button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("➕ Yana savol berish", callback_data="new_question")]]
    )


async def update_admin_question_status(
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int,
    original_text: str,
    status: str,
) -> None:
    """Edit the original admin question card and remove inline buttons."""
    if ADMIN_CHAT_ID is None:
        return

    try:
        await context.bot.edit_message_text(
            chat_id=ADMIN_CHAT_ID,
            message_id=message_id,
            text=with_admin_status(original_text, status),
        )
    except TelegramError as error:
        logger.warning("Could not update admin question status: %s", error)


async def begin_user_flow(reply_target, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start or restart the user flow using saved profile fields when available."""
    context.user_data.clear()
    saved_profile = get_saved_profile(chat_id)
    saved_name = get_profile_value(saved_profile, "name")
    saved_location = get_profile_value(saved_profile, "location")
    saved_age = get_profile_value(saved_profile, "age")

    if saved_name and saved_location and saved_age:
        context.user_data.update(
            {
                "name": saved_name,
                "location": saved_location,
                "age": saved_age,
            }
        )
        await reply_target.reply_text(
            "❓ Qanday mavzuda yordam kerak — savolingizni to'liq yozib qoldiring"
        )
        return QUESTION

    if saved_name and saved_location:
        context.user_data.update({"name": saved_name, "location": saved_location})
        await reply_target.reply_text("🎂 Yoshingizni yozing:")
        return AGE

    if saved_name:
        context.user_data.update({"name": saved_name})
        await reply_target.reply_text(
            f"📍 Assalomu alaykum, {saved_name}! Manzilingizni yoki shahringizni yozing:"
        )
        return LOCATION

    await reply_target.reply_text("👤 Assalomu alaykum! Iltimos, ismingizni yozing:")
    return NAME


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start or restart the question form."""
    return await begin_user_flow(update.message, update.effective_chat.id, context)


async def new_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restart the form when the user taps the inline new-question button."""
    query = update.callback_query
    await query.answer()
    return await begin_user_flow(query.message, query.from_user.id, context)


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep the admin out of the public user form."""
    pending_responses.pop(ADMIN_CHAT_ID, None)
    await update.message.reply_text(
        "🛠 Admin rejimi yoqilgan. Foydalanuvchilardan kelgan savollarga inline tugmalar orqali javob bering."
    )


async def ask_name_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to answer the name question again."""
    await update.message.reply_text("👤 Iltimos, ismingizni matn ko'rinishida yozing:")
    return NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's name and ask for their location."""
    name = update.message.text.strip()
    if not name:
        return await ask_name_again(update, context)

    context.user_data["name"] = name
    remember_profile_field(update.effective_chat.id, "name", name)
    await update.message.reply_text("📍 Manzilingizni yoki shahringizni yozing:")
    return LOCATION


async def ask_location_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to answer the location question again."""
    await update.message.reply_text("📍 Iltimos, manzilingizni yoki shahringizni matn ko'rinishida yozing:")
    return LOCATION


async def receive_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's location and ask for their age."""
    location = update.message.text.strip()
    if not location:
        return await ask_location_again(update, context)

    context.user_data["location"] = location
    remember_profile_field(update.effective_chat.id, "location", location)
    await update.message.reply_text("🎂 Yoshingizni yozing:")
    return AGE


async def ask_age_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to answer the age question again."""
    await update.message.reply_text("🎂 Iltimos, yoshingizni matn ko'rinishida yozing:")
    return AGE


async def receive_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's age and ask for their full question."""
    age = update.message.text.strip()
    if not age:
        return await ask_age_again(update, context)

    context.user_data["age"] = age
    remember_profile_field(update.effective_chat.id, "age", age)
    await update.message.reply_text(
        "❓ Qanday mavzuda yordam kerak — savolingizni to'liq yozib qoldiring"
    )
    return QUESTION


async def ask_question_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to submit the full question again."""
    await update.message.reply_text(
        "❓ Iltimos, savolingizni matn ko'rinishida to'liq yozib qoldiring:"
    )
    return QUESTION


async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's question, confirm receipt, and notify the admin."""
    question = update.message.text.strip()
    if not question:
        return await ask_question_again(update, context)

    context.user_data["question"] = question
    user_chat_id = update.effective_chat.id

    await update.message.reply_text(
        "✅ Savolingiz qabul qilindi. Shifokor tez orada javob beradi.",
        reply_markup=new_question_markup(),
    )

    if ADMIN_CHAT_ID is None:
        logger.error("ADMIN_CHAT_ID is not configured.")
        context.user_data.clear()
        return ConversationHandler.END

    admin_message = (
        "📩 Yangi savol!\n\n"
        f"👤 Ism: {context.user_data['name']}\n"
        f"📍 Manzil: {context.user_data['location']}\n"
        f"🎂 Yosh: {context.user_data['age']}\n"
        f"❓ Savol: {context.user_data['question']}\n\n"
        f"🆔 User ID: {user_chat_id}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Javob berish", callback_data=f"reply:{user_chat_id}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{user_chat_id}"),
            ]
        ]
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=admin_message,
        reply_markup=keyboard,
    )

    context.user_data.clear()
    return ConversationHandler.END


async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline admin buttons for replying to or rejecting a question."""
    query = update.callback_query
    await query.answer()

    if ADMIN_CHAT_ID is None or query.message.chat_id != ADMIN_CHAT_ID:
        await query.message.reply_text("Bu amal faqat admin uchun.")
        return

    action, user_chat_id_raw = query.data.split(":", 1)
    user_chat_id = int(user_chat_id_raw)

    if action == "reply":
        if ADMIN_CHAT_ID in pending_responses:
            await query.message.reply_text(
                "ℹ️ Avval oldingi foydalanuvchiga javobni yozib yuboring."
            )
            return

        user_name = extract_admin_card_value(query.message.text or "", "👤 Ism") or "foydalanuvchi"
        pending_responses[ADMIN_CHAT_ID] = {
            "user_chat_id": user_chat_id,
            "user_name": user_name,
            "admin_message_id": query.message.message_id,
            "admin_message_text": query.message.text or "",
        }
        await query.edit_message_text(
            text=with_admin_status(query.message.text or "", "⏳ Javob yozilmoqda...")
        )
        await context.bot.send_message(
            chat_id=user_chat_id,
            text="👩‍⚕️ Shifokor savolingizni ko'rib chiqmoqda. Tez orada javob yozadi.",
        )
        await query.message.reply_text(
            f"✍️ Siz {user_name} uchun javob yozyapsiz. Javobingizni yozing:"
        )
        return

    if action == "reject":
        pending_response = pending_responses.get(ADMIN_CHAT_ID)
        if pending_response and pending_response["user_chat_id"] == user_chat_id:
            pending_responses.pop(ADMIN_CHAT_ID, None)

        await context.bot.send_message(
            chat_id=user_chat_id,
            text=(
                "Uzr, hozirda sizning savolingizga javob berishning imkoni yo'q. "
                "Iltimos, keyinroq qayta murojaat qiling."
            ),
            reply_markup=new_question_markup(),
        )
        await update_admin_question_status(
            context,
            query.message.message_id,
            query.message.text or "",
            "❌ Rad etildi!",
        )
        await query.message.reply_text("❌ Rad etish xabari foydalanuvchiga yuborildi.")


async def handle_admin_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the admin's next text message to the selected user."""
    if ADMIN_CHAT_ID is None or update.effective_chat.id != ADMIN_CHAT_ID:
        return

    pending_response = pending_responses.pop(ADMIN_CHAT_ID, None)
    if pending_response is None:
        await update.message.reply_text(
            "ℹ️ Javob yuborish uchun avval savol ostidagi \"✅ Javob berish\" tugmasini bosing."
        )
        return

    user_chat_id = pending_response["user_chat_id"]
    admin_text = update.message.text
    await context.bot.send_message(
        chat_id=user_chat_id,
        text=f"👩‍⚕️ Dr. Farangisxon Yusufjonova:\n\n{admin_text}",
        reply_markup=new_question_markup(),
    )
    await update_admin_question_status(
        context,
        pending_response["admin_message_id"],
        pending_response["admin_message_text"],
        "✅ Javob berildi!",
    )
    user_name = pending_response.get("user_name", "foydalanuvchi")
    await update.message.reply_text(f"✅ Javob {user_name}ga yuborildi.")


async def unexpected_after_form(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restart the form when a user sends a new message after finishing."""
    return await start(update, context)


def build_application() -> Application:
    """Create the Telegram application and register all handlers."""
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to your .env file.")
    if ADMIN_CHAT_ID is None:
        raise RuntimeError("ADMIN_CHAT_ID is missing. Add it to your .env file.")

    application = Application.builder().token(BOT_TOKEN).build()

    # Admin reply messages must be checked before the generic user form handler.
    application.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_CHAT_ID) & filters.TEXT & ~filters.COMMAND,
            handle_admin_response,
        )
    )
    application.add_handler(CommandHandler("start", admin_start, filters=filters.Chat(ADMIN_CHAT_ID)))

    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(new_question, pattern="^new_question$"),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~filters.Chat(ADMIN_CHAT_ID),
                unexpected_after_form,
            ),
        ],
        states={
            NAME: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name),
                MessageHandler(filters.ALL, ask_name_again),
            ],
            LOCATION: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_location),
                MessageHandler(filters.ALL, ask_location_again),
            ],
            AGE: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_age),
                MessageHandler(filters.ALL, ask_age_again),
            ],
            QUESTION: [
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question),
                MessageHandler(filters.ALL, ask_question_again),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        # Keep this false because the text entry point is only for new questions
        # after a previous form ended. If re-entry is enabled, every form answer
        # is treated as a new entry and the bot asks for the name again.
        allow_reentry=False,
    )

    application.add_handler(conversation)
    application.add_handler(CallbackQueryHandler(handle_admin_action, pattern="^(reply|reject):"))
    return application


def main() -> None:
    """Run the bot with long polling."""
    application = build_application()
    logger.info("Starting @ginekolog_maslahati_bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
