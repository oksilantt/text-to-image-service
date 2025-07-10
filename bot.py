import os
import random
import json
import io
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import gspread

# Авторизация Google
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
service_account_info = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
credentials = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)
sheets_client = gspread.authorize(credentials)

# Переменные окружения
TEXTS_FOLDER_ID = os.environ.get("READ_FOLDER_ID")
IMAGES_FOLDER_ID = os.environ.get("WRITE_FOLDER_ID")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SHEET_ID = os.environ.get("SHEET_ID")

WAITING_PHOTO, WAITING_CONSENT = range(2)
user_codes = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"""👋 Здравствуйте, {update.effective_user.first_name}!
Я рада, что вы согласились поучаствовать в затее по переписыванию Википедии :)

Вот что нужно:
1️⃣ Нажмите /gettext — получите случайный текст. 
✍️ Перепишите его от руки.
📸 Сфотографируйте результат сверху, без теней. 
📎 Отправьте фото (JPG/PNG) сюда в чат.
✅ Дождитесь подтверждения загрузки и ответьте, сохранять ли ваш ник.

Нажмите /gettext, чтобы начать.
"""
    )

async def get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = drive_service.files().list(
        q=f"'{TEXTS_FOLDER_ID}' in parents and mimeType='text/plain'",
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    if not files:
        await update.message.reply_text("Нет доступных текстов.")
        return ConversationHandler.END

    file = random.choice(files)
    file_id = file['id']
    file_name = file['name']

    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    text = fh.read().decode('utf-8')

    code = file_name.replace('.txt', '')
    user_codes[update.effective_user.id] = code

    await update.message.reply_text(f"{text}\n\nВаш код: {code}")
    await update.message.reply_text("Теперь отправьте фото написанного текста (JPG или PNG).")
    return WAITING_PHOTO

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_codes:
        await update.message.reply_text("Сначала получите текст с помощью /gettext.")
        return ConversationHandler.END

    code = user_codes[user_id]
    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение.")
        return WAITING_PHOTO

    file = await context.bot.get_file(photo.file_id)
    ext = '.jpg'

    existing_files = drive_service.files().list(
        q=f"'{IMAGES_FOLDER_ID}' in parents and name contains '{code}' and trashed = false",
        fields="files(name)"
    ).execute().get("files", [])

    suffix = len(existing_files) + 1
    filename = f"{code}_{suffix}{ext}"
    await file.download_to_drive(filename)

    file_metadata = {'name': filename, 'parents': [IMAGES_FOLDER_ID]}
    media = MediaFileUpload(filename, mimetype='image/jpeg')
    drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    os.remove(filename)

    keyboard = [
        [InlineKeyboardButton("Да", callback_data="save_nick"),
         InlineKeyboardButton("Нет", callback_data="no_nick")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Фото успешно загружено. Спасибо за вклад!\n\n"
        "Хотите изредка получать новости о проекте?\n"
        "Нажмите «Да», чтобы мы сохранили ваш ник.\n"
        "Или «Нет» — и просто спасибо!",
        reply_markup=reply_markup
    )
    return WAITING_CONSENT

async def handle_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if query.data == "save_nick":
        username = user.username or f"id:{user.id}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet = sheets_client.open_by_key(SHEET_ID).sheet1
        sheet.append_row([username, timestamp])
        await query.edit_message_text("Спасибо! Ник сохранён.")
    else:
        await query.edit_message_text("Спасибо! Ваш вклад уже учтён.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('gettext', get_text)],
        states={
            WAITING_PHOTO: [MessageHandler(filters.PHOTO, receive_photo)],
            WAITING_CONSENT: [CallbackQueryHandler(handle_consent)]
        },
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
