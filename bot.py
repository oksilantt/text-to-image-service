import os
import random
import io
import json
from telegram import Update, InputFile
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
ARCHIVE_CHAT_ID = os.environ.get("ARCHIVE_CHAT_ID")  # Пример: -1002722164466
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
    print("‼️ DEBUG UPDATE (start):", update)
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
    print("‼️ DEBUG UPDATE (gettext):", update)
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
    await update.message.reply_text("Теперь отправьте фото написанного от руки текста (JPG или PNG).")
    return WAITING_PHOTO

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("‼️ DEBUG UPDATE (photo):", update)
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
    filename = f"{code}_{suffix}.jpg"
    await file.download_to_drive(filename)

    with open(filename, "rb") as img:
        await context.bot.send_photo(
            chat_id=ARCHIVE_CHAT_ID,
            photo=InputFile(img),
            caption=f"{code}_{suffix}"
        )

    os.remove(filename)
    await update.message.reply_text("Фото успешно загружено. Спасибо большое за ваш вклад в проект! Вы приблизили создание kraken-модели, которая сможет «читать» рукописи на современном русском языке")
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
