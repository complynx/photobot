from contextlib import asynccontextmanager
import json
import re
import os
import mimetypes
import tempfile
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, WebAppInfo
from telegram.ext import (
    CallbackContext,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    Application,
)
import logging
from .photo_task import get_by_user, PhotoTask
from .config import Config

logger = logging.getLogger(__name__)

PHOTO, CROPPER = range(2)

def full_link(app: "TGApplication", link: str) -> str:
    link = f"{app.config.server.base}{link}"
    match = re.match(r"http://localhost(:(\d+))?/", link)
    if match:
        port = match.group(2)
        if port is None:
            port = "80"
        # Replace the localhost part with your custom URL and port
        link = re.sub(r"http://localhost(:\d+)?/", f"https://complynx.net/testbot/{port}/", link)
    return link

async def start(update: Update, context: CallbackContext):
    """Send a welcome message when the /start command is issued."""
    logger.info(f"start called: {update.effective_user}")
    await context.bot.set_my_commands([("/avatar", "Создать аватар.")])
    await update.message.reply_markdown(
        "Приветствую. Я — простой бот, который поможет поместить аватарку в рамку. Для этого выбери команду\n"+
        "/avatar"
    )

async def avatar_cmd(update: Update, context: CallbackContext):
    """Handle the /avatar command, requesting a photo."""
    logger.info(f"Received /avatar command from {update.effective_user}")
    await avatar_cancel_inflow(update, context)
    buttons = [["Отмена"]]
    await update.message.reply_text(
        "📸 Отправь мне своё лучшее фото.\n\nP.S. Если в процессе покажется, что я "+
        "уснула, то просто разбуди меня, снова выбрав команду\n/avatar",
        reply_markup = ReplyKeyboardMarkup(
            buttons,
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    return PHOTO

async def avatar_received_image(update: Update, context: CallbackContext):
    """Handle the photo submission as photo"""
    logger.info(f"Received avatar photo from {update.effective_user}")

    photo_file = await update.message.photo[-1].get_file()
    file_name = f"{photo_file.file_id}.jpg"
    file_path = os.path.join(tempfile.gettempdir(), file_name)
    
    await photo_file.download_to_drive(file_path)
    return await avatar_received_stage2(update, context, file_path, "jpg")

async def avatar_received_document_image(update: Update, context: CallbackContext):
    """Handle the photo submission as document"""
    logger.info(f"Received avatar document from {update.effective_user}")

    document = update.message.document

    # Download the document
    document_file = await document.get_file()
    file_ext = mimetypes.guess_extension(document.mime_type)
    file_path = os.path.join(tempfile.gettempdir(), f"{document.file_id}.{file_ext}")
    await document_file.download_to_drive(file_path)
    return await avatar_received_stage2(update, context, file_path, file_ext)

async def avatar_received_stage2(update: Update, context: CallbackContext, file_path:str, file_ext:str):
    await avatar_cancel_inner(update)
    task = PhotoTask(update.effective_chat, update.effective_user)
    task.add_file(file_path, file_ext)
    buttons = [
        [
            KeyboardButton(
                "Выбрать расположение",
                web_app=WebAppInfo(full_link(context.application, f"/fit_frame?id={task.id.hex}"))
            )
        ],
        ["Так сойдёт"],["Отмена"]
    ]


    markup = ReplyKeyboardMarkup(
        buttons,
        resize_keyboard=True,
        one_time_keyboard=True
    )
    logger.debug(f"url: " + full_link(context.application, f"/fit_frame?id={task.id.hex}"))
    await update.message.reply_text(
        "Фото загружено. Выберите как оно будет располагаться внутри рамки.",
        reply_markup=markup
    )
    return CROPPER

async def avatar_crop_auto(update: Update, context: CallbackContext):
    try:
        task = get_by_user(update.effective_user.id)
    except KeyError:
        return await avatar_error(update, context)
    except Exception as e:
        logger.error("Exception in autocrop: %s", e, exc_info=1)
        return await avatar_error(update, context)
    await update.message.reply_text(f"Аватар обрабатывается... 🔄", reply_markup=ReplyKeyboardRemove())
    
    try:
        await task.resize_avatar()
    except Exception as e:
        logger.error("Exception in autocrop: %s", e, exc_info=1)
        return await avatar_error(update, context)
    return await avatar_crop_stage2(task, update, context)

async def avatar_crop_matrix(update: Update, context):
    try:
        task = get_by_user(update.effective_user.id)
    except KeyError:
        return await avatar_error(update, context)
    except Exception as e:
        logger.error("Exception in image_crop_matrix: %s", e, exc_info=1)
        return await avatar_error(update, context)
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        id_str = data['id']
        a = float(data['a'])
        b = float(data['b'])
        c = float(data['c'])
        d = float(data['d'])
        e = float(data['e'])
        f = float(data['f'])
    except Exception as e:
        logger.error("Exception in image_crop_matrix: %s", e, exc_info=1)
        return await avatar_error(update, context)
    if task.id.hex != id_str:
        return await avatar_error(update, context)
    await update.message.reply_text(f"Аватар обрабатывается...", reply_markup=ReplyKeyboardRemove())
    
    try:
        await task.transform_avatar(a,b,c,d,e,f)
    except Exception as e:
        logger.error("Exception in image_crop_matrix: %s", e, exc_info=1)
        return await avatar_error(update, context)
    return await avatar_crop_stage2(task, update, context)

async def avatar_crop_stage2(task: PhotoTask, update: Update, context: CallbackContext):
    try:
        await update.message.reply_text(
            "🪐 Уже совсем скоро твоё чудесное фото станет ещё и космическим! Процесс запущен...",
            reply_markup=ReplyKeyboardRemove()
        )
        await task.finalize_avatar()
        await update.message.reply_document(task.get_final_file(), filename="avatar.jpg")
        await update.message.reply_text(
            "🔁 Если хочешь другое фото, то для этого снова используй команду\n"+
            "/avatar\n\n🛸 Всё готово! До встречи на ZNS! 🐋",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error("Exception in cropped_st2: %s", e, exc_info=1)
        return await avatar_error(update, context)
    
    task.delete()
    return ConversationHandler.END

async def avatar_cancel_inner(update: Update):
    try:
        get_by_user(update.effective_user.id).delete()
        return True
    except KeyError:
        pass
    except Exception as e:
        logger.error("Exception in cancel: %s", e, exc_info=1)
    return False

async def avatar_cancel_inflow(update: Update, context: CallbackContext):
    """Handle the cancel command during the avatar submission."""
    logger.info(f"Avatar submission for {update.effective_user} canceled")
    if await avatar_cancel_inner(update):
        await update.message.reply_text(
            "Уже активированная обработка фотографии отменена.",
            reply_markup=ReplyKeyboardRemove()
        )
    return ConversationHandler.END

async def avatar_cancel_command(update: Update, context: CallbackContext):
    """Handle the cancel command during the avatar submission."""
    logger.info(f"Avatar submission for {update.effective_user} canceled")
    await avatar_cancel_inner(update)
    await update.message.reply_text(
        "Oбработка фотографии отменена.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def avatar_error(update: Update, context: CallbackContext):
    await avatar_cancel_inner(update)
    await update.message.reply_text(
        "Ошибка обработки фото, попробуйте ещё раз.\n/avatar",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def avatar_timeout(update: Update, context: CallbackContext):
    await avatar_cancel_inner(update)
    await update.message.reply_text(
        "Обработка фото отменена, так как долго не было активных действий от пользователя.\n"+
        "Запустить новую можно по команде /avatar",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def log_msg(update: Update, context: CallbackContext):
    logger.info(f"got unparsed update {update}")

async def error_handler(update, context):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

class TGApplication(Application):
    base_app = None
    config: Config

    def __init__(self, base_app, base_config: Config, **kwargs):
        super().__init__(**kwargs)
        self.base_app = base_app
        self.config = base_config

@asynccontextmanager
async def create_telegram_bot(config: Config, app) -> TGApplication:
    global web_app_base
    application = ApplicationBuilder().application_class(TGApplication, kwargs={
        "base_app": app,
        "base_config": config
    }).token(token=config.telegram.token.get_secret_value()).build()

    # Conversation handler for /аватар command
    avatar_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("avatar", avatar_cmd),
        ],
        states={
            PHOTO: [
                MessageHandler(filters.PHOTO, avatar_received_image),
                MessageHandler(filters.Document.IMAGE, avatar_received_document_image),
            ],
            CROPPER: [
                MessageHandler(filters.StatusUpdate.WEB_APP_DATA, avatar_crop_matrix),
                MessageHandler(filters.Regex(re.compile("^(Так сойдёт)$", re.I)), avatar_crop_auto),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, avatar_timeout)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", avatar_cancel_command),
            CommandHandler("avatar", avatar_cancel_command),
            MessageHandler(filters.Regex(re.compile("^(Cancel|Отмена)$", re.I|re.U)), avatar_cancel_command)
        ],
        conversation_timeout=config.photo.conversation_timeout
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(avatar_conversation)
    application.add_handler(MessageHandler(filters.ALL, log_msg))
    application.add_error_handler(error_handler)

    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        app.bot = application
        yield application
    finally:
        app.bot = None
        await application.stop()
        await application.updater.stop()
        await application.shutdown()
