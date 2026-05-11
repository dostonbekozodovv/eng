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
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove,
    BotCommand, BotCommandScopeDefault,
    BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
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

PRIZE_SCORE_AMOUNT = 10_000
PRIZE_REF_AMOUNT   = 10_000

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher(storage=MemoryStorage())

GROUP_QUIZ_STATE: dict = {}

async def _check_score_prize(user_id: int):
    user  = get_user(user_id)
    if not user: return
    score = user.get("score", 0)
    if score >= 10_000:
        try:
            await bot.send_message(
                user_id,
                f"🎉 <b>TABRIKLAYMIZ!</b>\n\n"
                f"Siz <b>10 000 ball</b> to'pladingiz!\n\n"
                f"🏆 Sovrin: <b>{PRIZE_SCORE_AMOUNT:,} so'm</b>\n\n"
                f"Adminlar siz bilan bog'lanadi. 🙏"
            )
            for admin_id in ADMIN_IDS:
                u = get_user(user_id)
                try:
                    await bot.send_message(
                        admin_id,
                        f"🏆 <b>10 000 BALL SOVRIN!</b>\n\n"
                        f"👤 {u.get('name','?') } (ID: <code>{user_id}</code>)\n"
                        f"⭐️ Ball: {score}\n\nSovrin: {PRIZE_SCORE_AMOUNT:,} so'm to'lang!"
                    )
                except Exception: pass
        except Exception: pass

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

class GroupPollState(StatesGroup):
    selecting_group = State()
    running         = State()

class FeedbackState(StatesGroup):
    waiting = State()

class UserTestState(StatesGroup):
    waiting_question = State()
    waiting_options  = State()
    waiting_answer   = State()
    confirm          = State()

LEVEL_NAMES = {
    "beginner":     "🟢 Boshlang'ich",
    "intermediate": "🟡 O'rta daraja",
    "advanced":     "🔴 Yuqori daraja",
}

# ══════════════════════════════════════════════════
# GRAMMAR MAVZULAR
# ══════════════════════════════════════════════════
GRAMMAR_TOPICS = [
    {
        "id": "present_simple", "name": "🕐 Present Simple", "emoji": "🕐",
        "explanation": (
            "🕐 <b>PRESENT SIMPLE</b> — Oddiy hozirgi zamon\n\n"
            "📌 <b>Qachon ishlatiladi?</b>\n"
            "✅ Odatiy harakatlar uchun\n✅ Haqiqatlar va qonunlar\n✅ Kundalik rutina\n\n"
            "📐 <b>Qoida:</b>\n"
            "➕ I/You/We/They + <b>V1</b>\n➕ He/She/It + <b>V1+s/es</b>\n"
            "➖ do/does + not + V1\n❓ Do/Does + subject + V1?\n\n"
            "💡 I <b>work</b> | She <b>speaks</b> | They <b>don't</b> like | <b>Does</b> he play?\n\n"
            "⚡️ He/She/It bilan fe'lga <b>-s/-es</b> qo'shiladi!"
        ),
        "questions": [
            {"q":"She ___ to school every day.","options":["go","goes","going","gone"],"answer":"goes","explanation":"He/She/It + goes ✅"},
            {"q":"They ___ not like pizza.","options":["do","does","did","is"],"answer":"do","explanation":"They + do not ✅"},
            {"q":"___ he speak English?","options":["Do","Does","Did","Is"],"answer":"Does","explanation":"He + Does ✅"},
            {"q":"The sun ___ in the east.","options":["rise","rises","rising","rose"],"answer":"rises","explanation":"Haqiqat: rises ✅"},
            {"q":"I ___ coffee every morning.","options":["drink","drinks","drinking","drank"],"answer":"drink","explanation":"I + drink ✅"},
        ]
    },
    {
        "id": "present_continuous", "name": "▶️ Present Continuous", "emoji": "▶️",
        "explanation": (
            "▶️ <b>PRESENT CONTINUOUS</b> — Davomli hozirgi zamon\n\n"
            "📌 Ayni shu paytda bo'layotgan harakat\n\n"
            "📐 Subject + <b>am/is/are + V-ing</b>\n\n"
            "💡 I <b>am studying</b> | She <b>is cooking</b> | Are you listening?\n\n"
            "⚡️ Kalit: now, right now, at the moment, look!, listen!"
        ),
        "questions": [
            {"q":"She ___ a book right now.","options":["reads","is reading","read","was reading"],"answer":"is reading","explanation":"Hozir: is reading ✅"},
            {"q":"They ___ football at the moment.","options":["play","played","are playing","have played"],"answer":"are playing","explanation":"They + are playing ✅"},
            {"q":"___ you listening to me?","options":["Do","Does","Are","Is"],"answer":"Are","explanation":"You + Are ✅"},
            {"q":"Look! It ___ outside.","options":["rains","is raining","rained","has rained"],"answer":"is raining","explanation":"Look! = is raining ✅"},
            {"q":"I ___ not watching TV now.","options":["do","does","am","are"],"answer":"am","explanation":"I + am ✅"},
        ]
    },
    {
        "id": "past_simple", "name": "⏮ Past Simple", "emoji": "⏮",
        "explanation": (
            "⏮ <b>PAST SIMPLE</b> — Oddiy o'tgan zamon\n\n"
            "📌 O'tgan tugallangan harakat\n\n"
            "📐 Subject + <b>V2</b> | did not + V1 | Did + subject + V1?\n\n"
            "💡 I <b>worked</b> | She <b>went</b> | He <b>didn't</b> call\n\n"
            "⚡️ Kalit: yesterday, last week, ago, in 2020"
        ),
        "questions": [
            {"q":"She ___ to school yesterday.","options":["go","goes","went","gone"],"answer":"went","explanation":"go → went ✅"},
            {"q":"I ___ not see him last night.","options":["do","does","did","was"],"answer":"did","explanation":"Past inkor: did not ✅"},
            {"q":"___ you call me yesterday?","options":["Do","Does","Did","Were"],"answer":"Did","explanation":"Past savol: Did ✅"},
            {"q":"They ___ TV last night.","options":["watch","watches","watched","watching"],"answer":"watched","explanation":"Regular +ed: watched ✅"},
            {"q":"He ___ a car two years ago.","options":["buys","buy","bought","buying"],"answer":"bought","explanation":"buy → bought ✅"},
        ]
    },
    {
        "id": "past_continuous", "name": "⏸ Past Continuous", "emoji": "⏸",
        "explanation": (
            "⏸ <b>PAST CONTINUOUS</b> — Davomli o'tgan zamon\n\n"
            "📌 O'tmishda davom etgan harakat (while/when)\n\n"
            "📐 Subject + <b>was/were + V-ing</b>\n\n"
            "💡 I <b>was sleeping</b> | They <b>were playing</b> when I arrived\n\n"
            "⚡️ Kalit: while, when, at that moment, all day long"
        ),
        "questions": [
            {"q":"I ___ when you called.","options":["sleep","slept","was sleeping","am sleeping"],"answer":"was sleeping","explanation":"was sleeping ✅"},
            {"q":"They ___ all evening yesterday.","options":["study","studied","were studying","are studying"],"answer":"were studying","explanation":"were studying ✅"},
            {"q":"___ she cooking when you arrived?","options":["Did","Was","Were","Is"],"answer":"Was","explanation":"She + Was ✅"},
            {"q":"While I ___, he came in.","options":["read","reads","was reading","am reading"],"answer":"was reading","explanation":"While + was reading ✅"},
            {"q":"We ___ not watching TV at midnight.","options":["did","were","was","are"],"answer":"were","explanation":"We + were ✅"},
        ]
    },
    {
        "id": "present_perfect", "name": "✨ Present Perfect", "emoji": "✨",
        "explanation": (
            "✨ <b>PRESENT PERFECT</b> — Tugallangan hozirgi zamon\n\n"
            "📌 Natijasi hozirga ta'sir qilgan harakat, tajriba\n\n"
            "📐 Subject + <b>have/has + V3</b>\n\n"
            "💡 I <b>have visited</b> | She <b>has finished</b> | Have you ever tried?\n\n"
            "⚡️ Kalit: ever, never, just, already, yet, since, for"
        ),
        "questions": [
            {"q":"She ___ her homework already.","options":["finish","finished","has finished","have finished"],"answer":"has finished","explanation":"She + has + V3 ✅"},
            {"q":"I ___ never been to Japan.","options":["have","has","had","did"],"answer":"have","explanation":"I + have ✅"},
            {"q":"___ you ever tried Indian food?","options":["Did","Do","Have","Has"],"answer":"Have","explanation":"Have you ever? ✅"},
            {"q":"He ___ just left the office.","options":["have","has","had","did"],"answer":"has","explanation":"He + has just ✅"},
            {"q":"They ___ not seen this movie yet.","options":["have","has","had","did"],"answer":"have","explanation":"They + have not ✅"},
        ]
    },
    {
        "id": "future_simple", "name": "🔮 Future Simple", "emoji": "🔮",
        "explanation": (
            "🔮 <b>FUTURE SIMPLE</b> — Oddiy kelasi zamon\n\n"
            "📌 Spontan qarorlar, bashorat, va'da\n\n"
            "📐 Subject + <b>will + V1</b> | won't + V1 | Will + subject?\n\n"
            "💡 I <b>will call</b> | It <b>will rain</b> | She <b>won't</b> come\n\n"
            "⚡️ Kalit: tomorrow, next week, soon, I think, probably"
        ),
        "questions": [
            {"q":"I think it ___ rain tomorrow.","options":["is","was","will","would"],"answer":"will","explanation":"Bashorat: will ✅"},
            {"q":"She ___ not come to the party.","options":["will","would","shall","should"],"answer":"will","explanation":"will not ✅"},
            {"q":"___ you help me with this?","options":["Do","Did","Will","Have"],"answer":"Will","explanation":"Will you? ✅"},
            {"q":"I ___ call you as soon as I arrive.","options":["call","called","will call","have called"],"answer":"will call","explanation":"will call ✅"},
            {"q":"They ___ not finish next week.","options":["don't finish","didn't finish","won't finish","haven't finished"],"answer":"won't finish","explanation":"won't finish ✅"},
        ]
    },
]

# ══════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════
def is_group(msg) -> bool:
    chat = msg.chat if hasattr(msg, "chat") else msg
    return chat.type in ("group", "supergroup")

def main_kb(user_id: int = None):
    vip      = is_vip(user_id) if user_id else False
    is_admin = user_id in ADMIN_IDS if user_id else False
    buttons = [
        [KeyboardButton(text="📚 So'z o'rgan"),   KeyboardButton(text="🧠 Test")],
        [KeyboardButton(text="📖 Grammatika"),      KeyboardButton(text="🔥 Streak")],
        [KeyboardButton(text="🏆 Reyting"),         KeyboardButton(text="👥 Referal")],
        [KeyboardButton(text="📝 Test yaratish"),   KeyboardButton(text="📋 Qo'llanma")],
        [KeyboardButton(text="💬 Taklif & Fikr"),   KeyboardButton(text="⚙️ Daraja")],
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

def word_card_kb(group_num: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Keyingi so'z",            callback_data="next_word")],
        [InlineKeyboardButton(text="🧠 Shu guruhni test qilish",  callback_data=f"group_quiz_{group_num}")],
        [InlineKeyboardButton(text="🔄 O'rganilganlarni ko'rish",callback_data="review_words")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",               callback_data="back_menu")],
    ])

# ══════════════════════════════════════════════════
# KANAL TEKSHIRUVI
# ══════════════════════════════════════════════════
async def check_subscription(user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception as e:
        logger.error(f"Kanal: {e}")
        return True

def subscribe_kb():
    ch  = CHANNEL_USERNAME.lstrip("@") if CHANNEL_USERNAME else ""
    url = f"https://t.me/{ch}" if ch else "https://t.me/"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=url)],
        [InlineKeyboardButton(text="✅ Tekshirish",             callback_data="check_sub")],
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

    if is_group(message):
        await message.answer(
            f"👋 Salom, <b>{name}</b>!\n\n"
            f"🤖 <b>LexoBot</b> — ingliz tili o'rganish boti\n\n"
            f"📌 <b>Guruh komandalari:</b>\n"
            f"/quiz — 🎯 Guruh viktorinasi (Poll)\n"
            f"/stopquiz — ⏹ Viktorinani to'xtatish\n"
            f"/rating — 🏆 Reyting\n"
            f"/streak — 🔥 Streak\n\n"
            f"💡 To'liq o'rganish uchun botga shaxsiy yozing!"
        )
        return

    if not await check_subscription(user_id):
        await message.answer(
            f"👋 Salom, <b>{name}</b>!\n\n"
            f"🔐 Botdan foydalanish uchun avval kanalga obuna bo'ling 👇",
            reply_markup=subscribe_kb()
        )
        return

    if ref_id:
        try:
            await bot.send_message(ref_id,
                f"🎉 <b>{name}</b> botga qo'shildi!\n👥 Referal hisobingiz yangilandi!")
        except Exception:
            pass

    if not user.get("level"):
        await message.answer(
            f"🎉 Xush kelibsiz, <b>{name}</b>!\n\n"
            f"🚀 LexoBot — ingliz tilini o'rganishning eng qulay yo'li!\n\n"
            f"📊 Avval darajangizni tanlang:",
            reply_markup=level_kb()
        )
    else:
        await message.answer(
            f"👋 Qaytib keldingiz, <b>{name}</b>! 🔥\n\nDavom ettiramizmi? 💪",
            reply_markup=main_kb(user_id)
        )

@dp.callback_query(F.data == "check_sub")
async def check_sub_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.delete()
        user = get_user(user_id)
        if not user or not user.get("level"):
            await callback.message.answer("✅ Rahmat! Darajangizni tanlang:", reply_markup=level_kb())
        else:
            await callback.message.answer("✅ Xush kelibsiz! 🎉", reply_markup=main_kb(user_id))
    else:
        await callback.answer("❗ Hali obuna bo'lmadingiz!", show_alert=True)

@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🏠 <b>Bosh menyu</b>", reply_markup=main_kb(callback.from_user.id))
    await callback.answer()

# ══════════════════════════════════════════════════
# DARAJA
# ══════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("level_"))
async def set_level(callback: types.CallbackQuery, state: FSMContext):
    level   = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    update_user_level(user_id, level)
    await state.clear()
    await callback.answer(f"✅ {LEVEL_NAMES.get(level, level)}")
    try:
        await callback.message.edit_text(
            f"✅ Daraja belgilandi: <b>{LEVEL_NAMES.get(level, level)}</b>\n\n🚀 O'rganishni boshlang!"
        )
    except Exception:
        pass
    if not is_group(callback.message):
        await callback.message.answer("📚 Bo'lim tanlang:", reply_markup=main_kb(user_id))
    else:
        # Guruhda daraja tanlanganidan keyin quiz menyusi
        all_words    = words.get(level, [])
        total_groups = (len(all_words) + 19) // 20
        rows = []
        row  = []
        for g in range(1, total_groups + 1):
            row.append(InlineKeyboardButton(text=f"📦 {g}-guruh", callback_data=f"poll_group_{g}"))
            if len(row) == 3:
                rows.append(row); row = []
        if row: rows.append(row)
        lbl = LEVEL_NAMES.get(level, level)
        await callback.message.answer(
            f"🎯 <b>GURUH VIKTORINASI</b>\n\n📚 Daraja: {lbl}\n📦 Guruhlar: <b>{total_groups} ta</b>\n\nQaysi guruhdan?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )

@dp.message(F.text == "⚙️ Daraja")
async def change_level(message: types.Message):
    await message.answer("⚙️ <b>DARAJA O'ZGARTIRISH</b>\n\nYangi darajangizni tanlang:", reply_markup=level_kb())

# ══════════════════════════════════════════════════
# /quiz — GURUH POLL VIKTORINASI (Lobby tizimi bilan)
# ══════════════════════════════════════════════════
@dp.message(Command("quiz"))
async def cmd_quiz(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user    = get_or_create_user(user_id, message.from_user.first_name or "Do'st", message.from_user.username or "")
    if not user.get("level"):
        await message.reply("⚙️ Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    level        = user.get("level", "beginner")
    all_words    = words.get(level, [])
    total_groups = (len(all_words) + 19) // 20
    if total_groups == 0:
        await message.reply("❌ So'zlar topilmadi.")
        return
    rows = []; row = []
    for g in range(1, total_groups + 1):
        row.append(InlineKeyboardButton(text=f"📦 {g}-guruh", callback_data=f"poll_group_{g}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    await state.clear()
    lbl = LEVEL_NAMES.get(level, level)
    await message.reply(
        f"🎯 <b>GURUH VIKTORINASI</b>\n\n📚 Daraja: {lbl}\n📦 Jami guruhlar: <b>{total_groups} ta</b>\n\nQaysi guruhdan o'ynaysiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@dp.message(Command("stopquiz"))
async def cmd_stopquiz(message: types.Message):
    chat_id = message.chat.id
    qs      = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or not qs.get("active"):
        await message.reply("❌ Hozir aktiv viktorina yo'q.")
        return
    user_id    = message.from_user.id
    starter_id = qs.get("starter_id")
    is_starter = (starter_id == user_id)
    is_adm     = False
    try:
        m      = await bot.get_chat_member(chat_id, user_id)
        is_adm = m.status in ("administrator", "creator")
    except Exception:
        pass
    if not is_starter and not is_adm:
        sname = qs.get("starter_name", "boshqasi")
        await message.reply(f"❌ Faqat testni boshlagan <b>{sname}</b> yoki admin to'xtatishi mumkin.")
        return
    qs["active"] = False
    scores   = qs.get("scores", {})
    poll_num = qs.get("poll_num", 0)
    group_num = qs.get("group_num", 1)
    if scores:
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        txt = f"⏹ <b>Viktorina to'xtatildi!</b>\n\n📊 {group_num}-guruh | {poll_num} savol\n━━━━━━━━━━━━━━━━━━\n"
        medals = ["🥇","🥈","🥉"]
        for i,(uid,cnt) in enumerate(sorted_scores[:10]):
            medal = medals[i] if i<3 else f"{i+1}."
            winner = " 🏆 G'OLIB!" if i==0 else ""
            try:
                m    = await bot.get_chat_member(chat_id, int(uid))
                name = m.user.first_name or "User"
            except Exception:
                name = f"Ishtirokchi {i+1}"
            txt += f"{medal} <b>{name}</b> — {cnt}/{poll_num} ✅{winner}\n"
    else:
        txt = "⏹ <b>Viktorina to'xtatildi.</b>\n\nHech kim qatnashmadi."
    await message.answer(txt)
    GROUP_QUIZ_STATE.pop(chat_id, None)

@dp.callback_query(F.data.startswith("poll_group_"))
async def poll_group_selected(callback: types.CallbackQuery, state: FSMContext):
    user_id   = callback.from_user.id
    chat_id   = callback.message.chat.id
    user      = get_user(user_id) or get_or_create_user(user_id, callback.from_user.first_name or "Do'st", callback.from_user.username or "")
    group_num = int(callback.data.split("_")[2])
    level     = user.get("level", "beginner")
    all_words = words.get(level, [])
    start_idx = (group_num - 1) * 20
    group_words = all_words[start_idx:start_idx + 20]
    if len(group_words) < 4:
        await callback.answer("❌ Bu guruhda yetarli so'z yo'q!", show_alert=True)
        return
    total = min(20, len(group_words))
    GROUP_QUIZ_STATE[chat_id] = {
        "group_num": group_num, "level": level,
        "group_words": [w["word"] for w in group_words],
        "poll_num": 0, "total": total, "asked": [],
        "scores": {}, "poll_answers": {}, "answered_polls": {},
        "active": False, "unanswered_streak": 0,
        "last_poll_id": None,
        "starter_id": user_id,
        "starter_name": callback.from_user.first_name or "Obunachi",
        "ready_users": {str(user_id): callback.from_user.first_name or "Obunachi"},
        "phase": "lobby",
    }
    ready_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tayyor!", callback_data=f"quiz_ready_{chat_id}")]
    ])
    await callback.message.edit_text(
        f"🎯 <b>{group_num}-guruh viktorinasi</b>\n\n"
        f"👥 Tayyor: <b>1 kishi</b>\n✅ {callback.from_user.first_name} tayyor!\n\n"
        f"⏳ Kamida <b>2 kishi</b> tayyor bo'lishi kerak\n"
        f"⏱ <b>30 soniya</b> kutiladi\n\n👇 Tayyor bo'lsangiz bosing:",
        reply_markup=ready_kb
    )
    await callback.answer()
    asyncio.create_task(_lobby_timeout(chat_id, callback.message.message_id))

async def _lobby_timeout(chat_id: int, message_id: int):
    await asyncio.sleep(30)
    qs = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or qs.get("phase") != "lobby":
        return
    ready = qs.get("ready_users", {})
    if len(ready) < 2:
        GROUP_QUIZ_STATE.pop(chat_id, None)
        try:
            await bot.send_message(chat_id,
                "❌ <b>Viktorina bekor qilindi</b>\n\n"
                "😔 Kamida 2 kishi tayyor bo'lishi kerak edi.\n/quiz — qayta urinib ko'ring!")
        except Exception:
            pass
        return
    qs["phase"]  = "running"
    qs["active"] = True
    names = ", ".join(list(ready.values())[:5])
    try:
        await bot.send_message(chat_id,
            f"🚀 <b>Viktorina boshlanmoqda!</b>\n\n"
            f"✅ Ishtirokchilar ({len(ready)} kishi): <b>{names}</b>\n"
            f"📊 Jami savollar: <b>{qs['total']}  </b>\n"
            f"⏱ Har savol uchun <b>20 soniya</b>\n\n🛑 To'xtatish: /stopquiz")
    except Exception:
        pass
    await _send_group_poll(chat_id)

@dp.callback_query(F.data.startswith("quiz_ready_"))
async def quiz_ready_cb(callback: types.CallbackQuery):
    chat_id = int(callback.data.split("_")[2])
    qs      = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or qs.get("phase") != "lobby":
        await callback.answer("⚠️ Lobby topilmadi.", show_alert=True)
        return
    user_id   = str(callback.from_user.id)
    user_name = callback.from_user.first_name or "Obunachi"
    if user_id in qs["ready_users"]:
        await callback.answer("✅ Siz allaqachon tayyor!", show_alert=True)
        return
    qs["ready_users"][user_id] = user_name
    count = len(qs["ready_users"])
    names = "\n".join([f"✅ {n}" for n in list(qs["ready_users"].values())])
    ready_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Tayyor! ({count} kishi)", callback_data=f"quiz_ready_{chat_id}")]
    ])
    try:
        await callback.message.edit_text(
            f"🎯 <b>{qs['group_num']}-guruh viktorinasi</b>\n\n"
            f"👥 Tayyor bo'lganlar: <b>{count} kishi</b>\n{names}\n\n"
            f"⏳ <b>30 soniya</b> kutilmoqda...\n👇 Siz ham tayyor bo'ling:",
            reply_markup=ready_kb
        )
    except Exception:
        pass
    await callback.answer(f"✅ Tayyor! ({count} kishi)")

async def _send_group_poll(chat_id: int):
    qs = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or not qs.get("active"):
        return
    poll_num = qs["poll_num"]
    total    = qs["total"]
    if qs.get("unanswered_streak", 0) >= 5:
        qs["active"] = False
        txt = f"⏹ <b>Viktorina to'xtatildi!</b>\n\n😔 5 ta savolga ketma-ket javob berilmadi.\n/quiz — yana boshlash"
        if qs.get("scores"):
            txt += "\n\n" + await _build_result_text(chat_id, qs, poll_num)
        await bot.send_message(chat_id, txt)
        GROUP_QUIZ_STATE.pop(chat_id, None)
        return
    if poll_num >= total:
        await _finish_group_quiz(chat_id, qs)
        return
    level     = qs["level"]
    word_keys = qs["group_words"]
    all_words = words.get(level, [])
    pool      = [w for w in all_words if w["word"] in word_keys]
    asked     = qs.get("asked", [])
    remaining = [w for w in pool if w["word"] not in asked]
    if not remaining: remaining = pool
    correct      = random.choice(remaining)
    qs["asked"].append(correct["word"])
    wrong_pool   = [w for w in all_words if w["word"] != correct["word"]]
    wrong_sample = random.sample(wrong_pool, min(3, len(wrong_pool)))
    options      = [correct["translation"]] + [w["translation"] for w in wrong_sample]
    random.shuffle(options)
    correct_idx  = options.index(correct["translation"])
    qs["poll_num"] += 1
    cur_num = qs["poll_num"]
    sent    = await bot.send_poll(
        chat_id=chat_id,
        question=f"❓ {cur_num}/{total} — 🇬🇧 {correct['word'].upper()} tarjimasini toping!",
        options=options, type="quiz",
        correct_option_id=correct_idx,
        explanation=f"💡 {correct.get('example','')}",
        is_anonymous=False, open_period=20
    )
    poll_id = sent.poll.id
    qs["poll_answers"][poll_id]   = correct_idx
    qs["answered_polls"][poll_id] = set()
    qs["last_poll_id"]            = poll_id
    asyncio.create_task(_delayed_next_poll(chat_id, poll_id, 22))

async def _delayed_next_poll(chat_id: int, poll_id: str, delay: int):
    await asyncio.sleep(delay)
    qs = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or not qs.get("active"):
        return
    if qs.get("last_poll_id") != poll_id:
        return
    answered = qs.get("answered_polls", {}).get(poll_id, set())
    if len(answered) == 0:
        qs["unanswered_streak"] = qs.get("unanswered_streak", 0) + 1
    else:
        qs["unanswered_streak"] = 0
    await _send_group_poll(chat_id)

async def _build_result_text(chat_id: int, qs: dict, shown_total: int) -> str:
    group_num     = qs["group_num"]
    scores        = qs.get("scores", {})
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    txt  = f"📊 <b>{group_num}-guruh — natijalar:</b>\nJami savollar: <b>{shown_total}</b>\n━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇","🥈","🥉"]
    for i,(uid,cnt) in enumerate(sorted_scores[:10]):
        medal  = medals[i] if i<3 else f"{i+1}."
        winner = " 🏆 G'OLIB!" if i==0 else ""
        try:
            m    = await bot.get_chat_member(chat_id, int(uid))
            name = m.user.first_name or "User"
        except Exception:
            name = f"Ishtirokchi {i+1}"
        txt += f"{medal} <b>{name}</b> — {cnt}/{shown_total} ✅{winner}\n"
    txt += "\n🎉 Barcha ishtirokchilarga rahmat!\n/quiz — qayta boshlash"
    return txt

async def _finish_group_quiz(chat_id: int, qs: dict):
    group_num = qs["group_num"]
    total     = qs["total"]
    qs["active"] = False
    if qs.get("scores"):
        header = f"🏆 <b>{group_num}-guruh viktorinasi yakunlandi!</b>\n\n"
        txt    = header + await _build_result_text(chat_id, qs, total)
    else:
        txt = f"🏆 <b>{group_num}-guruh yakunlandi!</b>\n\n😔 Hech kim qatnashmadi.\n/quiz — yana urinib ko'ring!"
    await bot.send_message(chat_id, txt)
    GROUP_QUIZ_STATE.pop(chat_id, None)

@dp.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer):
    poll_id = poll_answer.poll_id
    user_id = str(poll_answer.user.id)
    for chat_id, qs in list(GROUP_QUIZ_STATE.items()):
        if poll_id in qs.get("poll_answers", {}):
            correct_idx = qs["poll_answers"][poll_id]
            if poll_id not in qs["answered_polls"]:
                qs["answered_polls"][poll_id] = set()
            qs["answered_polls"][poll_id].add(user_id)
            if poll_answer.option_ids and poll_answer.option_ids[0] == correct_idx:
                qs["scores"][user_id] = qs["scores"].get(user_id, 0) + 1
            break
