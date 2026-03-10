import os
import asyncio
import logging
import aiohttp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.enums import ChatType

# ====== настройка окружения ======
# если файл называется иначе, передай путь: load_dotenv("gen.env")
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

# ====== инициализация бота ======
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ====== сетевые утилиты ======
async def fetch_json(session, method, url, **kwargs):
    timeout = aiohttp.ClientTimeout(total=30)
    async with session.request(method, url, headers=HEADERS, timeout=timeout, **kwargs) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return await resp.json()

# провайдер 1: tikwm
async def get_from_tikwm(session, tiktok_url: str) -> str | None:
    data = await fetch_json(session, "GET", "https://www.tikwm.com/api/", params={"url": tiktok_url})
    return data.get("data", {}).get("play")  # mp4

# провайдер 2: lovetik
async def get_from_lovetik(session, tiktok_url: str) -> str | None:
    data = await fetch_json(session, "POST", "https://lovetik.com/api/ajax/search", data={"query": tiktok_url})
    links = data.get("links") or []
    for item in links:
        # у них mp4-ссылка в поле "a", подпись "Download" в "s"
        if item.get("a") and str(item.get("s", "")).lower().startswith("download"):
            return item["a"]
    return None

async def resolve_video_url(tiktok_url: str) -> str | None:
    async with aiohttp.ClientSession() as session:
        for provider in (get_from_tikwm, get_from_lovetik):
            try:
                url = await provider(session, tiktok_url)
                if url:
                    return url
            except Exception as e:
                logging.warning("Provider %s failed: %r", provider.__name__, e)
        return None

# ====== обработчики ======

# ГРУППЫ / СУПЕРГРУППЫ — отвечаем только если есть ссылка на TikTok
@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}) & F.text.contains("tiktok.com")
)
async def group_tiktok(message: types.Message):
    url = message.text.strip()
    try:
        mp4 = await resolve_video_url(url)
        if mp4:
            await message.answer_video(mp4)
        # иначе молчим, чтобы не спамить группу
    except asyncio.TimeoutError:
        pass  # молчим в группе при таймауте
    except Exception as e:
        logging.warning("Group handler error: %r", e)

# ЛИЧКА — подсказываем и качаем
@router.message(F.chat.type == ChatType.PRIVATE, F.text)
async def private_text(message: types.Message):
    url = (message.text or "").strip()
    if "tiktok.com" not in url:
        await message.answer("Пришли ссылку на TikTok")
        return

    try:
        mp4 = await resolve_video_url(url)
        if not mp4:
            await message.answer("Не удалось получить видео. Попробуй другую ссылку.")
            return
        await message.answer_video(mp4, caption="Готово")
    except asyncio.TimeoutError:
        await message.answer("Таймаут при обращении к сервисам. Попробуй ещё раз.")
    except Exception as e:
        await message.answer(f"Ошибка сети: {e}")

# ====== запуск ======
async def main():
    if not API_TOKEN:
        raise RuntimeError("BOT_TOKEN не найден. Добавь его в .env (BOT_TOKEN=...)")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())