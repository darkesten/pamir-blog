import asyncio
import os
import re
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
import httpx

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

geo_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
    resize_keyboard=True
)

class PostState(StatesGroup):
    text = State()
    photo = State()
    location = State()

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Я бот для микроблога.\n\nНапиши текст поста:")
    await state.set_state(PostState.text)

@dp.message(PostState.text, F.text)
async def get_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await state.set_state(PostState.photo)
    await message.answer("Отправь фотографию. Или /skip")

@dp.message(PostState.photo, F.photo)
async def get_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer("Фото принято! Ещё или /skip")

@dp.message(PostState.photo, F.text.in_(["/skip"]))
async def skip_photo(message: types.Message, state: FSMContext):
    await state.update_data(photos=[])
    await state.set_state(PostState.location)
    await message.answer("Отправь геопозицию (кнопка внизу) или координаты: 39.723, 73.247\nИли /skip", reply_markup=geo_keyboard)

@dp.message(PostState.photo)
async def photo_unknown(message: types.Message):
    await message.answer("Пришли фото или /skip")

@dp.message(PostState.location, F.location)
async def get_location(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lng=message.location.longitude)
    await finish_post(message, state)

@dp.message(PostState.location, F.text)
async def get_location_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    match = re.match(r"^([\d\.\-]+)\s*[,;:\s]+\s*([\d\.\-]+)$", text)
    if match:
        await state.update_data(lat=float(match.group(1)), lng=float(match.group(2)))
        await finish_post(message, state)
    else:
        await message.answer("Напиши: 39.7236, 73.2470")

@dp.message(PostState.location, F.text.in_(["/skip"]))
async def skip_location(message: types.Message, state: FSMContext):
    await state.update_data(lat=None, lng=None)
    await finish_post(message, state)

async def finish_post(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "")
    photos = data.get("photos", [])
    lat = data.get("lat")
    lng = data.get("lng")
    await message.answer("Сохраняю...", reply_markup=ReplyKeyboardRemove())
    try:
        async with httpx.AsyncClient() as client:
            image_urls = []
            for i, file_id in enumerate(photos):
                file = await bot.get_file(file_id)
                file_bytes = await bot.download_file(file.file_path)
                filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{i}.jpg"
                upload = await client.post(
                    f"{SUPABASE_URL}/storage/v1/object/photos/{filename}",
                    headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
                    content=file_bytes.read()
                )
                if upload.status_code in (200, 201):
                    image_urls.append(f"{SUPABASE_URL}/storage/v1/object/photos/{filename}")
            await client.post(
                f"{SUPABASE_URL}/rest/v1/posts",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "Prefer": "return=minimal"},
                json={"text": text, "image_urls": image_urls if image_urls else None, "lat": lat, "lng": lng, "local_time_str": datetime.utcnow().strftime("%d %B, %H:%M")}
            )
            await message.answer("✅ Пост опубликован!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Ещё пост", callback_data="new_post")]])
    await message.answer("Что дальше?", reply_markup=markup)

@dp.callback_query(F.data == "new_post")
async def new_post(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.answer("Напиши текст поста:")
    await state.set_state(PostState.text)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
