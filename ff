import asyncio
import logging
import random
from datetime import datetime, timedelta

from aiogram.client.default import DefaultBotProperties
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

from config import (
    BOT_TOKEN, ADMIN_IDS, CARD_NUMBER, CARD_OWNER, VIP_PRICE,
    CHANNEL_ID, CHANNEL_USERNAME, MIN_REFERRALS_FOR_BONUS
)
from db import (
    get_or_create_user, get_user, update_streak, add_score, add_referral_earnings,
    add_learned_word, set_vip, is_vip, create_vip_request,
    get_stats, get_all_user_ids, get_top_scores, get_top_referrals,
    update_user_level, update_user_group,
    get_pending_vip_requests, update_vip_request_status,
    get_expired_vip_users, get_expiring_soon_vip_users
)
from words import words

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher(storage=MemoryStorage())

# ══════════════════════════════════════════════════
# FSM STATES
# ══════════════════════════════════════════════════
class QuizState(StatesGroup):
    answering = State()

class GrammarQuizState(StatesGroup):
    answering = State()

class VipState(StatesGroup):
    waiting_name  = State()
    waiting_check = State()

class BroadcastState(StatesGroup):
    waiting = State()

# ══════════════════════════════════════════════════
# GRAMMAR MA'LUMOTLARI
# ══════════════════════════════════════════════════
GRAMMAR_TOPICS = [
    {
        "id": "present_simple",
        "name": "🕐 Present Simple",
        "emoji": "🕐",
        "explanation": (
            "🕐 <b>PRESENT SIMPLE</b> — Oddiy hozirgi zamon\n\n"
            "📌 <b>Qachon ishlatiladi?</b>\n"
            "✅ Odatiy harakatlar uchun\n"
            "✅ Haqiqatlar va qonunlar uchun\n"
            "✅ Jadvallar va kundalik rutina\n\n"
            "📐 <b>Qoida:</b>\n"
            "➕ I/You/We/They + <b>V1</b>\n"
            "➕ He/She/It + <b>V1+s/es</b>\n"
            "➖ do/does + not + V1\n"
            "❓ Do/Does + subject + V1?\n\n"
            "💡 <b>Misollar:</b>\n"
            "• I <b>work</b> every day. (Men har kuni ishlayman)\n"
            "• She <b>speaks</b> English well. (U inglizni yaxshi gapiradi)\n"
            "• They <b>don't</b> like coffee. (Ular qahvani yoqtirmaydi)\n"
            "• <b>Does</b> he play football? (U futbol o'ynaydimi?)\n\n"
            "⚡️ <b>Esda saqlang:</b> He/She/It bilan fe'l oxiriga <b>-s/-es</b> qo'shiladi!"
        ),
        "questions": [
            {
                "q": "She ___ to school every day.",
                "options": ["go", "goes", "going", "gone"],
                "answer": "goes",
                "explanation": "He/She/It bilan fe'lga -s qo'shiladi: goes ✅"
            },
            {
                "q": "They ___ not like pizza.",
                "options": ["do", "does", "did", "is"],
                "answer": "do",
                "explanation": "They bilan inkor: do not ✅"
            },
            {
                "q": "___ he speak English?",
                "options": ["Do", "Does", "Did", "Is"],
                "answer": "Does",
                "explanation": "He bilan savol: Does ✅"
            },
            {
                "q": "The sun ___ in the east.",
                "options": ["rise", "rises", "rising", "rose"],
                "answer": "rises",
                "explanation": "Haqiqat: The sun rises - quyosh chiqadi ✅"
            },
            {
                "q": "I ___ coffee every morning.",
                "options": ["drink", "drinks", "drinking", "drank"],
                "answer": "drink",
                "explanation": "I bilan: drink (s qo'shilmaydi) ✅"
            },
        ]
    },
    {
        "id": "present_continuous",
        "name": "▶️ Present Continuous",
        "emoji": "▶️",
        "explanation": (
            "▶️ <b>PRESENT CONTINUOUS</b> — Davomli hozirgi zamon\n\n"
            "📌 <b>Qachon ishlatiladi?</b>\n"
            "✅ Ayni shu paytda bo'layotgan harakat\n"
            "✅ Vaqtincha bo'layotgan holat\n"
            "✅ Kelasi rejalashtirilgan harakat\n\n"
            "📐 <b>Qoida:</b>\n"
            "➕ Subject + <b>am/is/are + V-ing</b>\n"
            "➖ am/is/are + not + V-ing\n"
            "❓ Am/Is/Are + subject + V-ing?\n\n"
            "💡 <b>Misollar:</b>\n"
            "• I <b>am studying</b> right now. (Hozir o'qiyapman)\n"
            "• She <b>is cooking</b> dinner. (U kechki ovqat tayyorlamoqda)\n"
            "• They <b>are not sleeping</b>. (Ular uxlamayapti)\n"
            "• <b>Are</b> you listening? (Eshityapsizmi?)\n\n"
            "⚡️ <b>Kalit so'zlar:</b> now, right now, at the moment, currently, look!, listen!"
        ),
        "questions": [
            {
                "q": "She ___ (read) a book right now.",
                "options": ["reads", "is reading", "read", "was reading"],
                "answer": "is reading",
                "explanation": "Hozir bo'layotgan harakat: is reading ✅"
            },
            {
                "q": "They ___ (play) football at the moment.",
                "options": ["play", "played", "are playing", "have played"],
                "answer": "are playing",
                "explanation": "They + are playing (hozirgi vaqt) ✅"
            },
            {
                "q": "___ you listening to me?",
                "options": ["Do", "Does", "Are", "Is"],
                "answer": "Are",
                "explanation": "You bilan: Are you...? ✅"
            },
            {
                "q": "Look! It ___ (rain) outside.",
                "options": ["rains", "is raining", "rained", "has rained"],
                "answer": "is raining",
                "explanation": "Look! - hozir ko'rilayotgan holat: is raining ✅"
            },
            {
                "q": "I ___ not watching TV now.",
                "options": ["do", "does", "am", "are"],
                "answer": "am",
                "explanation": "I bilan: I am not watching ✅"
            },
        ]
    },
    {
        "id": "past_simple",
        "name": "⏮ Past Simple",
        "emoji": "⏮",
        "explanation": (
            "⏮ <b>PAST SIMPLE</b> — Oddiy o'tgan zamon\n\n"
            "📌 <b>Qachon ishlatiladi?</b>\n"
            "✅ O'tgan paytda tugallangan harakat\n"
            "✅ Ketma-ket o'tgan harakatlar\n"
            "✅ O'tmishdagi odatlar\n\n"
            "📐 <b>Qoida:</b>\n"
            "➕ Subject + <b>V2</b> (regular: V+ed)\n"
            "➖ Subject + <b>did not</b> + V1\n"
            "❓ <b>Did</b> + subject + V1?\n\n"
            "💡 <b>Misollar:</b>\n"
            "• I <b>worked</b> yesterday. (Kecha ishladim)\n"
            "• She <b>went</b> to Paris. (U Parijga bordi)\n"
            "• He <b>didn't</b> call me. (U menga qo'ng'iroq qilmadi)\n"
            "• <b>Did</b> you see the movie? (Filmni ko'rdingizmi?)\n\n"
            "⚡️ <b>Kalit so'zlar:</b> yesterday, last week/year, ago, in 2020"
        ),
        "questions": [
            {
                "q": "She ___ (go) to school yesterday.",
                "options": ["go", "goes", "went", "gone"],
                "answer": "went",
                "explanation": "Go ning V2 shakli: went ✅"
            },
            {
                "q": "I ___ not see him last night.",
                "options": ["do", "does", "did", "was"],
                "answer": "did",
                "explanation": "Past Simple inkor: did not ✅"
            },
            {
                "q": "___ you call me yesterday?",
                "options": ["Do", "Does", "Did", "Were"],
                "answer": "Did",
                "explanation": "Past Simple savol: Did ✅"
            },
            {
                "q": "They ___ (watch) TV last night.",
                "options": ["watch", "watches", "watched", "watching"],
                "answer": "watched",
                "explanation": "Regular fe'l + ed: watched ✅"
            },
            {
                "q": "He ___ (buy) a car two years ago.",
                "options": ["buys", "buy", "bought", "buying"],
                "answer": "bought",
                "explanation": "Buy ning V2 shakli: bought ✅"
            },
        ]
    },
    {
        "id": "past_continuous",
        "name": "⏸ Past Continuous",
        "emoji": "⏸",
        "explanation": (
            "⏸ <b>PAST CONTINUOUS</b> — Davomli o'tgan zamon\n\n"
            "📌 <b>Qachon ishlatiladi?</b>\n"
            "✅ O'tmishda ma'lum vaqtda davom etgan harakat\n"
            "✅ Bitta harakat bo'layotganda boshqasi kelib qoldi (when/while)\n"
            "✅ O'tmishdagi parallel harakatlar\n\n"
            "📐 <b>Qoida:</b>\n"
            "➕ Subject + <b>was/were + V-ing</b>\n"
            "➖ was/were + not + V-ing\n"
            "❓ Was/Were + subject + V-ing?\n\n"
            "💡 <b>Misollar:</b>\n"
            "• I <b>was sleeping</b> at 10 pm. (Soat 22:00 da uxlayotgan edim)\n"
            "• They <b>were playing</b> when I arrived. (Men kelganimda o'ynayotgan edi)\n"
            "• She <b>was not studying</b>. (U o'qiyotgan emasdi)\n\n"
            "⚡️ <b>Kalit so'zlar:</b> while, when, at that moment, all day long"
        ),
        "questions": [
            {
                "q": "I ___ (sleep) when you called.",
                "options": ["sleep", "slept", "was sleeping", "am sleeping"],
                "answer": "was sleeping",
                "explanation": "O'tmishda davom etgan harakat: was sleeping ✅"
            },
            {
                "q": "They ___ (study) all evening yesterday.",
                "options": ["study", "studied", "were studying", "are studying"],
                "answer": "were studying",
                "explanation": "They + were studying (o'tmishda davom etgan) ✅"
            },
            {
                "q": "___ she cooking when you arrived?",
                "options": ["Did", "Was", "Were", "Is"],
                "answer": "Was",
                "explanation": "She bilan: Was she...? ✅"
            },
            {
                "q": "While I ___ (read), he came in.",
                "options": ["read", "reads", "was reading", "am reading"],
                "answer": "was reading",
                "explanation": "While + o'tmish davomli: was reading ✅"
            },
            {
                "q": "We ___ not watching TV at midnight.",
                "options": ["did", "were", "was", "are"],
                "answer": "were",
                "explanation": "We bilan: were not watching ✅"
            },
        ]
    },
    {
        "id": "present_perfect",
        "name": "✨ Present Perfect",
        "emoji": "✨",
        "explanation": (
            "✨ <b>PRESENT PERFECT</b> — Tugallangan hozirgi zamon\n\n"
            "📌 <b>Qachon ishlatiladi?</b>\n"
            "✅ Natijasi hozirga ta'sir qilgan o'tgan harakat\n"
            "✅ Hayotda bo'lgan/bo'lmagan tajriba\n"
            "✅ Endigina tugagan harakat (just, already, yet)\n\n"
            "📐 <b>Qoida:</b>\n"
            "➕ Subject + <b>have/has + V3</b>\n"
            "➖ have/has + not + V3\n"
            "❓ Have/Has + subject + V3?\n\n"
            "💡 <b>Misollar:</b>\n"
            "• I <b>have visited</b> London. (Londonda bo'lganman)\n"
            "• She <b>has finished</b> her work. (U ishini tugatdi)\n"
            "• <b>Have</b> you ever eaten sushi? (Hech sushi yegansizmi?)\n"
            "• He <b>has just</b> arrived. (U hozirgina keldi)\n\n"
            "⚡️ <b>Kalit so'zlar:</b> ever, never, just, already, yet, since, for"
        ),
        "questions": [
            {
                "q": "She ___ (finish) her homework already.",
                "options": ["finish", "finished", "has finished", "have finished"],
                "answer": "has finished",
                "explanation": "She + has + V3: has finished ✅"
            },
            {
                "q": "I ___ never been to Japan.",
                "options": ["have", "has", "had", "did"],
                "answer": "have",
                "explanation": "I bilan: have never been ✅"
            },
            {
                "q": "___ you ever tried Indian food?",
                "options": ["Did", "Do", "Have", "Has"],
                "answer": "Have",
                "explanation": "You bilan tajriba so'rash: Have you ever...? ✅"
            },
            {
                "q": "He ___ just left the office.",
                "options": ["have", "has", "had", "did"],
                "answer": "has",
                "explanation": "He + has just: has just left ✅"
            },
            {
                "q": "They ___ not seen this movie yet.",
                "options": ["have", "has", "had", "did"],
                "answer": "have",
                "explanation": "They + have not: have not seen yet ✅"
            },
        ]
    },
    {
        "id": "future_simple",
        "name": "🔮 Future Simple",
        "emoji": "🔮",
        "explanation": (
            "🔮 <b>FUTURE SIMPLE</b> — Oddiy kelasi zamon\n\n"
            "📌 <b>Qachon ishlatiladi?</b>\n"
            "✅ Spontan qarorlar (hozir qabul qilindi)\n"
            "✅ Bashoratlar va taxminlar\n"
            "✅ Va'da va tahdidlar\n"
            "✅ Iltimoslar va takliflar\n\n"
            "📐 <b>Qoida:</b>\n"
            "➕ Subject + <b>will + V1</b>\n"
            "➖ Subject + <b>will not (won't)</b> + V1\n"
            "❓ <b>Will</b> + subject + V1?\n\n"
            "💡 <b>Misollar:</b>\n"
            "• I <b>will call</b> you tomorrow. (Ertaga qo'ng'iroq qilaman)\n"
            "• It <b>will rain</b> today. (Bugun yomg'ir yog'adi)\n"
            "• She <b>won't</b> come. (U kelmaydi)\n"
            "• <b>Will</b> you help me? (Menga yordam berасizmi?)\n\n"
            "⚡️ <b>Kalit so'zlar:</b> tomorrow, next week/year, soon, in the future, I think, probably"
        ),
        "questions": [
            {
                "q": "I think it ___ rain tomorrow.",
                "options": ["is", "was", "will", "would"],
                "answer": "will",
                "explanation": "Kelasi zamon bashorat: will rain ✅"
            },
            {
                "q": "She ___ not come to the party.",
                "options": ["will", "would", "shall", "should"],
                "answer": "will",
                "explanation": "Inkor: will not (won't) come ✅"
            },
            {
                "q": "___ you help me with this?",
                "options": ["Do", "Did", "Will", "Have"],
                "answer": "Will",
                "explanation": "Kelasi zamon iltimos: Will you...? ✅"
            },
            {
                "q": "I ___ call you as soon as I arrive.",
                "options": ["call", "called", "will call", "have called"],
                "answer": "will call",
                "explanation": "Kelasi va'da: will call ✅"
            },
            {
                "q": "They ___ (not finish) the project next week.",
                "options": ["don't finish", "didn't finish", "won't finish", "haven't finished"],
                "answer": "won't finish",
                "explanation": "Kelasi inkor: won't finish ✅"
            },
        ]
    },
]

# ══════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════
def main_kb(user_id: int = None):
    vip      = is_vip(user_id) if user_id else False
    is_admin = user_id in ADMIN_IDS if user_id else False
    buttons = [
        [KeyboardButton(text="📚 So'z o'rgan"),   KeyboardButton(text="🧠 Test")],
        [KeyboardButton(text="📖 Grammatika"),     KeyboardButton(text="🔥 Streak")],
        [KeyboardButton(text="🏆 Reyting"),        KeyboardButton(text="👥 Referal")],
        [KeyboardButton(text="⚙️ Daraja")],
    ]
    if is_admin or vip:
        buttons.append([KeyboardButton(text="💎 VIP Panel")])
    else:
        buttons.append([KeyboardButton(text="💎 VIP Sotib olish")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def level_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Boshlang'ich",  callback_data="level_beginner")],
        [InlineKeyboardButton(text="🟡 O'rta daraja",  callback_data="level_intermediate")],
        [InlineKeyboardButton(text="🔴 Yuqori daraja", callback_data="level_advanced")],
    ])

def back_to_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]
    ])

def word_card_kb(group_num: int, remaining: int):
    """So'z kartasi tugmalari"""
    row1 = [InlineKeyboardButton(text="➡️ Keyingi so'z", callback_data="next_word")]
    row2 = [InlineKeyboardButton(text="🧠 Shu guruhni test qilish", callback_data=f"group_quiz_{group_num}")]
    row3 = [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2, row3])

# ══════════════════════════════════════════════════
# MAJBURIY KANAL
# ══════════════════════════════════════════════════
async def check_subscription(user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception as e:
        logger.error(f"Kanal tekshiruv xatosi: {e}")
        return True

def subscribe_kb() -> InlineKeyboardMarkup:
    ch = CHANNEL_USERNAME.lstrip('@') if CHANNEL_USERNAME else ""
    url = f"https://t.me/{ch}" if ch else "https://t.me/"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=url)],
        [InlineKeyboardButton(text="✅ Tekshirish",            callback_data="check_sub")],
    ])

# ══════════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════════
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject = None):
    user_id  = message.from_user.id
    name     = message.from_user.first_name or "Do'st"
    username = message.from_user.username or ""

    ref_id = None
    if command and command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id == user_id:
            ref_id = None

    user = get_or_create_user(user_id, name, username, ref_id)
    update_streak(user_id)

    if not await check_subscription(user_id):
        await message.answer(
            f"👋 Salom, <b>{name}</b>!\n\n"
            f"🔐 Botdan to'liq foydalanish uchun\n"
            f"avval kanalimizga obuna bo'ling 👇\n\n"
            f"<i>Obuna bo'lgach '✅ Tekshirish' tugmasini bosing</i>",
            reply_markup=subscribe_kb()
        )
        return

    if ref_id:
        try:
            await bot.send_message(
                ref_id,
                f"🎉 Siz taklif qilgan <b>{name}</b> botga qo'shildi!\n"
                f"👥 Referal hisobingiz yangilandi!"
            )
        except Exception:
            pass

    if not user.get("level"):
        await message.answer(
            f"🎉 Xush kelibsiz, <b>{name}</b>!\n\n"
            f"🚀 LexoBot — ingliz tilini o'rganishning\n"
            f"eng qulay yo'li!\n\n"
            f"📊 Avval darajangizni tanlang:",
            reply_markup=level_kb()
        )
    else:
        await message.answer(
            f"👋 Qaytib keldingiz, <b>{name}</b>! 🔥\n\n"
            f"O'rganishni davom ettiramizmi? 💪",
            reply_markup=main_kb(user_id)
        )

@dp.callback_query(F.data == "check_sub")
async def check_sub_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.delete()
        user = get_user(user_id)
        if not user or not user.get("level"):
            await callback.message.answer(
                "✅ Rahmat! Darajangizni tanlang:",
                reply_markup=level_kb()
            )
        else:
            await callback.message.answer(
                "✅ Zo'r! Xush kelibsiz! 🎉",
                reply_markup=main_kb(user_id)
            )
    else:
        await callback.answer("❗ Hali obuna bo'lmadingiz!", show_alert=True)

@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    await callback.message.answer(
        "🏠 <b>Bosh menyu</b>",
        reply_markup=main_kb(user_id)
    )
    await callback.answer()

# ══════════════════════════════════════════════════
# DARAJA
# ══════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("level_"))
async def set_level(callback: types.CallbackQuery):
    level_map = {
        "beginner":     "🟢 Boshlang'ich",
        "intermediate": "🟡 O'rta daraja",
        "advanced":     "🔴 Yuqori daraja",
    }
    level   = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    update_user_level(user_id, level)
    await callback.answer(f"✅ {level_map.get(level, level)}")
    await callback.message.edit_text(
        f"✅ Daraja belgilandi: <b>{level_map.get(level, level)}</b>\n\n"
        f"🚀 Endi o'rganishni boshlashingiz mumkin!"
    )
    await callback.message.answer(
        "📚 Quyidagi bo'limlardan birini tanlang:",
        reply_markup=main_kb(user_id)
    )

@dp.message(F.text == "⚙️ Daraja")
async def change_level(message: types.Message):
    await message.answer(
        "⚙️ <b>DARAJA O'ZGARTIRISH</b>\n\n"
        "Yangi darajangizni tanlang:",
        reply_markup=level_kb()
    )

# ══════════════════════════════════════════════════
# SO'Z O'RGANISH — TO'LIQ TUZATILGAN
# ══════════════════════════════════════════════════
@dp.message(F.text == "📚 So'z o'rgan")
async def learn_word(message: types.Message):
    user_id = message.from_user.id
    user    = get_user(user_id)
    if not user or not user.get("level"):
        await message.answer("⚙️ Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    await _send_next_word(message, user_id, edit=False)

@dp.callback_query(F.data == "next_word")
async def next_word_cb(callback: types.CallbackQuery):
    await _send_next_word(callback.message, callback.from_user.id, edit=True)
    await callback.answer()

async def _send_next_word(target, user_id: int, edit: bool = False):
    user      = get_user(user_id)
    if not user:
        return
    level     = user.get("level", "beginner")
    group_num = user.get("current_group", 1)

    level_names = {
        "beginner":     "🟢 Boshlang'ich",
        "intermediate": "🟡 O'rta",
        "advanced":     "🔴 Yuqori",
    }

    all_words   = words.get(level, [])
    start_idx   = (group_num - 1) * 20
    end_idx     = start_idx + 20
    group_words = all_words[start_idx:end_idx]

    if not group_words:
        txt = (
            "🎊 <b>BARAKALLO!</b> 🎊\n\n"
            "🏆 Siz ushbu daraja so'zlarini\n"
            "to'liq tugatdingiz!\n\n"
            "⚙️ Darajani o'zgartiring yoki\n"
            "grammatika bo'limini sinab ko'ring!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Darajani o'zgartirish", callback_data="change_level_menu")],
            [InlineKeyboardButton(text="📖 Grammatika",             callback_data="grammar_menu")],
        ])
        if edit:
            await target.edit_text(txt, reply_markup=kb)
        else:
            await target.answer(txt, reply_markup=kb)
        return

    learned   = user.get("learned_words") or []
    unlearned = [w for w in group_words if w["word"] not in learned]

    if not unlearned:
        # Guruh tugadi
        vip_user = is_vip(user_id)
        if vip_user:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔓 Keyingi guruhni ochish", callback_data="next_group")],
                [InlineKeyboardButton(text="🔄 So'zlarni takrorlash",   callback_data="review_words")],
                [InlineKeyboardButton(text="🏠 Bosh menyu",             callback_data="back_menu")],
            ])
            txt = (
                f"🎯 <b>{group_num}-guruh tugadi!</b>\n\n"
                f"✅ 20 ta so'zni o'rgandingiz\n"
                f"💎 VIP sifatida test topshirmasdan\n"
                f"keyingi guruhga o'tishingiz mumkin! 🚀"
            )
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🧠 {group_num}-guruh testini topshirish",
                    callback_data=f"group_quiz_{group_num}"
                )],
                [InlineKeyboardButton(text="🔄 So'zlarni takrorlash", callback_data="review_words")],
                [InlineKeyboardButton(text="🏠 Bosh menyu",           callback_data="back_menu")],
            ])
            txt = (
                f"📚 <b>{group_num}-guruh so'zlari tugadi!</b>\n\n"
                f"✅ 20 ta so'zni o'qib chiqdingiz!\n\n"
                f"🔒 Keyingi guruh uchun testdan\n"
                f"<b>kamida 70% to'g'ri</b> javob bering\n\n"
                f"💡 <i>VIP bo'ling — testisiz o'ting! 💎</i>"
            )
        if edit:
            await target.edit_text(txt, reply_markup=kb)
        else:
            await target.answer(txt, reply_markup=kb)
        return

    word_data = unlearned[0]
    add_learned_word(user_id, word_data["word"])
    add_score(user_id, 2)

    remaining  = len(unlearned) - 1
    total_done = len(learned) + 1
    progress   = min(20, total_done - start_idx)
    bar        = "🟩" * progress + "⬜" * (20 - progress)

    kb = word_card_kb(group_num, remaining)

    level_label = level_names.get(level, level)
    txt = (
        f"📚 <b>SO'Z O'RGANISH</b>\n"
        f"{level_label}  |  📦 Guruh {group_num}  |  🔢 Qoldi: {remaining}\n"
        f"{bar}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🇬🇧  <b>{word_data['word'].upper()}</b>\n"
        f"🇺🇿  <b>{word_data['translation']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💬 <i>{word_data['example']}</i>\n\n"
        f"⭐️ +2 ball qo'shildi!"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "review_words")
async def review_words_cb(callback: types.CallbackQuery):
    """O'rganilgan so'zlarni takrorlash"""
    user_id = callback.from_user.id
    user    = get_user(user_id)
    level   = user.get("level", "beginner")
    group_num = user.get("current_group", 1)

    all_words   = words.get(level, [])
    start_idx   = (group_num - 1) * 20
    end_idx     = start_idx + 20
    group_words = all_words[start_idx:end_idx]
    learned     = user.get("learned_words") or []
    done_words  = [w for w in group_words if w["word"] in learned]

    if not done_words:
        await callback.answer("Hali so'z o'rganilmagan!", show_alert=True)
        return

    text = f"📖 <b>{group_num}-guruh so'zlari:</b>\n\n"
    for i, w in enumerate(done_words, 1):
        text += f"{i}. 🇬🇧 <b>{w['word']}</b> — 🇺🇿 {w['translation']}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Test boshlash",      callback_data=f"group_quiz_{group_num}")],
        [InlineKeyboardButton(text="➡️ O'rganishni davom", callback_data="next_word")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",         callback_data="back_menu")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "next_group")
async def next_group_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user    = get_user(user_id)
    if not is_vip(user_id):
        await callback.answer("💎 Bu imkoniyat faqat VIP uchun!", show_alert=True)
        return
    new_group = (user.get("current_group") or 1) + 1
    update_user_group(user_id, new_group)
    await callback.message.edit_text(
        f"🚀 <b>{new_group}-guruh ochildi!</b>\n\n"
        f"✨ Yangi 20 ta so'z sizni kutmoqda!\n"
        f"💎 VIP bilan o'rganish tezroq!"
    )
    await callback.answer("✅ Yangi guruh ochildi!")

@dp.callback_query(F.data == "change_level_menu")
async def change_level_menu_cb(callback: types.CallbackQuery):
    await callback.message.edit_text("⚙️ Yangi darajani tanlang:", reply_markup=level_kb())

# ══════════════════════════════════════════════════
# GURUH TESTI (so'z o'rganish bo'limidan)
# ══════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("group_quiz_"))
async def group_quiz_start(callback: types.CallbackQuery, state: FSMContext):
    user_id   = callback.from_user.id
    user      = get_user(user_id)
    group_num = int(callback.data.split("_")[2])
    level     = user.get("level", "beginner")

    all_words   = words.get(level, [])
    start_idx   = (group_num - 1) * 20
    group_words = all_words[start_idx:start_idx + 20]
    learned     = user.get("learned_words") or []
    # Faqat o'rganilgan so'zlardan test
    test_pool = [w for w in group_words if w["word"] in learned]

    if len(test_pool) < 4:
        await callback.answer("⚠️ Kamida 4 ta so'z o'rganing!", show_alert=True)
        return

    total = min(10, len(test_pool))
    await state.set_state(QuizState.answering)
    await state.update_data(
        q_num=1, total=total, correct_count=0,
        level=level,
        group_quiz=True,
        group_num=group_num,
        group_words=[w["word"] for w in test_pool]
    )
    await _send_group_quiz(callback.message, user_id, state, edit=True)
    await callback.answer()

async def _send_group_quiz(target, user_id: int, state: FSMContext, edit: bool = False):
    data            = await state.get_data()
    q_num           = data.get("q_num", 1)
    total           = data.get("total", 10)
    correct_count   = data.get("correct_count", 0)
    level           = data.get("level", "beginner")
    group_word_keys = data.get("group_words", [])
    group_num       = data.get("group_num", 1)

    all_words  = words.get(level, [])
    group_pool = [w for w in all_words if w["word"] in group_word_keys]

    if len(group_pool) < 4:
        extra = [w for w in all_words if w["word"] not in group_word_keys]
        group_pool += extra

    correct      = random.choice(group_pool)
    wrong_pool   = [w for w in group_pool if w["word"] != correct["word"]]
    if len(wrong_pool) < 3:
        extra = [w for w in all_words if w["word"] != correct["word"] and w not in wrong_pool]
        wrong_pool += extra
    wrong_sample = random.sample(wrong_pool, 3)
    options      = [correct] + wrong_sample
    random.shuffle(options)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=opt["translation"],
            callback_data=f"gqa_{opt['word']}_{correct['word']}"
        )]
        for opt in options
    ] + [[InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]])

    progress = "🟩" * correct_count + "⬜" * (total - correct_count)
    txt = (
        f"🧠 <b>GURUH TESTI</b> — {group_num}-guruh\n"
        f"📊 {q_num}/{total}  {progress}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🇬🇧 <b>{correct['word'].upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"❓ Tarjimasini toping:"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data.startswith("gqa_"), QuizState.answering)
async def group_quiz_answer(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    parts   = callback.data.split("_")
    chosen  = parts[1]
    correct = parts[2]

    data          = await state.get_data()
    q_num         = data.get("q_num", 1)
    total         = data.get("total", 10)
    correct_count = data.get("correct_count", 0)
    group_num     = data.get("group_num", 1)

    if chosen == correct:
        correct_count += 1
        add_score(user_id, 5)
        await callback.answer("✅ To'g'ri! +5 ball 🎉")
    else:
        await callback.answer(f"❌ Noto'g'ri! To'g'ri: {correct}", show_alert=True)

    if q_num >= total:
        await state.clear()
        percent = int((correct_count / total) * 100)
        passed  = percent >= 70

        if passed:
            new_group = group_num + 1
            update_user_group(user_id, new_group)
            emoji = "🏆" if percent == 100 else ("🥇" if percent >= 90 else "🎉")
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📚 Keyingi guruhni boshlash", callback_data="next_word")],
                [InlineKeyboardButton(text="🏠 Bosh menyu",               callback_data="back_menu")],
            ])
            await callback.message.edit_text(
                f"{emoji} <b>TEST O'TKAZILDI!</b>\n\n"
                f"✅ To'g'ri: <b>{correct_count}/{total}</b>\n"
                f"📊 Natija: <b>{percent}%</b>\n\n"
                f"🔓 <b>{new_group}-guruh ochildi!</b>\n"
                f"🚀 Yangi so'zlar sizi kutmoqda!",
                reply_markup=kb
            )
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Qaytadan urinish",     callback_data=f"group_quiz_{group_num}")],
                [InlineKeyboardButton(text="📖 So'zlarni takrorlash", callback_data="review_words")],
                [InlineKeyboardButton(text="🏠 Bosh menyu",           callback_data="back_menu")],
            ])
            await callback.message.edit_text(
                f"😔 <b>Test o'tmadi!</b>\n\n"
                f"❌ To'g'ri: <b>{correct_count}/{total}</b>\n"
                f"📊 Natija: <b>{percent}%</b>\n\n"
                f"⚠️ Keyingi guruh uchun <b>70%</b> kerak\n\n"
                f"💡 So'zlarni takrorlab, qayta urining!\n"
                f"💎 <i>VIP oling — testisiz o'ting!</i>",
                reply_markup=kb
            )
    else:
        await state.update_data(q_num=q_num + 1, correct_count=correct_count)
        await _send_group_quiz(callback.message, user_id, state, edit=True)

# ══════════════════════════════════════════════════
# ERKIN TEST (o'rganilgan barcha so'zlardan)
# ══════════════════════════════════════════════════
@dp.message(F.text == "🧠 Test")
async def start_quiz(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user or not user.get("level"):
        await message.answer("⚙️ Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    learned = user.get("learned_words") or []
    if len(learned) < 4:
        await message.answer(
            "⚠️ <b>So'zlar yetarli emas!</b>\n\n"
            "Test uchun kamida <b>4 ta so'z</b> o'rganing.\n"
            "📚 So'z o'rgan bo'limiga o'ting!"
        )
        return
    await state.set_state(QuizState.answering)
    await state.update_data(
        q_num=1, total=10, correct_count=0,
        level=user["level"],
        group_quiz=False,
        use_learned=True,
        learned_words=learned
    )
    await _send_free_quiz(message, message.from_user.id, state, edit=False)

@dp.callback_query(F.data == "quiz_start")
async def quiz_start_cb(callback: types.CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if not user or not user.get("level"):
        await callback.message.answer("⚙️ Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    learned = user.get("learned_words") or []
    if len(learned) < 4:
        await callback.message.answer(
            "⚠️ Kamida 4 ta so'z o'rganing!\n📚 So'z o'rgan bo'limiga o'ting."
        )
        return
    await state.set_state(QuizState.answering)
    await state.update_data(
        q_num=1, total=10, correct_count=0,
        level=user["level"],
        group_quiz=False,
        use_learned=True,
        learned_words=learned
    )
    await _send_free_quiz(callback.message, callback.from_user.id, state, edit=False)
    await callback.answer()

async def _send_free_quiz(target, user_id: int, state: FSMContext, edit: bool = False):
    data          = await state.get_data()
    q_num         = data.get("q_num", 1)
    total         = data.get("total", 10)
    correct_count = data.get("correct_count", 0)
    level         = data.get("level", "beginner")
    learned_keys  = data.get("learned_words", [])

    all_words    = words.get(level, words.get("beginner", []))
    learned_pool = [w for w in all_words if w["word"] in learned_keys]

    if len(learned_pool) < 4:
        learned_pool = all_words

    correct      = random.choice(learned_pool)
    wrong_pool   = [w for w in all_words if w["word"] != correct["word"]]
    wrong_sample = random.sample(wrong_pool, min(3, len(wrong_pool)))
    options      = [correct] + wrong_sample
    random.shuffle(options)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=opt["translation"],
            callback_data=f"qa_{opt['word']}_{correct['word']}"
        )]
        for opt in options
    ] + [[InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]])

    progress = "🟩" * correct_count + "⬜" * (total - correct_count)
    txt = (
        f"🧠 <b>ERKIN TEST</b>\n"
        f"📊 {q_num}/{total}  {progress}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🇬🇧 <b>{correct['word'].upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"❓ Tarjimasini toping:"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data.startswith("qa_"), QuizState.answering)
async def check_answer(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    parts   = callback.data.split("_")
    chosen  = parts[1]
    correct = parts[2]

    data          = await state.get_data()
    q_num         = data.get("q_num", 1)
    total         = data.get("total", 10)
    correct_count = data.get("correct_count", 0)

    # group_quiz bo'lsa gqa_ handler ishlaydi, bu erda faqat erkin test
    if data.get("group_quiz"):
        return

    if chosen == correct:
        correct_count += 1
        add_score(user_id, 10)
        await callback.answer("✅ To'g'ri! +10 ball 🎉")
    else:
        await callback.answer(f"❌ Noto'g'ri! To'g'ri: {correct}", show_alert=True)

    if q_num >= total:
        await state.clear()
        user    = get_user(user_id)
        percent = int((correct_count / total) * 100)
        emoji   = "🏆" if percent >= 90 else ("🥇" if percent >= 70 else ("👍" if percent >= 50 else "😅"))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yana test",        callback_data="quiz_start")],
            [InlineKeyboardButton(text="📚 So'z o'rganish",   callback_data="next_word")],
            [InlineKeyboardButton(text="🏠 Bosh menyu",       callback_data="back_menu")],
        ])
        await callback.message.edit_text(
            f"🎯 <b>TEST YAKUNLANDI!</b>  {emoji}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"✅ To'g'ri: <b>{correct_count}/{total}</b>\n"
            f"📊 Natija: <b>{percent}%</b>\n"
            f"⭐️ Jami ball: <b>{user.get('score', 0)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{'🔥 Ajoyib natija!' if percent>=70 else '💪 Davom eting, yaxshilanasiz!'}",
            reply_markup=kb
        )
    else:
        await state.update_data(q_num=q_num + 1, correct_count=correct_count)
        await _send_free_quiz(callback.message, user_id, state, edit=True)

# ══════════════════════════════════════════════════
# GRAMMATIKA BO'LIMI
# ══════════════════════════════════════════════════
@dp.message(F.text == "📖 Grammatika")
async def grammar_menu(message: types.Message):
    await _show_grammar_menu(message, edit=False)

@dp.callback_query(F.data == "grammar_menu")
async def grammar_menu_cb(callback: types.CallbackQuery):
    await _show_grammar_menu(callback.message, edit=True)
    await callback.answer()

async def _show_grammar_menu(target, edit: bool = False):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{t['emoji']} {t['name']}",
            callback_data=f"gram_{t['id']}"
        )]
        for t in GRAMMAR_TOPICS
    ] + [[InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]])

    txt = (
        "📖 <b>GRAMMATIKA BO'LIMI</b>\n\n"
        "🎯 Ingliz tili zamonlarini o'rganing!\n\n"
        "📌 <b>Har bir mavzu:</b>\n"
        "✅ Batafsil tushuntirish\n"
        "✅ Misollar bilan\n"
        "✅ 5 ta test savoli\n\n"
        "👇 Mavzuni tanlang:"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data.startswith("gram_"))
async def grammar_topic(callback: types.CallbackQuery):
    topic_id = callback.data.split("_", 1)[1]
    topic    = next((t for t in GRAMMAR_TOPICS if t["id"] == topic_id), None)
    if not topic:
        await callback.answer("Mavzu topilmadi!", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🧠 {topic['name']} testini boshlash",
            callback_data=f"gramquiz_{topic_id}"
        )],
        [InlineKeyboardButton(text="◀️ Mavzular ro'yxati", callback_data="grammar_menu")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",         callback_data="back_menu")],
    ])
    await callback.message.edit_text(topic["explanation"], reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("gramquiz_"))
async def grammar_quiz_start(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    topic    = next((t for t in GRAMMAR_TOPICS if t["id"] == topic_id), None)
    if not topic:
        await callback.answer("Mavzu topilmadi!", show_alert=True)
        return

    questions = topic["questions"].copy()
    random.shuffle(questions)

    await state.set_state(GrammarQuizState.answering)
    await state.update_data(
        topic_id=topic_id,
        topic_name=topic["name"],
        questions=questions,
        q_index=0,
        correct_count=0,
        total=len(questions)
    )
    await _send_grammar_question(callback.message, state, edit=True)
    await callback.answer()

async def _send_grammar_question(target, state: FSMContext, edit: bool = False):
    data          = await state.get_data()
    questions     = data["questions"]
    q_index       = data["q_index"]
    correct_count = data["correct_count"]
    total         = data["total"]
    topic_name    = data["topic_name"]

    q = questions[q_index]
    options = q["options"].copy()
    random.shuffle(options)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=opt,
            callback_data=f"gans_{opt}_{q['answer']}"
        )]
        for opt in options
    ] + [[InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]])

    progress = "🟩" * correct_count + "⬜" * (total - correct_count)
    txt = (
        f"📖 <b>GRAMMATIKA TESTI</b>\n"
        f"📌 {topic_name}\n"
        f"📊 {q_index + 1}/{total}  {progress}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ <b>{q['q']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 To'g'ri javobni tanlang:"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data.startswith("gans_"), GrammarQuizState.answering)
async def grammar_answer(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    parts   = callback.data.split("_", 3)
    chosen  = parts[1]
    correct = parts[2]

    data          = await state.get_data()
    questions     = data["questions"]
    q_index       = data["q_index"]
    correct_count = data["correct_count"]
    total         = data["total"]
    topic_id      = data["topic_id"]
    topic_name    = data["topic_name"]

    is_correct = (chosen == correct)
    if is_correct:
        correct_count += 1
        add_score(user_id, 8)
        explanation = questions[q_index].get("explanation", "")
        await callback.answer(f"✅ To'g'ri! +8 ball 🎉\n{explanation}")
    else:
        explanation = questions[q_index].get("explanation", "")
        await callback.answer(
            f"❌ Noto'g'ri!\n✅ To'g'ri: {correct}\n💡 {explanation}",
            show_alert=True
        )

    next_index = q_index + 1
    if next_index >= total:
        await state.clear()
        percent = int((correct_count / total) * 100)
        emoji   = "🏆" if percent == 100 else ("🥇" if percent >= 80 else ("👍" if percent >= 60 else "📚"))
        result_msg = "🔥 Zo'r! Siz grammatikani bilasiz!" if percent >= 80 else "💪 Tushuntirishni qayta o'qing va urinib ko'ring!"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Qaytadan test",       callback_data=f"gramquiz_{topic_id}")],
            [InlineKeyboardButton(text="📖 Boshqa mavzu",        callback_data="grammar_menu")],
            [InlineKeyboardButton(text="🏠 Bosh menyu",          callback_data="back_menu")],
        ])
        await callback.message.edit_text(
            f"🎯 <b>GRAMMATIKA TESTI TUGADI!</b>  {emoji}\n\n"
            f"📌 {topic_name}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"✅ To'g'ri: <b>{correct_count}/{total}</b>\n"
            f"📊 Natija: <b>{percent}%</b>\n"
            f"⭐️ +{correct_count * 8} ball qo'shildi!\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{result_msg}",
            reply_markup=kb
        )
    else:
        await state.update_data(q_index=next_index, correct_count=correct_count)
        await _send_grammar_question(callback.message, state, edit=True)

# ══════════════════════════════════════════════════
# STREAK
# ══════════════════════════════════════════════════
@dp.message(F.text == "🔥 Streak")
async def show_streak(message: types.Message):
    user   = get_user(message.from_user.id)
    streak = user.get("streak", 0)
    score  = user.get("score", 0)

    if streak >= 30:
        badge, msg = "🏆", "Siz haqiqiy USTOZ!"
    elif streak >= 14:
        badge, msg = "🔥", "Ajoyib natija!"
    elif streak >= 7:
        badge, msg = "💪", "Juda yaxshi!"
    elif streak >= 3:
        badge, msg = "⚡️", "Davom eting!"
    else:
        badge, msg = "🌱", "Endi boshlayapsiz!"

    bar = "🔥" * min(streak, 10) + "⬜" * max(0, 10 - streak)

    await message.answer(
        f"🔥 <b>STREAK HISOBINGIZ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{bar}\n"
        f"🗓 Ketma-ketlik: <b>{streak} kun</b>  {badge}\n"
        f"💬 {msg}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⭐️ Jami ball: <b>{score}</b>\n\n"
        f"<b>🎯 Maqsadlar:</b>\n"
        f"{'✅' if streak>=3  else '🔲'} 3 kun  — ⚡️ Ishga tushding!\n"
        f"{'✅' if streak>=7  else '🔲'} 7 kun  — 💪 Yaxshi!\n"
        f"{'✅' if streak>=14 else '🔲'} 14 kun — 🔥 Ajoyib!\n"
        f"{'✅' if streak>=30 else '🔲'} 30 kun — 🏆 Ustoz!\n\n"
        f"<i>Har kun kiring va streak'ingizni saqlang! 🚀</i>"
    )

# ══════════════════════════════════════════════════
# REYTING
# ══════════════════════════════════════════════════
@dp.message(F.text == "🏆 Reyting")
async def show_rating(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Ball bo'yicha",    callback_data="rank_score"),
         InlineKeyboardButton(text="👥 Referal bo'yicha", callback_data="rank_ref")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",       callback_data="back_menu")],
    ])
    await message.answer(
        "🏆 <b>REYTING</b>\n\nQaysi ro'yxatni ko'rmoqchisiz?",
        reply_markup=kb
    )

@dp.callback_query(F.data == "rank_score")
async def show_top_score(callback: types.CallbackQuery):
    top    = get_top_scores(10)
    text   = "🏆 <b>TOP 10 — BALL REYTINGI</b>\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, u in enumerate(top, 1):
        vip   = " 💎" if u.get("is_vip") else ""
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} <b>{u['name']}</b>{vip} — {u['score']} ⭐️\n"
    text += "\n<i>Har kuni o'rganib reyting oshiring! 🚀</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Referal reytingi", callback_data="rank_ref")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",       callback_data="back_menu")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "rank_ref")
async def show_top_ref(callback: types.CallbackQuery):
    top    = get_top_referrals(10)
    text   = "👥 <b>TOP 10 — REFERAL REYTINGI</b>\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, u in enumerate(top, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} <b>{u['name']}</b> — {u['referral_count']} 👤\n"
    text += f"\n<i>Har juma 5+ taklif qilgan g'olib 10 000 so'm yutadi! 🏆</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Ball reytingi", callback_data="rank_score")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",    callback_data="back_menu")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)

# ══════════════════════════════════════════════════
# REFERAL
# ══════════════════════════════════════════════════
@dp.message(F.text == "👥 Referal")
async def referal_menu(message: types.Message):
    user_id  = message.from_user.id
    user     = get_user(user_id)
    bot_info = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_count = user.get("referral_count", 0)
    needed    = max(0, MIN_REFERRALS_FOR_BONUS - ref_count)

    progress_bar = "🟩" * min(ref_count, 5) + "⬜" * max(0, 5 - ref_count)
    winner_line = "🏆 G'olib bo'lishingiz mumkin!" if ref_count >= 5 else f"📌 G'olib uchun yana {needed} ta kerak"

    await message.answer(
        f"👥 <b>REFERAL TIZIMI</b>\n\n"
        f"🔗 <b>Sizning havolangiz:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 Taklif etilganlar: <b>{ref_count} ta</b>\n"
        f"{progress_bar}\n"
        f"{winner_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>HAFTALIK TANLOV:</b>\n"
        f"• Har juma soat 18:00 da hisoblanadi\n"
        f"• Kamida <b>5 ta</b> taklif qilish shart\n"
        f"• G'olibga <b>💰 10 000 so'm</b>!\n\n"
        f"<i>Havolani do'stlaringizga yuboring! 🚀</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📤 Havolani ulashish",
                switch_inline_query=f"LexoBot orqali ingliz tilini o'rganing! {ref_link}"
            )],
        ])
    )

# ══════════════════════════════════════════════════
# VIP TIZIMI
# ══════════════════════════════════════════════════
@dp.message(F.text == "💎 VIP Sotib olish")
async def vip_buy(message: types.Message):
    user_id = message.from_user.id
    if is_vip(user_id):
        await message.answer("✅ Siz allaqachon VIP foydalanuvchisiz! 💎")
        return

    await message.answer(
        f"💎 <b>VIP PREMIUM — 1 OYLIK</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Narxi: <b>{VIP_PRICE:,} so'm / oy</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>VIP imkoniyatlari:</b>\n"
        f"🔓 Guruh testisiz o'tish\n"
        f"📚 Barcha daraja so'zlari\n"
        f"🚀 2x tezroq ball to'plash\n"
        f"🏆 Haftalik bonus mukofoti\n"
        f"🔕 Reklamasiz foydalanish\n\n"
        f"💳 <b>To'lov:</b>\n"
        f"Karta: <code>{CARD_NUMBER}</code>\n"
        f"Egasi: <b>{CARD_OWNER}</b>\n\n"
        f"<i>To'lovdan so'ng tugmani bosing 👇</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ To'lov qildim", callback_data="vip_pay")],
            [InlineKeyboardButton(text="❌ Bekor",         callback_data="vip_cancel")],
        ])
    )

@dp.callback_query(F.data == "vip_pay")
async def vip_pay_cb(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(VipState.waiting_name)
    await callback.message.answer(
        "👤 <b>Ism-familiyangizni kiriting:</b>\n"
        "<i>(To'lov amalga oshirgan shaxs)</i>"
    )
    await callback.answer()

@dp.callback_query(F.data == "vip_renew")
async def vip_renew_cb(callback: types.CallbackQuery):
    await callback.message.answer(
        f"💎 <b>VIP QAYTA OBUNA</b>\n\n"
        f"💰 Narxi: <b>{VIP_PRICE:,} so'm / oy</b>\n\n"
        f"💳 Karta: <code>{CARD_NUMBER}</code>\n"
        f"👤 Egasi: <b>{CARD_OWNER}</b>\n\n"
        f"To'lov qilgach tugmani bosing 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ To'lov qildim", callback_data="vip_pay")],
            [InlineKeyboardButton(text="❌ Bekor",         callback_data="vip_cancel")],
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "vip_cancel")
async def vip_cancel_cb(callback: types.CallbackQuery):
    await callback.answer("Bekor qilindi")
    await callback.message.edit_reply_markup(reply_markup=None)

@dp.message(VipState.waiting_name)
async def vip_get_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await state.set_state(VipState.waiting_check)
    await message.answer(
        "📸 <b>To'lov chekini yuboring:</b>\n"
        "<i>(Rasm yoki screenshot)</i>"
    )

@dp.message(VipState.waiting_check, F.photo | F.document)
async def vip_get_check(message: types.Message, state: FSMContext):
    user_id  = message.from_user.id
    data     = await state.get_data()
    file_id  = message.photo[-1].file_id if message.photo else message.document.file_id

    create_vip_request(user_id, data["full_name"], VIP_PRICE, file_id)
    await state.clear()

    await message.answer(
        "✅ <b>Arizangiz qabul qilindi!</b>\n\n"
        "⏳ Adminlar <b>24 soat</b> ichida ko'rib chiqadilar.\n"
        "📩 Natija haqida xabar beriladi."
    )

    username = f"@{message.from_user.username}" if message.from_user.username else "yo'q"
    caption  = (
        f"🆕 <b>VIP SO'ROV</b>\n\n"
        f"👤 Ism: <b>{data['full_name']}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📱 Username: {username}\n"
        f"💰 Summa: <b>{VIP_PRICE:,} so'm</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"vadm_ok_{user_id}")],
        [InlineKeyboardButton(text="❌ Rad etish",  callback_data=f"vadm_no_{user_id}")],
    ])
    for admin_id in ADMIN_IDS:
        try:
            if message.photo:
                await bot.send_photo(admin_id, photo=file_id, caption=caption, reply_markup=kb)
            else:
                await bot.send_document(admin_id, document=file_id, caption=caption, reply_markup=kb)
        except Exception as e:
            logger.error(f"Admin {admin_id} ga yuborib bo'lmadi: {e}")

@dp.message(VipState.waiting_check)
async def vip_check_wrong_type(message: types.Message):
    await message.answer("⚠️ Iltimos, <b>rasm</b> yoki <b>fayl</b> yuboring.")

# ══════════════════════════════════════════════════
# ADMIN VIP TASDIQLASH
# ══════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("vadm_ok_"))
async def admin_vip_approve(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    target_id = int(callback.data.split("_")[2])
    set_vip(target_id, True)
    try:
        await bot.send_message(
            target_id,
            "🎉 <b>TABRIKLAYMIZ!</b>\n\n"
            "💎 VIP obunangiz tasdiqlandi!\n"
            "📅 Muddat: <b>30 kun</b>\n\n"
            "Barcha VIP imkoniyatlar faollashdi! 🚀",
            reply_markup=main_kb(target_id)
        )
    except Exception as e:
        logger.error(f"VIP user {target_id} ga xabar yuborib bo'lmadi: {e}")
    new_caption = (callback.message.caption or "") + "\n\n✅ <b>TASDIQLANDI</b>"
    await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    await callback.answer("✅ VIP tasdiqlandi!")

@dp.callback_query(F.data.startswith("vadm_no_"))
async def admin_vip_reject(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    target_id = int(callback.data.split("_")[2])
    try:
        await bot.send_message(
            target_id,
            "❌ <b>VIP so'rovingiz rad etildi.</b>\n\n"
            "To'lov tasdiqlanmadi.\n"
            "Muammo bo'lsa admin bilan bog'laning."
        )
    except Exception as e:
        logger.error(f"Rad etish xabari {target_id} ga yuborib bo'lmadi: {e}")
    new_caption = (callback.message.caption or "") + "\n\n❌ <b>RAD ETILDI</b>"
    await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    await callback.answer("❌ Rad etildi")

# ══════════════════════════════════════════════════
# VIP PANEL
# ══════════════════════════════════════════════════
@dp.message(F.text == "💎 VIP Panel")
async def vip_panel(message: types.Message):
    user_id = message.from_user.id
    user    = get_user(user_id)

    if user_id in ADMIN_IDS:
        stats = get_stats()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistika",       callback_data="adm_stats")],
            [InlineKeyboardButton(text="📢 Xabar yuborish",   callback_data="adm_broadcast")],
            [InlineKeyboardButton(text="⏳ Kutilayotgan VIP", callback_data="adm_pending")],
        ])
        await message.answer(
            f"👨‍💼 <b>ADMIN PANEL</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 Jami: <b>{stats['total']}</b>\n"
            f"💎 VIP: <b>{stats['vip']}</b>\n"
            f"⏳ Kutilmoqda: <b>{stats['pending_vip']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb
        )
        return

    if not is_vip(user_id):
        await message.answer(
            "❌ Siz VIP emassiz.\n\n"
            "💎 VIP sotib olish uchun tugmani bosing:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 VIP Sotib olish", callback_data="vip_renew")]
            ])
        )
        return

    vip_since   = user.get("vip_since")
    vip_expires = user.get("vip_expires")
    since_str   = vip_since.strftime("%d.%m.%Y") if vip_since else "—"

    if vip_expires:
        if isinstance(vip_expires, str):
            vip_expires = datetime.fromisoformat(vip_expires)
        expires_str = vip_expires.strftime("%d.%m.%Y")
        delta     = vip_expires - datetime.now()
        days_left = max(0, delta.days)
        expire_line = (
            f"⚠️ Tugaydi: <b>{expires_str}</b> ({days_left} kun qoldi!)"
            if days_left <= 3
            else f"📅 Tugaydi: <b>{expires_str}</b> ({days_left} kun)"
        )
    else:
        expire_line = "📅 Muddat: —"

    await message.answer(
        f"💎 <b>VIP PANEL</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ VIP: <b>Faol</b>\n"
        f"📅 Boshlangan: <b>{since_str}</b>\n"
        f"{expire_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔓 Testisiz guruh o'tish: <b>Faol</b>\n"
        f"🚀 Barcha imkoniyatlar faol!"
    )

# ══════════════════════════════════════════════════
# ADMIN KOMANDALAR
# ══════════════════════════════════════════════════
@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Ruxsat yo'q")
        return
    stats = get_stats()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika",       callback_data="adm_stats")],
        [InlineKeyboardButton(text="📢 Xabar yuborish",   callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="⏳ Kutilayotgan VIP", callback_data="adm_pending")],
    ])
    await message.answer(
        f"👨‍💼 <b>ADMIN PANEL</b>\n\n"
        f"👥 Jami: <b>{stats['total']}</b>\n"
        f"💎 VIP: <b>{stats['vip']}</b>\n"
        f"⏳ Kutilmoqda: <b>{stats['pending_vip']}</b>",
        reply_markup=kb
    )

@dp.callback_query(F.data == "adm_stats")
async def adm_stats_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    stats = get_stats()
    await callback.message.edit_text(
        f"📊 <b>STATISTIKA</b>\n\n"
        f"👥 Jami foydalanuvchi: <b>{stats['total']}</b>\n"
        f"💎 VIP: <b>{stats['vip']}</b>\n"
        f"⏳ Kutilayotgan VIP: <b>{stats['pending_vip']}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="adm_stats")]
        ])
    )

@dp.callback_query(F.data == "adm_pending")
async def adm_pending_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    reqs = get_pending_vip_requests()
    if not reqs:
        await callback.answer("✅ Kutilayotgan so'rovlar yo'q", show_alert=True)
        return
    await callback.answer(f"⏳ {len(reqs)} ta so'rov kutmoqda", show_alert=True)

@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BroadcastState.waiting)
    await callback.message.answer(
        "📢 <b>XABAR YUBORISH</b>\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni yozing\n"
        "<i>(matn, rasm, video — hammasi qabul qilinadi)</i>:"
    )
    await callback.answer()

@dp.message(Command("broadcast"))
async def broadcast_cmd(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Ruxsat yo'q")
        return
    await state.set_state(BroadcastState.waiting)
    await message.answer("📢 Xabarni yozing:")

@dp.message(BroadcastState.waiting)
async def broadcast_send(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    await message.answer("⏳ Yuborilmoqda...")
    user_ids = get_all_user_ids()
    sent = fail = 0
    for uid in user_ids:
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await message.answer(
        f"✅ <b>Xabar yuborildi!</b>\n\n"
        f"📨 Muvaffaqiyatli: <b>{sent}</b>\n"
        f"❌ Yuborilmadi: <b>{fail}</b>"
    )
    await state.clear()

# ══════════════════════════════════════════════════
# BACKGROUND TASKS
# ══════════════════════════════════════════════════
async def vip_expiry_task():
    while True:
        try:
            await asyncio.sleep(3600)
            expired = get_expired_vip_users()
            for user in expired:
                set_vip(user["user_id"], False)
                try:
                    await bot.send_message(
                        user["user_id"],
                        "⚠️ <b>VIP obunangiz tugadi!</b>\n\n"
                        "1 oylik muddatingiz tugadi.\n"
                        "Davom ettirish uchun qayta obuna bo'ling 👇",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="💎 Qayta obuna", callback_data="vip_renew")]
                        ])
                    )
                except Exception:
                    pass
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"🔴 VIP tugadi: <b>{user['name']}</b> (ID: {user['user_id']})"
                        )
                    except Exception:
                        pass

            expiring = get_expiring_soon_vip_users(hours=24)
            for user in expiring:
                expires = user.get("vip_expires")
                if expires:
                    if isinstance(expires, str):
                        expires = datetime.fromisoformat(expires)
                    try:
                        await bot.send_message(
                            user["user_id"],
                            f"⏰ <b>VIP tugayapti!</b>\n\n"
                            f"Muddat: <b>{expires.strftime('%d.%m.%Y')}</b>\n"
                            f"Uzilmaslik uchun hoziroq yangilang! 💎",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="💎 Qayta obuna", callback_data="vip_renew")]
                            ])
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"VIP expiry task xatosi: {e}")
            await asyncio.sleep(300)

async def weekly_bonus_task():
    while True:
        try:
            now = datetime.now()
            days_until_friday = (4 - now.weekday()) % 7
            if days_until_friday == 0 and now.hour >= 18:
                days_until_friday = 7
            target       = now.replace(hour=18, minute=0, second=0, microsecond=0)
            target      += timedelta(days=days_until_friday)
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(max(60, wait_seconds))

            top_list = get_top_referrals(1)
            if top_list:
                winner = top_list[0]
                if winner.get("referral_count", 0) >= MIN_REFERRALS_FOR_BONUS:
                    add_referral_earnings(winner["user_id"], 10000)
                    try:
                        await bot.send_message(
                            winner["user_id"],
                            f"🎉 <b>HAFTALIK G'OLIB!</b> 🏆\n\n"
                            f"👥 Taklif: <b>{winner['referral_count']} ta</b>\n"
                            f"💰 <b>+10 000 so'm</b> bonus!\n\n"
                            f"Tabriklaymiz! 🎊"
                        )
                    except Exception:
                        pass
                else:
                    for admin_id in ADMIN_IDS:
                        try:
                            await bot.send_message(
                                admin_id,
                                f"ℹ️ Haftalik bonus berilmadi.\n"
                                f"Eng ko'p: <b>{winner.get('referral_count',0)} ta</b>\n"
                                f"Kerak: kamida <b>{MIN_REFERRALS_FOR_BONUS} ta</b>"
                            )
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Haftalik bonus xatosi: {e}")
            await asyncio.sleep(3600)

# ══════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════
async def main():
    from db import init_db
    init_db()
    logger.info("✅ LexoBot ishga tushdi!")
    asyncio.create_task(weekly_bonus_task())
    asyncio.create_task(vip_expiry_task())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
