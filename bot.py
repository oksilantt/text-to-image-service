import os
import random
import io
import json
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from dotenv import load_dotenv
load_dotenv()

# Переменные окружения
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ARCHIVE_CHAT_ID = os.environ.get("ARCHIVE_CHAT_ID")  # Пример: -1001234567890
TEXTS_FOLDER_ID = os.environ.get("READ_FOLDER_ID")
GOOGLE_CREDENTIALS = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))

# Google Drive client
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
credentials = service_account.Credentials.from_service_account_info(
    GOOGLE_CREDENTIALS, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=credentials)

WAITING_PHOTO = 1
user_codes = {}
user_photo_counts = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"""Привет, {update.effective_user.first_name}!
Это бот проекта рукописной Википедии.

Нажмите /gettext — получите текст.
Перепишите его от руки.
Пришлите фото написанного.
"""
    )

async def get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = drive_service.files().list(
        q=f"'{TEXTS_FOLDER_ID}' in parents and mimeType='text/plain' and trashed = false",
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    if not files:
        await update.message.reply_text("Нет доступных текстов.")
        return ConversationHandler.END

    file = random.choice(files)
    file_id = file['id']
    file_name = file['name']
    code = file_name.replace('.txt', '')

    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)
    text = fh.read().decode('utf-8')

    user_id = update.effective_user.id
    user_codes[user_id] = code
    user_photo_counts[user_id] = 0

    await update.message.reply_text(f"{text}\n\nВаш код: {code}")
    await update.message.reply_text("Теперь отправьте фото.")
    return WAITING_PHOTO

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_codes:
        await update.message.reply_text("Сначала получите текст с помощью /gettext.")
        return ConversationHandler.END

    code = user_codes[user_id]
    user_photo_counts[user_id] += 1
    suffix = user_photo_counts[user_id]

    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение.")
        return WAITING_PHOTO

    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()

    caption = f"{code}_{suffix}"

    await context.bot.send_photo(
        chat_id=ARCHIVE_CHAT_ID,
        photo=file_bytes,
        caption=caption
    )

    await update.message.reply_text("Фото принято и отправлено. Спасибо!")
    return ConversationHandler.END

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"chat_id этого чата: {chat_id}")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('gettext', get_text)],
        states={WAITING_PHOTO: [MessageHandler(filters.PHOTO, receive_photo)]},
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", get_chat_id))
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
