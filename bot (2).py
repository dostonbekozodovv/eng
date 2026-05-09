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

from config import BOT_TOKEN, ADMIN_IDS, CARD_NUMBER, CARD_OWNER, VIP_PRICE
from db import (
    get_or_create_user, get_user, update_streak, add_score, add_referral_earnings,
    add_learned_word, set_vip, is_vip, create_vip_request,
    get_stats, get_all_user_ids, get_top_scores, get_top_referrals,
    update_user_level, update_user_group,
    get_pending_vip_requests, update_vip_request_status
)
from words import words

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher(storage=MemoryStorage())

# ═══════════════════════════════════════
# FSM STATES
# ═══════════════════════════════════════
class QuizState(StatesGroup):
    answering = State()

class VipState(StatesGroup):
    waiting_name  = State()
    waiting_check = State()

class BroadcastState(StatesGroup):
    waiting = State()

# ═══════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════
def main_kb(user_id: int = None):
    vip = is_vip(user_id) if user_id else False
    buttons = [
        [KeyboardButton(text="📚 So'z o'rgan"), KeyboardButton(text="🧠 Test")],
        [KeyboardButton(text="🔥 Streak"),       KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="👥 Referal"),       KeyboardButton(text="⚙️ Daraja")],
    ]
    if vip:
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

# ═══════════════════════════════════════
# /start — referal link bilan
# ═══════════════════════════════════════
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject = None):
    user_id  = message.from_user.id
    name     = message.from_user.first_name or "Do'st"
    username = message.from_user.username or ""

    # t.me/bot?start=123456789  →  ref_id = 123456789
    ref_id = None
    if command and command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id == user_id:
            ref_id = None

    user = get_or_create_user(user_id, name, username, ref_id)
    update_streak(user_id)

    if ref_id:
        # Referalga xabar yuborish
        try:
            await bot.send_message(
                ref_id,
                f"🎉 Yangi do'stingiz <b>{name}</b> botga qo'shildi!\n"
                f"Referal hisobingiz yangilandi. 👥"
            )
        except Exception:
            pass

    if not user.get("level"):
        await message.answer(
            f"👋 Salom, <b>{name}</b>!\n\nDarajangizni tanlang:",
            reply_markup=level_kb()
        )
    else:
        await message.answer(
            f"👋 Xush kelibsiz, <b>{name}</b>!",
            reply_markup=main_kb(user_id)
        )

# ═══════════════════════════════════════
# DARAJA TANLASH
# ═══════════════════════════════════════
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
    await callback.answer(f"✅ Daraja: {level_map.get(level, level)}")
    await callback.message.edit_text(f"✅ Daraja o'rnatildi: <b>{level_map.get(level, level)}</b>")
    await callback.message.answer("O'rganishni boshlashingiz mumkin:", reply_markup=main_kb(user_id))

@dp.message(F.text == "⚙️ Daraja")
async def change_level(message: types.Message):
    await message.answer("Yangi darajangizni tanlang:", reply_markup=level_kb())

# ═══════════════════════════════════════
# SO'Z O'RGANISH (guruhlar bo'yicha)
# ═══════════════════════════════════════
@dp.message(F.text == "📚 So'z o'rgan")
async def learn_word(message: types.Message):
    await _send_next_word(message, message.from_user.id)

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

    all_words = words.get(level, [])
    start_idx = (group_num - 1) * 20
    end_idx   = start_idx + 20
    group_words = all_words[start_idx:end_idx]

    if not group_words:
        txt = "🎊 Barcha so'zlarni tugatdingiz! Tabriklaymiz!"
        if edit:
            await target.edit_text(txt)
        else:
            await target.answer(txt)
        return

    learned   = user.get("learned_words") or []
    unlearned = [w for w in group_words if w["word"] not in learned]

    if not unlearned:
        # Guruh so'zlari tugadi — keyingi guruhga o'tish uchun 70% test kerak
        # VIP bo'lsa cheklovsiz o'tadi
        vip_user = user.get("is_vip", False)

        if vip_user:
            # VIP — to'g'ridan to'g'ri o'tish
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔓 Keyingi guruhni ochish", callback_data="next_group")]
            ])
            txt = (
                f"✅ <b>{group_num}-guruh</b> so'zlari tugatildi!\n\n"
                f"💎 VIP sifatida to'g'ridan-to'g'ri keyingi guruhga o'tishingiz mumkin."
            )
        else:
            # Oddiy — avval shu guruh bo'yicha test topshirsin
            # current_group_quiz callback orqali test boshlaydi
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🧠 {group_num}-guruh testini topshirish",
                    callback_data=f"group_quiz_{group_num}"
                )]
            ])
            txt = (
                f"✅ <b>{group_num}-guruh</b> so'zlarini o'qib chiqdingiz!\n\n"
                f"⚠️ Keyingi guruhga o'tish uchun ushbu guruh testidan\n"
                f"<b>kamida 70% to'g'ri</b> javob bering.\n\n"
                f"💎 VIP bo'lsangiz cheklovsiz o'tasiz!"
            )
        if edit:
            await target.edit_text(txt, reply_markup=kb)
        else:
            await target.answer(txt, reply_markup=kb)
        return

    word_data = unlearned[0]
    add_learned_word(user_id, word_data["word"])
    add_score(user_id, 2)

    remaining = len(unlearned) - 1
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Keyingi so'z", callback_data="next_word")],
        [InlineKeyboardButton(text="🧠 Test boshlash", callback_data="quiz_start")],
    ])
    txt = (
        f"📦 <b>Guruh {group_num}</b>  |  Qoldi: {remaining} so'z\n\n"
        f"🇬🇧 <b>{word_data['word']}</b>\n"
        f"🇺🇿 <b>{word_data['translation']}</b>\n\n"
        f"💬 <i>{word_data['example']}</i>"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "next_group")
async def next_group_cb(callback: types.CallbackQuery):
    """Faqat VIP uchun — to'g'ridan keyingi guruhga o'tish"""
    user_id = callback.from_user.id
    user    = get_user(user_id)
    if not user.get("is_vip"):
        await callback.answer("💎 Bu imkoniyat faqat VIP uchun!", show_alert=True)
        return
    new_group = (user.get("current_group") or 1) + 1
    update_user_group(user_id, new_group)
    await callback.message.edit_text(
        f"🚀 <b>{new_group}-guruh ochildi!</b>\n"
        f"Yangi 20 ta so'z sizni kutmoqda. 💎"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("group_quiz_"))
async def group_quiz_start(callback: types.CallbackQuery, state: FSMContext):
    """Guruh testi — 70% to'g'ri bo'lsa keyingi guruhga o'tadi"""
    user_id   = callback.from_user.id
    user      = get_user(user_id)
    group_num = int(callback.data.split("_")[2])
    level     = user.get("level", "beginner")

    all_words   = words.get(level, [])
    start_idx   = (group_num - 1) * 20
    end_idx     = start_idx + 20
    group_words = all_words[start_idx:end_idx]

    if len(group_words) < 4:
        await callback.answer("So'zlar yetarli emas!", show_alert=True)
        return

    # 10 ta savol — shu guruh so'zlaridan
    total = min(10, len(group_words))
    await state.set_state(QuizState.answering)
    await state.update_data(
        q_num=1, total=total, correct_count=0,
        level=level,
        group_quiz=True,       # bu guruh testi ekanligini belgilash
        group_num=group_num,
        group_words=[w["word"] for w in group_words]
    )
    await _send_group_quiz(callback.message, user_id, state, edit=False)
    await callback.answer()

async def _send_group_quiz(target, user_id: int, state: FSMContext, edit: bool = False):
    """Faqat shu guruh so'zlaridan test"""
    data          = await state.get_data()
    q_num         = data.get("q_num", 1)
    total         = data.get("total", 10)
    correct_count = data.get("correct_count", 0)
    level         = data.get("level", "beginner")
    group_word_keys = data.get("group_words", [])

    all_words  = words.get(level, [])
    group_pool = [w for w in all_words if w["word"] in group_word_keys]

    if len(group_pool) < 4:
        txt = "⚠️ So'zlar yetarli emas."
        await (target.edit_text(txt) if edit else target.answer(txt))
        return

    correct      = random.choice(group_pool)
    wrong_pool   = [w for w in group_pool if w["word"] != correct["word"]]
    if len(wrong_pool) < 3:
        # Yetarli noto'g'ri variant yo'q — boshqa darajadan to'ldirish
        extra = [w for w in all_words if w["word"] not in group_word_keys]
        wrong_pool += extra
    wrong_sample = random.sample(wrong_pool, 3)
    options      = [correct] + wrong_sample
    random.shuffle(options)

    await state.update_data(correct_word=correct["word"])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=opt["translation"],
            callback_data=f"gqa_{opt['word']}_{correct['word']}"
        )]
        for opt in options
    ])

    progress = "✅" * correct_count + "⬜" * (total - correct_count)
    txt = (
        f"📋 <b>Guruh testi {data.get('group_num',1)}</b> — {q_num}/{total}\n"
        f"{progress}\n\n"
        f"🇬🇧 <b>{correct['word']}</b> so'zining tarjimasini toping:"
    )
    await (target.edit_text(txt, reply_markup=kb) if edit else target.answer(txt, reply_markup=kb))

@dp.callback_query(F.data.startswith("gqa_"), QuizState.answering)
async def group_quiz_answer(callback: types.CallbackQuery, state: FSMContext):
    """Guruh testi javobi"""
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
        await callback.answer("✅ To'g'ri! +5 ball")
    else:
        await callback.answer(f"❌ Noto'g'ri! To'g'risi: {correct}", show_alert=True)

    if q_num >= total:
        await state.clear()
        percent  = int((correct_count / total) * 100)
        passed   = percent >= 70

        if passed:
            # Keyingi guruhga o'tkazish
            new_group = group_num + 1
            update_user_group(user_id, new_group)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📚 Keyingi guruhni boshlash", callback_data="next_word")]
            ])
            await callback.message.edit_text(
                f"🎉 <b>Test muvaffaqiyatli topshirildi!</b>\n\n"
                f"✅ To'g'ri: <b>{correct_count}/{total}</b> ({percent}%)\n"
                f"🔓 <b>{new_group}-guruh ochildi!</b> Yangi so'zlar sizi kutmoqda. 🚀",
                reply_markup=kb
            )
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Qaytadan urinib ko'rish", callback_data=f"group_quiz_{group_num}")],
                [InlineKeyboardButton(text="📚 So'zlarni takrorlash",    callback_data="next_word")],
            ])
            await callback.message.edit_text(
                f"😔 <b>Test o'tmadi!</b>\n\n"
                f"✅ To'g'ri: <b>{correct_count}/{total}</b> ({percent}%)\n"
                f"⚠️ Keyingi guruh uchun <b>kamida 70%</b> kerak.\n\n"
                f"So'zlarni yana bir marta takrorlab, qayta urinib ko'ring!",
                reply_markup=kb
            )
    else:
        await state.update_data(q_num=q_num + 1, correct_count=correct_count)
        await _send_group_quiz(callback.message, user_id, state, edit=True)

# ═══════════════════════════════════════
# TEST TIZIMI
# ═══════════════════════════════════════
async def _send_quiz(target, user_id: int, state: FSMContext, edit: bool = False):
    data          = await state.get_data()
    q_num         = data.get("q_num", 1)
    total         = data.get("total", 10)
    correct_count = data.get("correct_count", 0)
    level         = data.get("level", "beginner")

    word_list = words.get(level, words.get("beginner", []))
    if len(word_list) < 4:
        txt = "⚠️ So'zlar ro'yxati yetarli emas."
        if edit:
            await target.edit_text(txt)
        else:
            await target.answer(txt)
        return

    correct      = random.choice(word_list)
    wrong_pool   = [w for w in word_list if w["word"] != correct["word"]]
    wrong_sample = random.sample(wrong_pool, min(3, len(wrong_pool)))
    options      = [correct] + wrong_sample
    random.shuffle(options)

    await state.update_data(correct_word=correct["word"])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=opt["translation"],
            callback_data=f"qa_{opt['word']}_{correct['word']}"
        )]
        for opt in options
    ])

    progress = "✅" * correct_count + "⬜" * (total - q_num + 1 - (total - q_num + 1 - correct_count))
    txt = (
        f"🧠 <b>Test</b> — {q_num}/{total}\n"
        f"{progress}\n\n"
        f"🇬🇧 <b>{correct['word']}</b> so'zining tarjimasini toping:"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.message(F.text == "🧠 Test")
async def start_quiz(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user or not user.get("level"):
        await message.answer("Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    learned = user.get("learned_words") or []
    if len(learned) < 4:
        await message.answer("⚠️ Kamida 4 ta so'z o'rganib keyin test boshlang.")
        return
    total = 10
    await state.set_state(QuizState.answering)
    await state.update_data(q_num=1, total=total, correct_count=0, level=user["level"])
    await _send_quiz(message, message.from_user.id, state)

@dp.callback_query(F.data == "quiz_start")
async def quiz_start_cb(callback: types.CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if not user or not user.get("level"):
        await callback.message.answer("Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    learned = user.get("learned_words") or []
    if len(learned) < 4:
        await callback.message.answer("⚠️ Kamida 4 ta so'z o'rganib keyin test boshlang.")
        return
    total = 10
    await state.set_state(QuizState.answering)
    await state.update_data(q_num=1, total=total, correct_count=0, level=user["level"])
    await _send_quiz(callback.message, callback.from_user.id, state)
    await callback.answer()

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

    if chosen == correct:
        correct_count += 1
        add_score(user_id, 10)
        await callback.answer("✅ To'g'ri! +10 ball")
    else:
        await callback.answer(f"❌ Noto'g'ri! To'g'risi: {correct}", show_alert=True)

    if q_num >= total:
        await state.clear()
        user    = get_user(user_id)
        percent = int((correct_count / total) * 100)
        emoji   = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "😅")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Qaytadan test",  callback_data="quiz_start")],
            [InlineKeyboardButton(text="📚 So'z o'rganish", callback_data="next_word")],
        ])
        await callback.message.edit_text(
            f"🎯 <b>Test yakunlandi!</b>  {emoji}\n\n"
            f"✅ To'g'ri: <b>{correct_count}/{total}</b>\n"
            f"📊 Natija: <b>{percent}%</b>\n"
            f"⭐ Jami ball: <b>{user.get('score', 0)}</b>",
            reply_markup=kb
        )
    else:
        await state.update_data(q_num=q_num + 1, correct_count=correct_count)
        await _send_quiz(callback.message, user_id, state, edit=True)

# ═══════════════════════════════════════
# STREAK
# ═══════════════════════════════════════
@dp.message(F.text == "🔥 Streak")
async def show_streak(message: types.Message):
    user   = get_user(message.from_user.id)
    streak = user.get("streak", 0)
    if streak >= 30:
        badge = "🏆 Ustoz!"
    elif streak >= 14:
        badge = "🔥 Ajoyib!"
    elif streak >= 7:
        badge = "💪 Yaxshi!"
    else:
        badge = "🌱 Davom et!"

    await message.answer(
        f"🔥 <b>STREAK</b>\n\n"
        f"Ketma-ketlik: <b>{streak} kun</b>  {badge}\n\n"
        f"Har kuni o'rganib streak'ingizni saqlang!\n"
        f"• 7 kun  → 💪\n"
        f"• 14 kun → 🔥\n"
        f"• 30 kun → 🏆"
    )

# ═══════════════════════════════════════
# REYTING
# ═══════════════════════════════════════
@dp.message(F.text == "🏆 Reyting")
async def show_rating(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Ball bo'yicha",    callback_data="rank_score"),
         InlineKeyboardButton(text="👥 Referal bo'yicha", callback_data="rank_ref")],
    ])
    await message.answer("🏆 <b>Reyting</b> — tur tanlang:", reply_markup=kb)

@dp.callback_query(F.data == "rank_score")
async def show_top_score(callback: types.CallbackQuery):
    top  = get_top_scores(10)
    text = "🏆 <b>TOP 10 — BALL</b>\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, u in enumerate(top, 1):
        vip_badge = " 💎" if u.get("is_vip") else ""
        medal     = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {u['name']}{vip_badge} — <b>{u['score']}</b> ball\n"
    await callback.message.edit_text(text)

@dp.callback_query(F.data == "rank_ref")
async def show_top_ref(callback: types.CallbackQuery):
    top  = get_top_referrals(10)
    text = "👥 <b>TOP 10 — REFERAL</b>\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, u in enumerate(top, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {u['name']} — <b>{u['referral_count']}</b> ta taklif\n"
    await callback.message.edit_text(text)

# ═══════════════════════════════════════
# REFERAL TIZIMI
# ═══════════════════════════════════════
@dp.message(F.text == "👥 Referal")
async def referal_menu(message: types.Message):
    user_id  = message.from_user.id
    user     = get_user(user_id)
    bot_info = await bot.get_me()

    # Havola: t.me/botusername?start=USER_ID
    ref_link  = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_count = user.get("referral_count", 0)

    await message.answer(
        f"👥 <b>REFERAL TIZIMI</b>\n\n"
        f"🔗 <b>Sizning havolangiz:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"👤 Taklif etilganlar: <b>{ref_count} ta</b>\n\n"
        f"<b>Qoidalar:</b>\n"
        f"✅ Havolani do'stlarga yuboring\n"
        f"✅ Har juma eng ko'p referal qilgan g'olib <b>10 000 so'm</b> yutadi!\n"
        f"✅ Har taklif uchun +5 ball"
    )

# ═══════════════════════════════════════
# VIP TIZIMI
# ═══════════════════════════════════════
@dp.message(F.text == "💎 VIP Sotib olish")
async def vip_buy(message: types.Message):
    user_id = message.from_user.id
    if is_vip(user_id):
        await message.answer("✅ Siz allaqachon VIP foydalanuvchisiz!")
        return

    await message.answer(
        f"💎 <b>VIP PREMIUM</b>\n\n"
        f"💰 Narxi: <b>{VIP_PRICE:,} so'm</b>\n\n"
        f"<b>VIP imkoniyatlari:</b>\n"
        f"✅ Barcha daraja so'zlari\n"
        f"✅ Reklamasiz foydalanish\n"
        f"✅ Haftalik bonus mukofoti\n"
        f"✅ 2x tezroq ball to'plash\n\n"
        f"💳 Karta raqami:\n<code>{CARD_NUMBER}</code>\n"
        f"👤 Karta egasi: <b>{CARD_OWNER}</b>\n\n"
        f"To'lov qilgach tugmani bosing 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ To'lov qildim", callback_data="vip_pay")],
            [InlineKeyboardButton(text="❌ Bekor",         callback_data="vip_cancel")],
        ])
    )

@dp.callback_query(F.data == "vip_pay")
async def vip_pay_cb(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(VipState.waiting_name)
    await callback.message.answer("👤 Ism-familiyangizni kiriting (F.I.Sh.):")
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
        "📸 Endi to'lov chekini yuboring:\n"
        "<i>(Rasm yoki screenshot)</i>"
    )

# FOTO yoki DOCUMENT qabul qiladi
@dp.message(VipState.waiting_check, F.photo | F.document)
async def vip_get_check(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data    = await state.get_data()

    if message.photo:
        file_id = message.photo[-1].file_id
    else:
        file_id = message.document.file_id

    create_vip_request(user_id, data["full_name"], VIP_PRICE, file_id)
    await state.clear()

    await message.answer(
        "✅ <b>Arizangiz qabul qilindi!</b>\n\n"
        "Adminlar 24 soat ichida ko'rib chiqadilar.\n"
        "Natija haqida xabar beriladi."
    )

    # Har bir adminga xabar + chek + tasdiqlash tugmalari
    user     = get_user(user_id)
    username = f"@{message.from_user.username}" if message.from_user.username else "yo'q"
    caption  = (
        f"🆕 <b>VIP SO'ROV</b>\n\n"
        f"👤 Ism: <b>{data['full_name']}</b>\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
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
    await message.answer("⚠️ Iltimos, rasm (screenshot) yoki fayl yuboring.")

# ═══════════════════════════════════════
# ADMIN — VIP TASDIQLASH / RAD ETISH
# ═══════════════════════════════════════
@dp.callback_query(F.data.startswith("vadm_ok_"))
async def admin_vip_approve(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    target_id = int(callback.data.split("_")[2])
    set_vip(target_id, True)

    # Foydalanuvchiga xabar
    try:
        await bot.send_message(
            target_id,
            "🎉 <b>Tabriklaymiz!</b>\n\n"
            "VIP so'rovingiz tasdiqlandi!\n"
            "Endi barcha VIP imkoniyatlardan foydalanishingiz mumkin. 💎",
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
            "To'lov ma'lumotlari tasdiqlanmadi.\n"
            "Muammo bo'lsa admin bilan bog'laning."
        )
    except Exception as e:
        logger.error(f"Rad etish xabari {target_id} ga yuborib bo'lmadi: {e}")

    new_caption = (callback.message.caption or "") + "\n\n❌ <b>RAD ETILDI</b>"
    await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    await callback.answer("❌ Rad etildi")

# ═══════════════════════════════════════
# VIP PANEL (foydalanuvchi uchun)
# ═══════════════════════════════════════
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
            f"👥 Jami: {stats['total']}\n"
            f"💎 VIP: {stats['vip']}\n"
            f"⏳ Kutilmoqda: {stats['pending_vip']}",
            reply_markup=kb
        )
        return

    if not is_vip(user_id):
        await message.answer("❌ Siz VIP emassiz.")
        return

    vip_since = user.get("vip_since")
    date_str  = vip_since.strftime("%d.%m.%Y") if vip_since else "—"
    await message.answer(
        f"💎 <b>VIP PANEL</b>\n\n"
        f"Siz VIP foydalanuvchisiz!\n"
        f"📅 VIP olgan sana: {date_str}\n\n"
        f"✅ Barcha imkoniyatlar faol."
    )

# ═══════════════════════════════════════
# ADMIN QOʻSHIMCHA KOMANDALAR
# ═══════════════════════════════════════
@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Ruxsat yo'q")
        return
    stats = get_stats()
    await message.answer(
        f"👨‍💼 <b>ADMIN PANEL</b>\n\n"
        f"👥 Jami foydalanuvchi: {stats['total']}\n"
        f"💎 VIP: {stats['vip']}\n"
        f"⏳ Kutilayotgan VIP: {stats['pending_vip']}"
    )

@dp.callback_query(F.data == "adm_stats")
async def adm_stats_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    stats = get_stats()
    await callback.message.edit_text(
        f"📊 <b>STATISTIKA</b>\n\n"
        f"👥 Jami: {stats['total']}\n"
        f"💎 VIP: {stats['vip']}\n"
        f"⏳ Kutilmoqda: {stats['pending_vip']}"
    )

@dp.callback_query(F.data == "adm_pending")
async def adm_pending_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    reqs = get_pending_vip_requests()
    if not reqs:
        await callback.answer("Kutilayotgan so'rovlar yo'q", show_alert=True)
        return
    await callback.answer(f"{len(reqs)} ta so'rov kutmoqda", show_alert=True)

@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(BroadcastState.waiting)
    await callback.message.answer("📢 Yubormoqchi bo'lgan xabaringizni yozing:")
    await callback.answer()

@dp.message(Command("broadcast"))
async def broadcast_cmd(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Ruxsat yo'q")
        return
    await state.set_state(BroadcastState.waiting)
    await message.answer("📢 Yubormoqchi bo'lgan xabaringizni yozing:")

@dp.message(BroadcastState.waiting)
async def broadcast_send(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    user_ids = get_all_user_ids()
    sent = 0
    for uid in user_ids:
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ {sent} ta foydalanuvchiga yuborildi.")
    await state.clear()

# ═══════════════════════════════════════
# HAFTALIK BONUS (har juma 18:00)
# ═══════════════════════════════════════
async def weekly_bonus_task():
    while True:
        try:
            now = datetime.now()
            # Keyingi juma, soat 18:00 ni hisoblash
            days_until_friday = (4 - now.weekday()) % 7
            if days_until_friday == 0 and now.hour >= 18:
                days_until_friday = 7
            target = now.replace(hour=18, minute=0, second=0, microsecond=0)
            target += timedelta(days=days_until_friday)

            wait_seconds = (target - now).total_seconds()
            logger.info(f"Keyingi haftalik bonus: {target} ({int(wait_seconds)}s keyin)")
            await asyncio.sleep(max(60, wait_seconds))

            top_list = get_top_referrals(1)
            if top_list:
                winner = top_list[0]
                add_referral_earnings(winner["user_id"], 10000)
                try:
                    await bot.send_message(
                        winner["user_id"],
                        f"🎉 <b>HAFTALIK G'OLIB!</b>\n\n"
                        f"Siz bu haftada eng ko'p do'st taklif qildingiz!\n"
                        f"💰 <b>+10 000 so'm</b> bonus qo'shildi! 🏆"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Haftalik bonus xatosi: {e}")
            await asyncio.sleep(3600)

# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════
async def main():
    from db import init_db
    init_db()
    logger.info("✅ Bot ishga tushdi!")
    asyncio.create_task(weekly_bonus_task())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
