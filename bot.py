import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
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


# Conversation states for the fresh two-step user flow.
INFO, QUESTION = range(2)

# The admin's next message is routed to the selected user through this map.
pending_responses = {}

USER_NEW_QUESTION_BUTTON = "Yangi savol yuborish"


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


def user_keyboard() -> ReplyKeyboardMarkup:
    """Return the persistent user keyboard."""
    return ReplyKeyboardMarkup(
        [[USER_NEW_QUESTION_BUTTON]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def continue_reply_markup() -> InlineKeyboardMarkup:
    """Return the user inline button for replying after doctor/admin messages."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✍️ Javob yozish", callback_data="new_question")]]
    )


def admin_repeat_reply_markup(user_chat_id: int) -> InlineKeyboardMarkup:
    """Return the admin inline button for sending another response to the same user."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ Qayta xabar yuborish", callback_data=f"reply:{user_chat_id}")]]
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


async def begin_user_flow(reply_target, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start a fresh user form every time."""
    context.user_data.clear()
    await reply_target.reply_text(
        "👤 Sizga murojaat qilishimiz uchun iltimos ismingiz va yoshingizni yozing:",
        reply_markup=user_keyboard(),
    )
    return INFO


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start or restart the fresh user form."""
    return await begin_user_flow(update.message, context)


async def new_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start another message, reusing the info the user already gave."""
    query = update.callback_query
    await query.answer()

    saved_info = context.user_data.get("saved_info")
    if saved_info:
        context.user_data["info"] = saved_info
        context.user_data.pop("question", None)
        await query.message.reply_text(
            "❓ Qanday mavzuda yordam kerak — savolingizni to'liq yozib qoldiring",
            reply_markup=user_keyboard(),
        )
        return QUESTION

    return await begin_user_flow(query.message, context)


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep the admin out of the public user form."""
    pending_responses.pop(ADMIN_CHAT_ID, None)
    await update.message.reply_text(
        "🛠 Admin rejimi yoqilgan. Foydalanuvchilardan kelgan savollarga inline tugmalar orqali javob bering."
    )


async def ask_info_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to submit their name and age again."""
    await update.message.reply_text(
        "👤 Iltimos, ismingiz va yoshingizni matn ko'rinishida yozing:",
        reply_markup=user_keyboard(),
    )
    return INFO


async def receive_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user's single info field and ask for their question."""
    info = update.message.text.strip()
    if not info:
        return await ask_info_again(update, context)

    context.user_data["info"] = info
    context.user_data["saved_info"] = info
    await update.message.reply_text(
        "❓ Qanday mavzuda yordam kerak — savolingizni to'liq yozib qoldiring",
        reply_markup=user_keyboard(),
    )
    return QUESTION


async def ask_question_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to submit the full question again."""
    await update.message.reply_text(
        "❓ Iltimos, savolingizni matn ko'rinishida to'liq yozib qoldiring:",
        reply_markup=user_keyboard(),
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
    )

    if ADMIN_CHAT_ID is None:
        logger.error("ADMIN_CHAT_ID is not configured.")
        context.user_data.clear()
        return ConversationHandler.END

    admin_message = (
        "📩 Yangi savol!\n\n"
        f"ℹ️ Ma'lumot: {context.user_data['info']}\n"
        f"❓ Savol: {context.user_data['question']}"
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

    context.user_data["saved_info"] = context.user_data["info"]
    context.user_data.pop("info", None)
    context.user_data.pop("question", None)
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

        user_info = extract_admin_card_value(query.message.text or "", "ℹ️ Ma'lumot") or "foydalanuvchi"
        pending_responses[ADMIN_CHAT_ID] = {
            "user_chat_id": user_chat_id,
            "user_info": user_info,
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
            f"✍️ Siz ushbu ma'lumot egasiga javob yozyapsiz:\n\n{user_info}\n\nJavobingizni yozing:"
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
            reply_markup=continue_reply_markup(),
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
        reply_markup=continue_reply_markup(),
    )
    await update_admin_question_status(
        context,
        pending_response["admin_message_id"],
        pending_response["admin_message_text"],
        "✅ Javob berildi!",
    )
    user_info = pending_response.get("user_info", "foydalanuvchi")
    await update.message.reply_text(
        f"✅ Javob foydalanuvchiga yuborildi.\n\nℹ️ Ma'lumot: {user_info}",
        reply_markup=admin_repeat_reply_markup(user_chat_id),
    )


async def unexpected_after_form(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start a fresh form when a user sends a new message after finishing."""
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
                filters.Regex(f"^{USER_NEW_QUESTION_BUTTON}$") & ~filters.Chat(ADMIN_CHAT_ID),
                start,
            ),
            CallbackQueryHandler(new_question, pattern="^new_question$"),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~filters.Chat(ADMIN_CHAT_ID),
                unexpected_after_form,
            ),
        ],
        states={
            INFO: [
                CommandHandler("start", start),
                MessageHandler(filters.Regex(f"^{USER_NEW_QUESTION_BUTTON}$"), start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_info),
                MessageHandler(filters.ALL, ask_info_again),
            ],
            QUESTION: [
                CommandHandler("start", start),
                MessageHandler(filters.Regex(f"^{USER_NEW_QUESTION_BUTTON}$"), start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question),
                MessageHandler(filters.ALL, ask_question_again),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        # Keep this false so normal text answers advance the current state.
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
