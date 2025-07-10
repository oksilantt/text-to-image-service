import os
import random
import json
import io
import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Авторизация Google Drive и Google Sheets
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
service_account_info = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
credentials = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES
)

drive_service = build('drive', 'v3', credentials=credentials)
sheets_service = build('sheets', 'v4', credentials=credentials)

# Переменные окружения
TEXTS_FOLDER_ID = os.environ.get("READ_FOLDER_ID")
IMAGES_FOLDER_ID = os.environ.get("WRITE_FOLDER_ID")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SPREADSHEET_ID = '1Zuz6XPL6vaglPLNc0f_3Q9QdEVuq2ctjMrxDsDnhDdQ'  # <-- 

WAITING_PHOTO = 1
user_codes = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f""" 👋 Здравствуйте, {update.effective_user.first_name}!
Я рада, что вы согласились поучаствовать в затее по переписыванию Википедии :)

Вот что теперь нужно сделать:
1️⃣ Нажмите /gettext . Вы получите случайный текст. 

✍️ Перепишите этот текст или его фрагмент. Писать можно на любой бумаге, если будут зачеркивания — нестрашно. Пожалуйста, не меняйте инструмент письма, то есть не переходите с ручки на карандаш посередине страницы. 
Слова на иностранном языке лучше заменять на многоточия.

📸 Сфотографируйте результат в хорошем освещении, чётко и сверху. Нужно, чтобы весь лист попадал в кадр. Постарайтесь избежать тени от телефона на листе.

📎 Отправьте фото (JPG или PNG), как вы обычно делаете это в Telegram.

✅ Дождитесь подтверждения загрузки.

Спасибо!

Приступим? Нажимайте /gettext 
"""
    )

async def get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = drive_service.files().list(
        q=f"'{TEXTS_FOLDER_ID}' in parents and mimeType='text/plain'",
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    if not files:
        await update.message.reply_text("Нет текстов.")
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

    # Добавим данные в таблицу
    user_data = [
        str(update.effective_user.id),
        update.effective_user.username or '',
        update.effective_user.first_name or '',
        code,
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ]
    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range='A1',
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body={'values': [user_data]}
    ).execute()

    await update.message.reply_text(f"{text}\n\nВаш код: {code}")
    await update.message.reply_text("Теперь отправьте фото написанного от руки текста (JPG или PNG).")
    return WAITING_PHOTO

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_codes:
        await update.message.reply_text("Сначала получите текст с помощью /gettext.")
        return ConversationHandler.END

    code = user_codes[user_id]
    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        await update.message.reply_text("Отправьте изображение.")
        return WAITING_PHOTO

    file = await context.bot.get_file(photo.file_id)
    ext = '.jpg'

    # Проверка на существующие файлы с таким кодом
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
    await update.message.reply_text("""Фото успешно загружено. 

Спасибо большое за ваш вклад в проект! 
Вы приблизили создание kraken-модели, которая сможет «читать» рукописи на современном русском языке.""")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('gettext', get_text)],
        states={WAITING_PHOTO: [MessageHandler(filters.PHOTO, receive_photo)]},
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
