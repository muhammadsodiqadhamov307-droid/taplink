import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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


def is_text_message(update: Update) -> bool:
    """Return True when the incoming update has normal text content."""
    return bool(update.message and update.message.text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start or restart the question form."""
    context.user_data.clear()
    await update.message.reply_text("Assalomu alaykum! Iltimos, ismingizni yozing:")
    return NAME


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep the admin out of the public user form."""
    pending_responses.pop(ADMIN_CHAT_ID, None)
    await update.message.reply_text(
        "Admin rejimi yoqilgan. Foydalanuvchilardan kelgan savollarga inline tugmalar orqali javob bering."
    )


async def ask_name_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to answer the name question again."""
    await update.message.reply_text("Iltimos, ismingizni matn ko'rinishida yozing:")
    return NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's name and ask for their location."""
    name = update.message.text.strip()
    if not name:
        return await ask_name_again(update, context)

    context.user_data["name"] = name
    await update.message.reply_text("Manzilingizni yoki shahringizni yozing:")
    return LOCATION


async def ask_location_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to answer the location question again."""
    await update.message.reply_text("Iltimos, manzilingizni yoki shahringizni matn ko'rinishida yozing:")
    return LOCATION


async def receive_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's location and ask for their age."""
    location = update.message.text.strip()
    if not location:
        return await ask_location_again(update, context)

    context.user_data["location"] = location
    await update.message.reply_text("Yoshingizni yozing:")
    return AGE


async def ask_age_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to answer the age question again."""
    await update.message.reply_text("Iltimos, yoshingizni matn ko'rinishida yozing:")
    return AGE


async def receive_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's age and ask for their full question."""
    age = update.message.text.strip()
    if not age:
        return await ask_age_again(update, context)

    context.user_data["age"] = age
    await update.message.reply_text(
        "Qanday mavzuda yordam kerak — savolingizni to'liq yozib qoldiring"
    )
    return QUESTION


async def ask_question_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to submit the full question again."""
    await update.message.reply_text(
        "Iltimos, savolingizni matn ko'rinishida to'liq yozib qoldiring:"
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
        "Savolingiz qabul qilindi. Shifokor tez orada javob beradi."
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
        pending_responses[ADMIN_CHAT_ID] = user_chat_id
        await query.message.reply_text(
            "Siz ushbu foydalanuvchiga javob yozyapsiz. Javobingizni yozing:"
        )
        return

    if action == "reject":
        await context.bot.send_message(
            chat_id=user_chat_id,
            text=(
                "Uzr, hozirda sizning savolingizga javob berishning imkoni yo'q. "
                "Iltimos, keyinroq qayta murojaat qiling."
            ),
        )
        await query.message.reply_text("Rad etish xabari foydalanuvchiga yuborildi.")


async def handle_admin_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the admin's next text message to the selected user."""
    if ADMIN_CHAT_ID is None or update.effective_chat.id != ADMIN_CHAT_ID:
        return

    user_chat_id = pending_responses.pop(ADMIN_CHAT_ID, None)
    if user_chat_id is None:
        await update.message.reply_text(
            "Javob yuborish uchun avval savol ostidagi \"✅ Javob berish\" tugmasini bosing."
        )
        return

    admin_text = update.message.text
    await context.bot.send_message(
        chat_id=user_chat_id,
        text=f"👩‍⚕️ Dr. Farangisxon Yusufjonova:\n\n{admin_text}",
    )
    await update.message.reply_text("Javob foydalanuvchiga yuborildi.")


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
