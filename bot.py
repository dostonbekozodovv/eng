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
    get_conn,
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

# ── Sozlamalar ──
PRIZE_SCORE_AMOUNT = 10_000   # sovrin miqdori (so'm)
PRIZE_BALL_TARGET  = 5_000    # nechi ball yig'sa g'olib bo'ladi
PRIZE_MIN_REFERRAL = 1        # pul yechish uchun minimal referal soni
REFERRAL_BONUS     = 200      # referal uchun ball
TEST_SCORE_BONUS   = 10       # to'g'ri test javobi uchun ball
PRIZE_REF_AMOUNT   = 10_000   # Haftalik referal g'olibi uchun sovrin (so'm)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

# Guruh quiz holati — chat_id bo'yicha saqlanadi
# { chat_id: { poll_id: correct_option_id, scores: {user_id: int}, ... } }
GROUP_QUIZ_STATE: dict = {}

async def _check_score_prize(user_id: int):
    """5 000 ball to'plagan foydalanuvchini tekshirish"""
    user      = get_user(user_id)
    if not user:
        return
    score     = user.get("score", 0)
    ref_count = user.get("referral_count", 0)
    if score >= PRIZE_BALL_TARGET and not user.get("prize_claimed"):
        if ref_count < PRIZE_MIN_REFERRAL:
            try:
                await bot.send_message(
                    user_id,
                    f"🏆 <b>Tabriklaymiz! {PRIZE_BALL_TARGET:,} ball yig'dingiz!</b>\n\n"
                    f"⚠️ Lekin pul yechish uchun kamida <b>{PRIZE_MIN_REFERRAL} ta do'st</b> taklif qilishingiz shart!\n\n"
                    f"👥 Hozirgi referal: <b>{ref_count} ta</b>\n\n"
                    f"👥 Referal bo'limiga o'ting va do'stingizni taklif qiling!"
                )
            except Exception:
                pass
            return
        try:
            bot_info = await bot.get_me()
            username = user.get("username") or str(user_id)
            user_link = f"https://t.me/{username}" if user.get("username") else f"tg://user?id={user_id}"
            await bot.send_message(
                user_id,
                f"🎉 <b>TABRIKLAYMIZ!</b>\n\n"
                f"🏆 Siz <b>{PRIZE_BALL_TARGET:,} ball</b> yig'dingiz!\n"
                f"💰 <b>{PRIZE_SCORE_AMOUNT:,} so'm</b> sovrin yutdingiz!\n\n"
                f"📞 Adminlar siz bilan tez orada bog'lanadi. 🙏"
            )
            for admin_id in ADMIN_IDS:
                uname = user.get("username")
                name  = user.get("name", "?")
                tag   = f"@{uname}" if uname else f"ID: {user_id}"
                await bot.send_message(
                    admin_id,
                    f"🚨 <b>G'OLIB ANIQLANDI!</b>\n\n"
                    f"👤 Foydalanuvchi: {tag} (ID: <code>{user_id}</code>)\n"
                    f"📛 Ism: <b>{name}</b>\n"
                    f"⭐️ Ball: <b>{score}</b>\n"
                    f"👥 Referal: <b>{ref_count} ta</b>\n\n"
                    f"💰 Sovrin: <b>{PRIZE_SCORE_AMOUNT:,} so'm</b> to'lang!\n"
                    f"🔗 <a href=\"{user_link}\">Foydalanuvchi bilan bog'lanish</a>",
                    disable_web_page_preview=True
                )
                # Admin panel uchun g'olib ID ni saqlash
                PRIZE_WINNERS[user_id] = {
                    "name": name, "username": uname,
                    "score": score, "ref_count": ref_count,
                    "link": user_link
                }
        except Exception as e:
            pass
dp  = Dispatcher(storage=MemoryStorage())
PRIZE_WINNERS: dict = {}  # {user_id: {name, username, score, link}}

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

class TestMenuState(StatesGroup):
    select_group = State()

class GroupPollState(StatesGroup):
    selecting_group = State()
    running         = State()

class FeedbackState(StatesGroup):
    waiting = State()

class ResetOneRefState(StatesGroup):
    waiting_id = State()

class SurveyState(StatesGroup):
    running = State()

# So'rovnoma natijalari — xotirada saqlanadi
# { survey_id: { "questions": [...], "answers": {user_id: [ans1, ans2, ...]}, "total_sent": int } }
ACTIVE_SURVEY: dict = {}   # faqat 1 ta aktiv bo'ladi: ACTIVE_SURVEY["current"]
SURVEY_COMPLETED_USERS: set = set()  # so'rovnomani tugatgan userlar (ball olmaslik uchun)
SURVEY_RESULTS: dict = {}  # { user_id: [ans_idx_q0, ans_idx_q1, ...] }

class UserTestState(StatesGroup):
    waiting_question = State()
    waiting_options   = State()
    waiting_answer    = State()
    confirm           = State()

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
def is_group(message_or_chat) -> bool:
    """Guruh yoki superguruh ekanligini tekshiradi"""
    if hasattr(message_or_chat, 'chat'):
        chat = message_or_chat.chat
    else:
        chat = message_or_chat
    return chat.type in ("group", "supergroup")

def main_kb(user_id: int = None, chat=None):
    if chat and is_group(chat):
        return ReplyKeyboardRemove()
    vip      = is_vip(user_id) if user_id else False
    is_admin = user_id in ADMIN_IDS if user_id else False
    vip_btn  = KeyboardButton(text="💎 VIP Panel") if (is_admin or vip) else KeyboardButton(text="💎 VIP Sotib olish")
    buttons = [
        [KeyboardButton(text="📚 So’z o‘rgan"),  KeyboardButton(text="🧠 Test")],
        [KeyboardButton(text="💰 Pul yutug'i"), KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="📖 Grammatika"),    KeyboardButton(text="⚙️ Daraja")],
        [KeyboardButton(text="👥 Referal"),        KeyboardButton(text="🔥 Streak")],
        [KeyboardButton(text="📝 Test yaratish"),  KeyboardButton(text="📋 Qo‘llanma")],
        [KeyboardButton(text="💬 Taklif & Fikr"),  vip_btn],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def ref_progress_bar(count: int, total: int = 3) -> str:
    """3/3 progress bar: [███░░░] 1/3"""
    filled = min(count, total)
    empty  = total - filled
    bar    = "█" * filled + "░" * empty
    pct    = int((filled / total) * 100)
    return f"[{bar}] {filled}/{total} ({pct}%)"

def more_kb():
    """Boshqalar menyusi - reply keyboard (asosiy menyuga o'xshash)"""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👥 Referal"),       KeyboardButton(text="🔥 Streak")],
        [KeyboardButton(text="📝 Test yaratish"), KeyboardButton(text="💬 Taklif & Fikr")],
        [KeyboardButton(text="🏠 Orqaga")],
    ], resize_keyboard=True)



def more_kb():
    """Boshqalar menyusi - inline keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Grammatika",    callback_data="more_grammar"),
         InlineKeyboardButton(text="🔥 Streak",        callback_data="more_streak")],
        [InlineKeyboardButton(text="📝 Test yaratish", callback_data="more_create_test"),
         InlineKeyboardButton(text="📋 Qo‘llanma",     callback_data="more_guide")],
        [InlineKeyboardButton(text="💬 Taklif & Fikr", callback_data="more_feedback"),
         InlineKeyboardButton(text="⚙️ Daraja",        callback_data="more_level")],
    ])


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
    row3 = [InlineKeyboardButton(text="🔄 Qayta test (o'rganilganlar)", callback_data="retake_learned_test")]
    row4 = [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2, row3, row4])

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

# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═
# SUBSCRIPTION MIDDLEWARE
# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═# ═
@dp.message.outer_middleware()
async def subscription_middleware(handler, message: types.Message, data: dict):
    if message.text and message.text.startswith('/start'):
        return await handler(message, data)
    user_id = message.from_user.id if message.from_user else None
    if user_id and CHANNEL_ID:
        if not await check_subscription(user_id):
            await message.answer(
                '📢 Botdan foydalanish uchun kanalimizga obuna bo‘ling!',
                reply_markup=subscribe_kb()
            )
            return
    return await handler(message, data)

# ══════════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════════
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject = None):
    user_id  = message.from_user.id
    name     = message.from_user.first_name or "Do'st"
    username = message.from_user.username or ""
    in_group = is_group(message)

    ref_id = None
    if command and command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id == user_id:
            ref_id = None

    user = get_or_create_user(user_id, name, username, ref_id)
    update_streak(user_id)

    # Guruhda faqat qisqa xabar
    if in_group:
        await message.answer(
            f"👋 Salom, <b>{name}</b>!\n\n"
            f"🤖 <b>LexoBot</b> — ingliz tili o'rganish boti.\n\n"
            f"📌 Guruhda ishlatiladigan komandalar:\n"
            f"/quiz — 🎯 So'z viktorinasi (Poll)\n"
            f"/test — 🧠 Shaxsiy test\n"
            f"/learn — 📚 So'z o'rganish\n"
            f"/streak — 🔥 Streak\n"
            f"/rating — 🏆 Reyting\n\n"
            f"💡 To'liq funksiyalar uchun botga shaxsiy xabar yozing!"
        )
        return

    if not await check_subscription(user_id):
        await message.answer(
            f"👋 Salom, <b>{name}</b>!\n\n"
            f"🔐 Botdan to'liq foydalanish uchun\n"
            f"avval kanalimizga obuna bo'ling 👇\n\n"
            f"<i>Obuna bo'lgach '✅ Tekshirish' tugmasini bosing</i>",
            reply_markup=subscribe_kb()
        )
        return

    # Obuna bor — referal xabarini yuborish (agar yangi foydalanuvchi bo'lsa)
    if ref_id and user.get("is_new"):
        try:
            await bot.send_message(
                ref_id,
                f"🎉 <b>Yangi referal!</b>\n\n"
                f"👤 Siz taklif qilgan <b>{name}</b> botga kirdi!\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⭐️ <b>+50 ball</b> hisoblangiz qo'shildi!"
            )
        except Exception:
            pass

    if not user.get("level"):
        await message.answer(
            f"🎉 <b>Xush kelibsiz, {name}!</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚀 <b>Word Master</b> — ingliz tilini o'rganishning eng qulay yo'li!\n\n"
            "📌 <b>Nima o'rgatasiz?</b>\n"
            "  📚 Yangi so'zlar — guruhma-guruh\n"
            "  🧠 Testlar — bilimni mustahkamlash\n"
            "  📖 Grammatika — zamonlar va qoidalar\n\n"
            "📊 <i>Avval darajangizni tanlang:</i>",
            reply_markup=level_kb()
        )
    else:
        await message.answer(
            f"👋 <b>Qaytib keldingiz, {name}!</b> 🔥\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💪 <i>O'rganishni davom ettiramizmi?</i>",
            reply_markup=main_kb(user_id)
        )

@dp.callback_query(F.data == "check_sub")
async def check_sub_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.delete()
        user = get_user(user_id)

        # Referal: faqat birinchi marta (referral_notified belgisi yo'q bo'lsa)
        ref_id = user.get("referred_by") if user else None
        if ref_id and not user.get("referral_notified"):
            try:
                name = callback.from_user.first_name or "Do'st"
                # Taklif qilganga +50 ball qo'shish
                add_score(int(ref_id), REFERRAL_BONUS)  # referal uchun ball
                # Xabar yuborish
                await bot.send_message(
                    int(ref_id),
                    f"🎉 <b>Yangi referal!</b>\n\n"
                    f"✅ Siz taklif qilgan <b>{name}</b> ro'yxatdan o'tdi!\n"
                    f"⭐️ <b>+50 ball</b> qo'shildi!"
                )
                # 3 ta referal to'lganda VIP avtomatik berish
                referrer = get_user(int(ref_id))
                if referrer:
                    ref_total = referrer.get("referral_count", 0)
                    if ref_total >= 3 and not is_vip(int(ref_id)):
                        import datetime
                        from datetime import datetime as dt2, timedelta as td2
                        vip_until = (dt2.now() + td2(days=30)).strftime("%Y-%m-%d %H:%M:%S")
                        set_vip(int(ref_id), True, vip_until)
                        try:
                            await bot.send_message(
                                int(ref_id),
                                "🎊 <b>TABRIKLAYMIZ!</b>\n\n"
                                "💎 Siz 3 ta do'stingizni taklif qildingiz!\n"
                                "✅ Akkauntingiz <b>1 oylik VIP statusiga</b> o'tdi!\n\n"
                                "🔓 VIP imkoniyatlardan hoziroq foydalaning!"
                            )
                        except Exception:
                            pass
                # Qayta xabar kelmаsin deb belgilash
                conn = get_conn()
                cur  = conn.cursor()
                cur.execute(
                    "UPDATE users SET referral_notified = TRUE WHERE user_id = %s",
                    (user_id,)
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception:
                pass

        if not user or not user.get("level"):
            await callback.message.answer(
                "✅ <b>Obuna tasdiqlandi!</b>\n\nDarajangizni tanlang:",
                reply_markup=level_kb()
            )
        else:
            await callback.message.answer(
                "✅ <b>Xush kelibsiz!</b> 🎉",
                reply_markup=main_kb(user_id)
            )
    else:
        await callback.answer("❗ Hali obuna bo'lmadingiz!", show_alert=True)

@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    if is_group(callback.message):
        await callback.message.answer(
            "📌 Guruh komandalari:\n"
            "/quiz — 🎯 Viktorina\n"
            "/test — 🧠 Test\n"
            "/learn — 📚 So'z o'rganish\n"
            "/streak — 🔥 Streak\n"
            "/rating — 🏆 Reyting"
        )
    else:
        await callback.message.answer(
            "🏠 <b>Bosh menyu</b>",
            reply_markup=main_kb(user_id)
        )
    await callback.answer()

# ══════════════════════════════════════════════════
# SLASH KOMANDALAR (guruh va shaxsiy uchun)
# ══════════════════════════════════════════════════
@dp.message(Command("menu"))
async def cmd_menu(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    get_or_create_user(user_id, message.from_user.first_name or "Do'st", message.from_user.username or "")
    if is_group(message):
        await message.answer(
            "📌 Guruh komandalari:\n"
            "/quiz — 🎯 Viktorina\n"
            "/test — 🧠 Test\n"
            "/learn — 📚 So'z o'rganish\n"
            "/streak — 🔥 Streak\n"
            "/rating — 🏆 Reyting"
        )
    else:
        await message.answer("🏠 <b>Bosh menyu</b>", reply_markup=main_kb(user_id))

@dp.message(Command("test"))
async def cmd_test(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user    = get_user(user_id)
    if not user:
        user = get_or_create_user(user_id, message.from_user.first_name or "Do'st", message.from_user.username or "")
    if not user.get("level"):
        await message.reply("⚙️ Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    learned = user.get("learned_words") or []
    if len(learned) < 4:
        await message.reply(
            "⚠️ <b>So'zlar yetarli emas!</b>\n\n"
            "Test uchun kamida <b>4 ta so'z</b> o'rganing.\n"
            "📚 /learn buyrug'ini bosing!"
        )
        return
    await _show_test_menu(message, user_id, edit=False)

@dp.message(Command("learn"))
async def cmd_learn(message: types.Message):
    user_id = message.from_user.id
    get_or_create_user(user_id, message.from_user.first_name or "Do'st", message.from_user.username or "")
    await _send_next_word(message, user_id, edit=False)

@dp.message(Command("grammar"))
async def cmd_grammar(message: types.Message):
    await _show_grammar_menu(message, edit=False)

@dp.message(Command("streak"))
async def cmd_streak(message: types.Message):
    # streak handlerini qayta ishlatish
    user_id = message.from_user.id
    user    = get_user(user_id)
    if not user:
        await message.answer("❌ Avval /start bosing.")
        return
    streak  = user.get("streak", 0)
    best    = user.get("best_streak", 0)
    await message.answer(
        f"🔥 <b>STREAK</b>\n\n"
        f"📅 Hozirgi streak: <b>{streak} kun</b>\n"
        f"🏆 Eng yuqori: <b>{best} kun</b>"
    )

@dp.message(Command("rating"))
async def cmd_rating(message: types.Message):
    top = get_top_scores(10)
    if not top:
        await message.answer("📊 Hali reyting yo'q.")
        return
    text = "🏆 <b>TOP-10 REYTING</b>\n\n━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇","🥈","🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, u in enumerate(top):
        name  = u.get("name") or f"User{u['user_id']}"
        score = u.get("score", 0)
        text += f"{medals[i]} <b>{name}</b> — {score} ball\n"
    await message.answer(text)


async def show_referral(message: types.Message):
    user_id   = message.from_user.id
    user      = get_user(user_id)
    if not user:
        await message.answer("❌ Avval /start bosing.")
        return
    bot_info  = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_count = user.get("referral_count", 0)
    needed    = max(0, 3 - ref_count)
    bar       = ref_progress_bar(ref_count)
    if ref_count >= 3:
        status = "✅ <b>Barakalla! VIP faollashtirildi!</b>"
    elif needed == 1:
        status = "🔥 Yana <b>1 ta doʿst</b> qoldi — VIP yaqin!"
    else:
        status = f"⏳ VIP uchun yana <b>{needed} ta doʿst</b> taklif qiling."
    share_text = f"🎁 Bu botda ingliz tilini o‘rganmoqdaman! Sen ham ko‘r: {ref_link}"
    text = (
        "🎁 <b>Shoshiling! Sizga sovgʿa bor!</b>\n\n"
        "Sizga VIP status berilishi uchun atigi <b>3 ta doʿstingiz</b> botga kirishi kifoya.\n\n"
        f"📊 Progress:\n{bar}\n"
        f"{status}\n\n"
        "⏳ <b>Diqqat:</b> Bu imkoniyat faqat <b>24 soat</b> amal qiladi!\n\n"
        f"🔗 Sizning shaxsiy havolangiz:\n<code>{ref_link}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🚀 Doʿstlarimga ulashish",
            switch_inline_query=share_text
        )
    ]])
    await message.answer(text, reply_markup=kb)

@dp.message(Command("referral"))
async def cmd_referral(message: types.Message):
    await show_referral(message)

@dp.message(Command("vip"))
async def cmd_vip(message: types.Message):
    user_id = message.from_user.id
    if is_vip(user_id):
        await message.answer("💎 Siz VIP foydalanuvchisiz! 🎉")
    else:
        await message.answer(
            "💎 <b>VIP</b> bo'lish uchun to'lov qiling.\n"
            "Batafsil: /start bosib botga o'ting."
        )

# ══════════════════════════════════════════════════
# /quiz — GURUH VIKTORINASI (Telegram Poll, 20 savol)
# ══════════════════════════════════════════════════
@dp.message(Command("quiz"))
async def cmd_quiz(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user    = get_user(user_id)

    # Foydalanuvchi mavjud bo'lmasa yaratish
    if not user:
        user = get_or_create_user(user_id, message.from_user.first_name or "Do'st", message.from_user.username or "")

    # Daraja yo'q bo'lsa — faqat inline button bilan so'rash (guruhda keyboard chiqmasin)
    if not user.get("level"):
        await message.reply(
            "⚙️ Avval darajangizni tanlang:",
            reply_markup=level_kb()
        )
        return

    level     = user.get("level", "beginner")
    all_words = words.get(level, [])

    # Nechta guruh bor — hisoblash
    total_groups = (len(all_words) + 19) // 20  # har guruhda 20 ta

    if total_groups == 0:
        await message.reply("❌ So'zlar topilmadi.")
        return

    # Guruh tanlash inline klaviaturasi (3 ta ustunlik)
    rows = []
    row  = []
    for g in range(1, total_groups + 1):
        row.append(InlineKeyboardButton(
            text=f"📦 {g}-guruh",
            callback_data=f"poll_group_{g}"
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    level_label = {"beginner": "🟢 Boshlang'ich", "intermediate": "🟡 O'rta", "advanced": "🔴 Yuqori"}.get(level, level)
    await state.clear()
    await message.reply(
        f"🎯 <b>GURUH VIKTORINASI</b>\n\n"
        f"📚 Daraja: {level_label}\n"
        f"📦 Jami guruhlar: <b>{total_groups} ta</b>\n\n"
        f"Qaysi guruhdan o'ynaysiz?",
        reply_markup=kb
    )

@dp.message(Command("stopquiz"))
async def cmd_stopquiz(message: types.Message):
    """Viktorinani to'xtatish"""
    chat_id = message.chat.id
    qs = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or not qs.get("active"):
        await message.reply("❌ Hozir aktiv viktorina yo'q.")
        return

    user_id    = message.from_user.id
    starter_id = qs.get("starter_id")

    # Faqat testni boshlagan yoki admin to'xtatishi mumkin
    is_starter = (starter_id == user_id)
    is_admin   = False
    try:
        member   = await bot.get_chat_member(chat_id, user_id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        pass

    if not is_starter and not is_admin:
        starter_name = qs.get("starter_name", "boshqasi")
        await message.reply(
            f"❌ Faqat testni boshlagan <b>{starter_name}</b> yoki admin to'xtatishi mumkin."
        )
        return

    qs["active"] = False
    scores    = qs.get("scores", {})
    poll_num  = qs.get("poll_num", 0)
    group_num = qs.get("group_num", 1)

    if scores:
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        max_score     = sorted_scores[0][1] if sorted_scores else 0
        result_text   = f"⏹ <b>Viktorina to'xtatildi!</b>\n\n"
        result_text  += f"📊 {group_num}-guruh | {poll_num} savol o'tdi\n"
        result_text  += "━━━━━━━━━━━━━━━━━━\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, count) in enumerate(sorted_scores[:10]):
            medal      = medals[i] if i < 3 else f"{i+1}."
            winner_tag = " 🏆 G'OLIB!" if i == 0 and count == max_score else ""
            try:
                m    = await bot.get_chat_member(chat_id, int(uid))
                name = m.user.first_name or "User"
            except Exception:
                name = f"Ishtirokchi {i+1}"
            result_text += f"{medal} <b>{name}</b> — {count}/{poll_num} ✅{winner_tag}\n"
    else:
        result_text = "⏹ <b>Viktorina to'xtatildi.</b>\n\nHech kim qatnashmadi."

    await message.answer(result_text)
    GROUP_QUIZ_STATE.pop(chat_id, None)

@dp.callback_query(F.data.startswith("poll_group_"))
async def poll_group_selected(callback: types.CallbackQuery, state: FSMContext):
    user_id    = callback.from_user.id
    chat_id    = callback.message.chat.id
    in_group   = is_group(callback.message)
    user       = get_user(user_id)
    if not user:
        user = get_or_create_user(user_id, callback.from_user.first_name or "Do'st", callback.from_user.username or "")
    group_num  = int(callback.data.split("_")[2])
    level      = user.get("level", "beginner")
    all_words  = words.get(level, [])

    start_idx   = (group_num - 1) * 20
    group_words = all_words[start_idx:start_idx + 20]

    if len(group_words) < 4:
        await callback.answer("❌ Bu guruhda yetarli so'z yo'q!", show_alert=True)
        return

    total = min(20, len(group_words))

    GROUP_QUIZ_STATE[chat_id] = {
        "group_num":         group_num,
        "level":             level,
        "group_words":       [w["word"] for w in group_words],
        "poll_num":          0,
        "total":             total,
        "asked":             [],
        "scores":            {},
        "poll_answers":      {},
        "answered_polls":    {},
        "active":            False,
        "unanswered_streak": 0,
        "last_poll_id":      None,
        "starter_id":        user_id,
        "starter_name":      callback.from_user.first_name or "Obunachi",
        "ready_users":       {str(user_id): callback.from_user.first_name or "Obunachi"},
        "phase":             "lobby",
    }

    # Shaxsiy chatda — Ready kerak emas, to'g'ridan boshlash
    if not in_group:
        GROUP_QUIZ_STATE[chat_id]["phase"]  = "running"
        GROUP_QUIZ_STATE[chat_id]["active"] = True
        await callback.message.edit_text(
            f"🎯 <b>{group_num}-guruh viktorinasi boshlanmoqda!</b>\n\n"
            f"📊 Jami savollar: <b>{total}</b>\n"
            f"⏱ Har savol uchun <b>20 soniya</b>",
            reply_markup=None
        )
        await callback.answer()
        await _send_group_poll(chat_id)
        return

    # Guruhda — Ready tizimi
    ready_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tayyor!", callback_data=f"quiz_ready_{chat_id}")]
    ])
    await callback.message.edit_text(
        f"🎯 <b>{group_num}-guruh viktorinasi</b>\n\n"
        f"👥 Tayyor bo'lganlar: <b>1 kishi</b>\n"
        f"✅ {callback.from_user.first_name}\n\n"
        f"⏳ Kamida <b>2 kishi</b> tayyor bo'lishi kerak\n"
        f"⏱ <b>30 soniya</b> kutiladi\n\n"
        f"👇 Tayyor bo'lsangiz bosing:",
        reply_markup=ready_kb
    )
    await callback.answer()
    asyncio.create_task(_lobby_timeout(chat_id, callback.message.message_id))

async def _lobby_timeout(chat_id: int, message_id: int):
    """30 soniya kutib, tayyor bo'lganlar bilan boshlayman"""
    await asyncio.sleep(30)
    qs = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or qs.get("phase") != "lobby":
        return
    ready = qs.get("ready_users", {})
    if len(ready) < 2:
        # Yetarli odam yo'q — bekor qilish
        GROUP_QUIZ_STATE.pop(chat_id, None)
        try:
            await bot.send_message(
                chat_id,
                "❌ <b>Viktorina bekor qilindi</b>\n\n"
                "😔 Kamida 2 kishi tayyor bo'lishi kerak edi.\n"
                "/quiz — qayta urinib ko'ring!"
            )
        except Exception:
            pass
        return
    # Boshlanamiz
    qs["phase"]  = "running"
    qs["active"] = True
    names = ", ".join(list(ready.values())[:5])
    try:
        await bot.send_message(
            chat_id,
            f"🚀 <b>Viktorina boshlanmoqda!</b>\n\n"
            f"✅ Ishtirokchilar ({len(ready)} kishi): <b>{names}</b>\n"
            f"📊 Jami savollar: <b>{qs['total']}</b>\n"
            f"⏱ Har savol uchun <b>20 soniya</b>\n\n"
            f"🛑 To'xtatish: /stopquiz"
        )
    except Exception:
        pass
    await _send_group_poll(chat_id)

@dp.callback_query(F.data.startswith("quiz_ready_"))
async def quiz_ready_cb(callback: types.CallbackQuery):
    """Foydalanuvchi Ready bosdi"""
    chat_id = int(callback.data.split("_")[2])
    qs      = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or qs.get("phase") != "lobby":
        await callback.answer("⚠️ Lobby topilmadi yoki boshlandi.", show_alert=True)
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
            f"👥 Tayyor bo'lganlar: <b>{count} kishi</b>\n"
            f"{names}\n\n"
            f"⏳ <b>30 soniya</b> kutilmoqda...\n"
            f"👇 Siz ham tayyor bo'ling:",
            reply_markup=ready_kb
        )
    except Exception:
        pass
    await callback.answer(f"✅ Tayyor! ({count} kishi)")

async def _send_group_poll(chat_id: int):
    """Guruh pollini yuborish"""
    qs = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or not qs.get("active"):
        return

    poll_num          = qs["poll_num"]
    total             = qs["total"]
    level             = qs["level"]
    word_keys         = qs["group_words"]
    group_num         = qs["group_num"]
    unanswered_streak = qs.get("unanswered_streak", 0)

    # 5 ta ketma-ket javobsiz → to'xtatish
    if unanswered_streak >= 5:
        qs["active"] = False
        scores = qs.get("scores", {})
        txt = f"⏹ <b>Viktorina to'xtatildi!</b>\n\n😔 5 ta savolga ketma-ket hech kim javob bermadi.\n\n"
        if scores:
            txt += await _build_result_text(chat_id, qs, poll_num)
        else:
            txt += "Hech kim qatnashmadi.\n\n/quiz — yana boshlash"
        await bot.send_message(chat_id, txt)
        GROUP_QUIZ_STATE.pop(chat_id, None)
        return

    # Barcha savollar tugadi
    if poll_num >= total:
        await _finish_group_quiz(chat_id, qs)
        return

    all_words  = words.get(level, [])
    group_pool = [w for w in all_words if w["word"] in word_keys]

    asked     = qs.get("asked", [])
    remaining = [w for w in group_pool if w["word"] not in asked]
    if not remaining:
        remaining = group_pool

    correct      = random.choice(remaining)
    qs["asked"].append(correct["word"])

    wrong_pool   = [w for w in all_words if w["word"] != correct["word"]]
    wrong_sample = random.sample(wrong_pool, min(3, len(wrong_pool)))

    options     = [correct["translation"]] + [w["translation"] for w in wrong_sample]
    random.shuffle(options)
    correct_idx = options.index(correct["translation"])

    qs["poll_num"] += 1

    # Poll ID ni oldindan belgilaymiz (unique key sifatida)
    current_poll_num = qs["poll_num"]

    sent = await bot.send_poll(
        chat_id=chat_id,
        question=f"❓ {current_poll_num}/{total} — 🇬🇧 {correct['word'].upper()} tarjimasini toping!",
        options=options,
        type="quiz",
        correct_option_id=correct_idx,
        explanation=f"💡 {correct['example']}",
        is_anonymous=False,
        open_period=20
    )

    poll_id = sent.poll.id
    qs["poll_answers"][poll_id]   = correct_idx
    qs["answered_polls"][poll_id] = set()   # Bo'sh to'plam — hali javob yo'q
    qs["last_poll_id"]            = poll_id

    # 22 soniyadan keyin keyingi savol (20 sek poll + 2 sek pauza)
    asyncio.create_task(_delayed_next_poll(chat_id, poll_id, 22))

async def _delayed_next_poll(chat_id: int, poll_id: str, delay: int):
    """Kechikish bilan keyingi poll yuborish"""
    await asyncio.sleep(delay)
    qs = GROUP_QUIZ_STATE.get(chat_id)
    if not qs or not qs.get("active"):
        return
    # Faqat bu task o'z poll_id si uchun ishlashi kerak
    if qs.get("last_poll_id") != poll_id:
        return
    # Shu pollga javob berilganmi?
    answered = qs.get("answered_polls", {}).get(poll_id, set())
    if len(answered) == 0:
        qs["unanswered_streak"] = qs.get("unanswered_streak", 0) + 1
    else:
        qs["unanswered_streak"] = 0
    await _send_group_poll(chat_id)

async def _build_result_text(chat_id: int, qs: dict, shown_total: int) -> str:
    """Natija matnini yasash"""
    group_num     = qs["group_num"]
    scores        = qs.get("scores", {})
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    max_score     = sorted_scores[0][1] if sorted_scores else 0
    txt  = f"📊 <b>{group_num}-guruh — natijalar:</b>\n"
    txt += f"Jami savollar: <b>{shown_total}</b>\n"
    txt += "━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, count) in enumerate(sorted_scores[:10]):
        medal      = medals[i] if i < 3 else f"{i+1}."
        winner_tag = " 🏆 G'OLIB!" if i == 0 and count == max_score else ""
        try:
            member = await bot.get_chat_member(chat_id, int(uid))
            name   = member.user.first_name or "User"
        except Exception:
            name = f"Ishtirokchi {i+1}"
        txt += f"{medal} <b>{name}</b> — {count}/{shown_total} ✅{winner_tag}\n"
    txt += "\n🎉 Barcha ishtirokchilarga rahmat!\n/quiz — qayta boshlash"
    return txt

async def _finish_group_quiz(chat_id: int, qs: dict):
    """Viktorina tugadi — natija chiqarish"""
    group_num = qs["group_num"]
    total     = qs["total"]
    scores    = qs.get("scores", {})
    qs["active"] = False

    if scores:
        header = f"🏆 <b>{group_num}-guruh viktorinasi yakunlandi!</b>\n\n"
        result_text = header + await _build_result_text(chat_id, qs, total)
    else:
        result_text = (
            f"🏆 <b>{group_num}-guruh viktorinasi yakunlandi!</b>\n\n"
            f"😔 Hech kim qatnashmadi.\n"
            f"/quiz — yana urinib ko'ring!"
        )

    await bot.send_message(chat_id, result_text)
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

# ══════════════════════════════════════════════════
# DARAJA
# ══════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("level_"))
async def set_level(callback: types.CallbackQuery, state: FSMContext):
    level_map = {
        "beginner":     "🟢 Boshlang'ich",
        "intermediate": "🟡 O'rta daraja",
        "advanced":     "🔴 Yuqori daraja",
    }
    level   = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    update_user_level(user_id, level)
    await state.clear()
    await callback.answer(f"✅ {level_map.get(level, level)}")

    new_text = (
        f"✅ Daraja belgilandi: <b>{level_map.get(level, level)}</b>\n\n"
        f"🚀 Endi o'rganishni boshlashingiz mumkin!"
    )
    try:
        await callback.message.edit_text(new_text)
    except Exception:
        pass  # Xuddi shu matn bo'lsa Telegram xato beradi — e'tiborsiz qoldiramiz

    if not is_group(callback.message):
        await callback.message.answer(
            "📚 Quyidagi bo'limlardan birini tanlang:",
            reply_markup=main_kb(user_id)
        )
    else:
        # Guruhda daraja tanlanganidan keyin quiz menyusini ko'rsat
        all_words    = words.get(level, [])
        total_groups = (len(all_words) + 19) // 20
        rows = []
        row  = []
        for g in range(1, total_groups + 1):
            row.append(InlineKeyboardButton(
                text=f"📦 {g}-guruh",
                callback_data=f"poll_group_{g}"
            ))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        level_label = {"beginner": "🟢 Boshlang'ich", "intermediate": "🟡 O'rta", "advanced": "🔴 Yuqori"}.get(level, level)
        await callback.message.answer(
            f"🎯 <b>GURUH VIKTORINASI</b>\n\n"
            f"📚 Daraja: {level_label}\n"
            f"📦 Jami guruhlar: <b>{total_groups} ta</b>\n\n"
            f"Qaysi guruhdan o'ynaysiz?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )

@dp.message(F.text == "⚙️ Daraja")
async def change_level(message: types.Message):
    await message.answer(
        "⚙️ <b>DARAJA BO'LIMI</b>\n\n━━━━━━━━━━━━━━━\n📈 <i>Darajangizni tanlang:</i>",
        reply_markup=level_kb()
    )

# ══════════════════════════════════════════════════
# SO'Z O'RGANISH — TO'LIQ TUZATILGAN
# ══════════════════════════════════════════════════
@dp.message(F.text == "📚 So’z o‘rgan")
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
                [InlineKeyboardButton(text=f"🧠 {group_num}-guruh testini topshirish", callback_data=f"group_quiz_{group_num}")],
                [InlineKeyboardButton(text="🔄 So'zlarni takrorlash",   callback_data="review_words")],
                [InlineKeyboardButton(text="🏠 Bosh menyu",             callback_data="back_menu")],
            ])
            txt = (
                f"🎯 <b>{group_num}-guruh tugadi!</b>\n\n"
                f"✅ 20 ta so'zni o'rgandingiz\n"
                f"💎 VIP sifatida testisiz keyingi guruhga o'tishingiz mumkin!\n\n"
                f"Yoki testni topshirib ball to'plang! 🚀"
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
        group_words=[w["word"] for w in test_pool],
        asked_words=[]
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
    asked_words     = data.get("asked_words", [])

    all_words  = words.get(level, [])
    group_pool = [w for w in all_words if w["word"] in group_word_keys]

    if len(group_pool) < 4:
        extra = [w for w in all_words if w["word"] not in group_word_keys]
        group_pool += extra

    # Takrorlanmaslik: so'ralgan so'zlar olib tashlanadi
    remaining_pool = [w for w in group_pool if w["word"] not in asked_words]
    if len(remaining_pool) < 1:
        remaining_pool = group_pool

    correct = random.choice(remaining_pool)
    asked_words.append(correct["word"])
    await state.update_data(asked_words=asked_words)

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
        add_score(user_id, TEST_SCORE_BONUS)
        await callback.answer(f"✅ To'g'ri! +{TEST_SCORE_BONUS} ball 🎉")
        await _check_score_prize(user_id)
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
@dp.callback_query(F.data == "retake_learned_test")
async def retake_learned_test_cb(callback: types.CallbackQuery, state: FSMContext):
    """So'z o'rganish bo'limidan qayta test"""
    user_id = callback.from_user.id
    user    = get_user(user_id)
    learned = user.get("learned_words") or []
    if len(learned) < 4:
        await callback.answer("⚠️ Kamida 4 ta so'z o'rganing!", show_alert=True)
        return
    level = user.get("level", "beginner")
    await state.set_state(QuizState.answering)
    await state.update_data(
        q_num=1, total=min(10, len(learned)), correct_count=0,
        level=level,
        group_quiz=False,
        use_learned=True,
        learned_words=learned,
        asked_words=[]
    )
    await callback.answer()
    await _send_free_quiz(callback.message, user_id, state, edit=True)

# ══════════════════════════════════════════════════
# TEST BO'LIMI — GURUH TANLASH MENYUSI
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
    await _show_test_menu(message, message.from_user.id, edit=False)

async def _show_test_menu(target, user_id: int, edit: bool = False):
    """Test menyusi — guruh tanlash"""
    user    = get_user(user_id)
    level   = user.get("level", "beginner")
    learned = user.get("learned_words") or []
    all_words = words.get(level, [])

    # Qaysi guruhlardan so'z o'rganilgan — aniqlash
    learned_set = set(learned)
    unlocked_groups = []
    group_num = 1
    while True:
        start_idx   = (group_num - 1) * 20
        group_words = all_words[start_idx:start_idx + 20]
        if not group_words:
            break
        done_in_group = [w for w in group_words if w["word"] in learned_set]
        if len(done_in_group) >= 4:
            unlocked_groups.append((group_num, len(done_in_group)))
        group_num += 1

    rows = []
    for gnum, count in unlocked_groups:
        rows.append([InlineKeyboardButton(
            text=f"📦 {gnum}-guruh  ({count} ta so'z)",
            callback_data=f"test_group_{gnum}"
        )])
    # Barcha o'rganilgan so'zlardan test
    rows.append([InlineKeyboardButton(
        text=f"🌐 Barcha o'rganilgan so'zlar ({len(learned)} ta)",
        callback_data="test_all_learned"
    )])
    rows.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    txt = (
        "🧠 <b>TEST BO'LIMI</b>\n\n━━━━━━━━━━━━━━━\n"
        "📌 Qaysi guruhdan test ishlaysiz?\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📚 O'rganilgan so'zlar: <b>{len(learned)} ta</b>\n"
        f"📦 Ochilgan guruhlar: <b>{len(unlocked_groups)} ta</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👇 Guruhni tanlang:"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data.startswith("test_group_"))
async def test_group_select_cb(callback: types.CallbackQuery, state: FSMContext):
    """Muayyan guruhdan test boshlash (Test menyusidan)"""
    user_id   = callback.from_user.id
    user      = get_user(user_id)
    group_num = int(callback.data.split("_")[2])
    level     = user.get("level", "beginner")

    all_words   = words.get(level, [])
    start_idx   = (group_num - 1) * 20
    group_words = all_words[start_idx:start_idx + 20]
    learned     = user.get("learned_words") or []
    test_pool   = [w for w in group_words if w["word"] in learned]

    if len(test_pool) < 4:
        await callback.answer("⚠️ Bu guruhdan kamida 4 ta so'z o'rganing!", show_alert=True)
        return

    total = min(10, len(test_pool))
    await state.set_state(QuizState.answering)
    await state.update_data(
        q_num=1, total=total, correct_count=0,
        level=level,
        group_quiz=True,
        group_num=group_num,
        group_words=[w["word"] for w in test_pool],
        asked_words=[]
    )
    await callback.answer()
    await _send_group_quiz(callback.message, user_id, state, edit=True)

@dp.callback_query(F.data == "test_all_learned")
async def test_all_learned_cb(callback: types.CallbackQuery, state: FSMContext):
    """Barcha o'rganilgan so'zlardan test"""
    user_id = callback.from_user.id
    user    = get_user(user_id)
    learned = user.get("learned_words") or []
    level   = user.get("level", "beginner")

    if len(learned) < 4:
        await callback.answer("⚠️ Kamida 4 ta so'z o'rganing!", show_alert=True)
        return

    total = min(10, len(learned))
    await state.set_state(QuizState.answering)
    await state.update_data(
        q_num=1, total=total, correct_count=0,
        level=level,
        group_quiz=False,
        use_learned=True,
        learned_words=learned,
        asked_words=[]
    )
    await callback.answer()
    await _send_free_quiz(callback.message, user_id, state, edit=True)

@dp.callback_query(F.data == "quiz_start")
async def quiz_start_cb(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user    = get_user(user_id)
    if not user or not user.get("level"):
        await callback.message.answer("⚙️ Avval darajangizni tanlang:", reply_markup=level_kb())
        return
    learned = user.get("learned_words") or []
    if len(learned) < 4:
        await callback.message.answer(
            "⚠️ Kamida 4 ta so'z o'rganing!\n📚 So'z o'rgan bo'limiga o'ting."
        )
        return
    await callback.answer()
    await _show_test_menu(callback.message, user_id, edit=True)

async def _send_free_quiz(target, user_id: int, state: FSMContext, edit: bool = False):
    data          = await state.get_data()
    q_num         = data.get("q_num", 1)
    total         = data.get("total", 10)
    correct_count = data.get("correct_count", 0)
    level         = data.get("level", "beginner")
    learned_keys  = data.get("learned_words", [])
    asked_words   = data.get("asked_words", [])

    all_words    = words.get(level, words.get("beginner", []))
    learned_pool = [w for w in all_words if w["word"] in learned_keys]

    if len(learned_pool) < 4:
        learned_pool = all_words

    # Takrorlanmaslik: so'ralgan so'zlar olib tashlanadi
    remaining_pool = [w for w in learned_pool if w["word"] not in asked_words]
    if len(remaining_pool) < 1:
        # Hammalari so'ralgan — qaytadan boshlash
        remaining_pool = learned_pool

    correct      = random.choice(remaining_pool)
    asked_words.append(correct["word"])
    await state.update_data(asked_words=asked_words)

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
        add_score(user_id, TEST_SCORE_BONUS)
        await callback.answer(f"✅ To'g'ri! +{TEST_SCORE_BONUS} ball 🎉")
        await _check_score_prize(user_id)
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

@dp.message(F.text == "☰ Boshqalar")
async def more_menu(message: types.Message):
    await message.answer("☰ Boshqa bo‘limlar:", reply_markup=more_kb())

@dp.message(F.text == "🏠 Orqaga")
async def back_to_main(message: types.Message):
    await message.answer("🏠 Asosiy menyu:", reply_markup=main_kb(message.from_user.id, message.chat))

@dp.message(F.text == "🔥 Streak")
async def more_streak_msg(message: types.Message):
    uid  = message.from_user.id
    user = get_user(uid)
    if not user:
        await message.answer("Avval /start bosing")
        return
    streak = user.get("streak", 0)
    best   = user.get("best_streak", 0)
    await message.answer(
        f"🔥 <b>STREAK</b>\n\n"
        f"📅 Hozirgi streak: <b>{streak} kun</b>\n"
        f"🏆 Eng yuqori: <b>{best} kun</b>"
    )

@dp.callback_query(F.data == "more_streak")
async def more_streak_cb(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    user = get_user(uid)
    if not user:
        await callback.answer("Avval /start bosing", show_alert=True)
        return
    streak = user.get("streak", 0)
    best   = user.get("best_streak", 0)
    await callback.message.answer(
        f"🔥 <b>STREAK</b>\n\n"
        f"📅 Hozirgi streak: <b>{streak} kun</b>\n"
        f"🏆 Eng yuqori: <b>{best} kun</b>"
    )
    await callback.answer()

@dp.callback_query(F.data == "more_create_test")
async def more_create_test_cb(callback: types.CallbackQuery, state: FSMContext):
    user_id  = callback.from_user.id
    my_tests = USER_TESTS.get(user_id, [])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi test yaratish", callback_data="create_test_start")],
        *([[InlineKeyboardButton(text=f"▶️ Mening testim ({len(my_tests)} savol)", callback_data="run_my_test")]] if my_tests else []),
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")],
    ])
    await callback.message.answer(
        "📝 <b>TEST YARATISH</b>\n\n"
        "O‘z testingizni yarating va ishlang!\n\n"
        f"• Sizda: <b>{len(my_tests)} ta savol</b>\n"
        "• Savol, 4 ta variant va to‘g‘ri javob kiriting",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data == "more_guide")
async def more_guide_cb(callback: types.CallbackQuery):
    await guide_menu(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "more_feedback")
async def more_feedback_cb(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(FeedbackState.waiting)
    await callback.message.answer(
        "💬 <b>TAKLIF & FIKR</b>\n\n━━━━━━━━━━━━━━━\n"
        "🙏 <i>Botni yaxshilashga yordam bering!</i>\n\n"
        "📌 Quyidagilar haqida yozishingiz mumkin:\n"
        "  🔴 Muammo yoki xato haqida\n"
        "  🟡 Yangi funksiya taklifi\n"
        "  🟢 Umumiy fikr\n\n"
        "✍️ <b>Xabaringizni yozing:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_menu")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "more_level")
async def more_level_cb(callback: types.CallbackQuery):
    await callback.message.answer(
        "⚙️ <b>DARAJA BO'LIMI</b>\n\n━━━━━━━━━━━━━━━\n📈 <i>Darajangizni tanlang:</i>",
        reply_markup=level_kb()
    )
    await callback.answer()

async def more_referral_msg(message: types.Message):
    await show_referral(message)

@dp.message(F.text == "💬 Taklif & Fikr")
async def more_feedback_msg(message: types.Message, state: FSMContext):
    await feedback_menu(message, state)

@dp.message(F.text == "📝 Test yaratish")
async def more_test_msg(message: types.Message):
    await user_test_menu(message)

@dp.callback_query(F.data == "more_referral")
async def more_referral_cb(callback: types.CallbackQuery):
    await show_referral(callback.message)
    await callback.answer()


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
            text=t['name'],
            callback_data=f"gram_{t['id']}"
        )]
        for t in GRAMMAR_TOPICS
    ] + [[InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")]])

    txt = (
        "📖 <b>GRAMMATIKA BO'LIMI</b>\n\n━━━━━━━━━━━━━━━\n🎯 <i>Ingliz tili zamonlarini o'rganing!</i>\n\n"
        "📌 <b>Har bir mavzuda:</b>\n"
        "  ✅ Batafsil tushuntirish\n"
        "  ✅ Misollar bilan\n"
        "  ✅ 5 ta test savoli\n\n"
        "👇 <b>Mavzuni tanlang:</b>"
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
        await _check_score_prize(user_id)
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

    prize_pct  = min(100, int(score / 10_000 * 100))
    prize_bar  = "🟨" * (prize_pct // 10) + "⬜" * (10 - prize_pct // 10)
    prize_left = max(0, 10_000 - score)
    prize_line = f"✅ {PRIZE_BALL_TARGET:,} ball — sovrin yutdingiz!" if score >= 10_000 else f"⭐️ Yana {prize_left:,} ball — {PRIZE_SCORE_AMOUNT:,} so'm sovrin yuting!"

    await message.answer(
        f"🔥 <b>STREAK BO'LIMI</b>\n\n━━━━━━━━━━━━━━━\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{bar}\n"
        f"🗓 Ketma-ketlik: <b>{streak} kun</b>  {badge}\n"
        f"💬 {msg}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⭐️ Jami ball: <b>{score}</b>\n\n"
        f"<b>🏆 SOVRIN MAQSAD:</b>\n"
        f"{prize_bar} {prize_pct}%\n"
        f"{prize_line}\n\n"
        f"<b>🎯 STREAK MAQSADLAR:</b>\n"
        f"{'✅' if streak>=3  else '🔲'} 3 kun  — ⚡️ Ishga tushding!\n"
        f"{'✅' if streak>=7  else '🔲'} 7 kun  — 💪 Yaxshi!\n"
        f"{'✅' if streak>=14 else '🔲'} 14 kun — 🔥 Ajoyib!\n"
        f"{'✅' if streak>=30 else '🔲'} 30 kun — 🏆 Ustoz!\n\n"
        f"<i>Har kun kiring va streak'ingizni saqlang! 🚀</i>"
    )

# ══════════════════════════════════════════════════
# REYTING
# ══════════════════════════════════════════════════
@dp.message(F.text == "💰 Pul yutug'i")
async def prize_menu(message: types.Message):
    user_id   = message.from_user.id
    user      = get_user(user_id)
    if not user:
        await message.answer("❌ Avval /start bosing.")
        return
    score     = user.get("score", 0)
    ref_count = user.get("referral_count", 0)
    remaining = max(0, PRIZE_BALL_TARGET - score)
    bar       = ref_progress_bar(score, PRIZE_BALL_TARGET)

    if score >= PRIZE_BALL_TARGET and ref_count >= PRIZE_MIN_REFERRAL:
        status = "🏆 <b>Tabriklaymiz! Siz g'olib bo'ldingiz!</b>\nAdmin siz bilan bog'lanadi."
    elif score >= PRIZE_BALL_TARGET and ref_count < PRIZE_MIN_REFERRAL:
        status = (
            f"⚠️ Ballar yetarli! Lekin pul yechish uchun\n"
            f"kamida <b>{PRIZE_MIN_REFERRAL} ta do'st</b> taklif qiling!\n"
            f"Hozir: <b>{ref_count} ta</b> referal"
        )
    else:
        status = f"⏳ Yutuqqacha: <b>{remaining:,} ball</b> qoldi"

    text = (
        "💰 <b>PUL YUTUG'I</b>\n\n"
        "═══════════════\n"
        "🏆 <b>DIQQAT, TANLOV!</b>\n\n"
        "Kim birinchi bo'lib <b>5,000 ball</b> yig'sa,\n"
        "unga <b>10,000 so'm</b> haqiqiy pul mukofoti beramiz!\n\n"
        "📊 <b>Sizning natijangiz:</b>\n"
        f"{bar}\n\n"
        f"🔹 Sizning balingiz: <b>{score:,}</b>\n"
        f"🔹 Yutuqqacha qoldi: <b>{remaining:,} ball</b>\n\n"
        f"{status}\n\n"
        "═══════════════\n"
        "📌 <b>Shartlar:</b>\n"
        "  ✅ <b>5,000 ball</b> yig'ing\n"
        "  ✅ Kamida <b>1 ta do'st</b> taklif qiling\n"
        "  💰 Sovrin: <b>10,000 so'm</b>\n\n"
        "💡 <b>Ball yig'ish yo'llari:</b>\n"
        "  📚 So'z o'rganish: <b>+2 ball</b>\n"
        "  🧠 To'g'ri test javobi: <b>+10 ball</b>\n"
        "  👥 Referal (do'st taklif): <b>+200 ball</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Do'st taklif qilish", callback_data="more_referral")],
        [InlineKeyboardButton(text="🧠 Test yechish",         callback_data="go_test")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",          callback_data="back_menu")],
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "go_test")
async def go_test_cb(callback: types.CallbackQuery):
    await user_test_menu(callback.message)
    await callback.answer()

@dp.message(F.text == "🏆 Reyting")
async def show_rating(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Ball reytingi",   callback_data="rank_score"),
         InlineKeyboardButton(text="👥 Referal reytingi", callback_data="rank_ref")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",       callback_data="back_menu")],
    ])
    await message.answer(
        "📊 <b>REYTING BO'LIMI</b>\n\n━━━━━━━━━━━━━━━\n🏅 Qaysi ro'yxatni ko'rmoqchisiz?",
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
@dp.message(F.text == "👥 Referal")
async def referal_menu(message: types.Message):
    user_id   = message.from_user.id
    user      = get_user(user_id)
    if not user:
        await message.answer("❌ Avval /start bosing.")
        return
    bot_info  = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_count = user.get("referral_count", 0)
    needed_vip    = max(0, 3 - ref_count)
    needed_weekly = max(0, MIN_REFERRALS_FOR_BONUS - ref_count)
    vip_bar    = ref_progress_bar(ref_count, 3)
    weekly_bar = ref_progress_bar(ref_count, MIN_REFERRALS_FOR_BONUS)
    if ref_count >= 3:
        vip_status = "✅ <b>VIP faollashtirildi!</b> (1 oy)"
    elif needed_vip == 1:
        vip_status = "🔥 Yana <b>1 ta</b> qoldi — VIP yaqin!"
    else:
        vip_status = f"⏳ VIP uchun yana <b>{needed_vip} ta</b> doʿst kerak"
    winner_line = "🏆 Gʿolib boʿlishingiz mumkin!" if ref_count >= MIN_REFERRALS_FOR_BONUS else f"📌 Gʿolib uchun yana {needed_weekly} ta kerak"
    share_text = f"🎁 Bu botda ingliz tilini o‘rganmoqdaman! Sen ham ko‘r: {ref_link}"
    await message.answer(
        f"🎁 <b>Shoshiling! Sizga sovgʿa bor!</b>\n\n"
        f"Sizga VIP status berilishi uchun atigi <b>3 ta doʿstingiz</b> botga kirishi kifoya.\n\n"
        f"📊 <b>VIP progress:</b>\n{vip_bar}\n"
        f"{vip_status}\n\n"
        f"━━━━━━━━━━\n"
        f"🏆 <b>HAFTALIK TANLOV:</b>\n"
        f"📊 Progress: {weekly_bar}\n"
        f"{winner_line}\n"
        f"• Har juma 18:00 da hisoblanadi\n"
        f"• Kamida <b>{MIN_REFERRALS_FOR_BONUS} ta</b> taklif shart\n"
        f"• Gʿolibga <b>💰 10 000 soʿm</b>!\n\n"
        f"⏳ <b>Diqqat:</b> VIP aksiya faqat <b>24 soat</b> amal qiladi!\n\n"
        f"🔗 Sizning havolangiz:\n<code>{ref_link}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🚀 Doʿstlarimga ulashish",
                switch_inline_query=share_text
            )
        ]])
    )

# ══════════════════════════════════════════════════
# QO'LLANMA
# ══════════════════════════════════════════════════
@dp.message(F.text == "📋 Qo‘llanma")
async def guide_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 So'z o'rgan",    callback_data="guide_learn")],
        [InlineKeyboardButton(text="🧠 Test",           callback_data="guide_test")],
        [InlineKeyboardButton(text="📖 Grammatika",     callback_data="guide_grammar")],
        [InlineKeyboardButton(text="🔥 Streak",         callback_data="guide_streak")],
        [InlineKeyboardButton(text="🏆 Reyting & Ball", callback_data="guide_rating")],
        [InlineKeyboardButton(text="👥 Referal",        callback_data="guide_referal")],
        [InlineKeyboardButton(text="💎 VIP",            callback_data="guide_vip")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",     callback_data="back_menu")],
    ])
    await message.answer(
        "📋 <b>QO'LLANMA</b>\n\n"
        "Qaysi bo'lim haqida bilmoqchisiz?",
        reply_markup=kb
    )

@dp.callback_query(F.data == "guide_back")
async def guide_back_cb(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 So'z o'rgan",    callback_data="guide_learn")],
        [InlineKeyboardButton(text="🧠 Test",           callback_data="guide_test")],
        [InlineKeyboardButton(text="📖 Grammatika",     callback_data="guide_grammar")],
        [InlineKeyboardButton(text="🔥 Streak",         callback_data="guide_streak")],
        [InlineKeyboardButton(text="🏆 Reyting & Ball", callback_data="guide_rating")],
        [InlineKeyboardButton(text="👥 Referal",        callback_data="guide_referal")],
        [InlineKeyboardButton(text="💎 VIP",            callback_data="guide_vip")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",     callback_data="back_menu")],
    ])
    await callback.message.edit_text(
        "📋 <b>QO'LLANMA</b>\n\n━━━━━━━━━━━━━━━\n💡 <i>Qaysi bo'lim haqida bilmoqchisiz?</i>",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("guide_"))
async def guide_section(callback: types.CallbackQuery):
    section = callback.data.split("_", 1)[1]
    texts = {
        "learn": (
            "📚 <b>SO'Z O'RGANISH BO'LIMI</b>\n\n"
            "Bu bo'limda ingliz so'zlarini guruh-guruh o'rganasiz.\n\n"
            "<b>Qanday ishlaydi?</b>\n"
            "• Har guruhda <b>20 ta so'z</b> bor\n"
            "• Har so'zda tarjima, transkripsiya va misol gap ko'rsatiladi\n"
            "• ➡️ Keyingi so'z — oldinga o'tish\n"
            "• 🧠 Test — shu guruhni sinash\n"
            "• 20 ta so'z tugagach test topshirib keyingi guruhga o'tasiz\n\n"
            "<b>Ball tizimi:</b>\n"
            "• Har o'rganilgan so'z uchun <b>+5 ball</b>\n"
            "• <b>10 000 ball</b> to'plab sovrin yuting! 🏆"
        ),
        "test": (
            "🧠 <b>TEST BO'LIMI</b>\n\n━━━━━━━━━━━━━━━\n"
            "O'rganilgan so'zlardan test ishlaysiz.\n\n"
            "<b>Qanday ishlaydi?</b>\n"
            "• Guruh tanlaysiz yoki barcha so'zlardan ishlaysiz\n"
            "• 4 ta variantdan to'g'risini topasiz\n"
            "• Har to'g'ri javob uchun <b>+8 ball</b>\n"
            "• 10 ta savol — natija ko'rsatiladi\n\n"
            "<b>Qayta test:</b>\n"
            "• So'z kartasida 🔄 Qayta test tugmasi mavjud\n"
            "• Test yaratish bo'limida o'z testingizni yaratasiz"
        ),
        "grammar": (
            "📖 <b>GRAMMATIKA BO'LIMI</b>\n\n"
            "Ingliz tili grammatika qoidalarini o'rganasiz.\n\n"
            "<b>Mavzular:</b>\n"
            "• Present/Past/Future Simple\n"
            "• Present/Past Continuous\n"
            "• Present Perfect\n\n"
            "<b>Har mavzuda:</b>\n"
            "• Batafsil tushuntirish\n"
            "• Misollar\n"
            "• 5 savollik test\n"
            "• Har to'g'ri javob <b>+8 ball</b>"
        ),
        "streak": (
            "🔥 <b>STREAK TIZIMI</b>\n\n"
            "Har kuni botga kirib streak'ingizni oshiring!\n\n"
            "<b>Nishonlar:</b>\n"
            "• 3 kun  — ⚡️ Ishga tushding!\n"
            "• 7 kun  — 💪 Yaxshi!\n"
            "• 14 kun — 🔥 Ajoyib!\n"
            "• 30 kun — 🏆 Ustoz!\n\n"
            "Bir kun o'tkazib yuborsangiz streak nolga tushadi.\n"
            "Har kuni kiring! 🚀"
        ),
        "rating": (
            "🏆 <b>REYTING & BALL TIZIMI</b>\n\n"
            "<b>Ball qanday to'planadi?</b>\n"
            "• So'z o'rganish: <b>+5 ball</b>\n"
            "• To'g'ri test javobi: <b>+8 ball</b>\n"
            "• Grammatika to'g'ri javobi: <b>+8 ball</b>\n\n"
            f"<b>🏆 KATTA SOVRIN:</b>\n"
            f"• <b>{PRIZE_BALL_TARGET:,} ball</b> to'playdi → <b>{PRIZE_SCORE_AMOUNT:,} so'm</b> yutadi!\n\n"
            "<b>Haftalik referal sovrin:</b>\n"
            f"• Haftalik eng ko'p taklif → <b>{PRIZE_REF_AMOUNT:,} so'm</b>"
        ),
        "referal": (
            "👥 <b>REFERAL TIZIMI</b>\n\n"
            "Do'stlaringizni taklif qilib ball va sovrin yuting!\n\n"
            "<b>Qanday ishlaydi?</b>\n"
            "• 👥 Referal bo'limidan havolangizni oling\n"
            "• Do'stlaringizga yuboring\n"
            "• Ular botga kirsa sizga <b>+50 ball</b>\n\n"
            "<b>Haftalik sovrin:</b>\n"
            f"• Kamida <b>5 taklif</b> + eng ko'p taklif\n"
            f"• G'olibga <b>{PRIZE_REF_AMOUNT:,} so'm</b>!\n"
            "• Har juma soat 18:00 da hisoblanadi"
        ),
        "vip": (
            "💎 <b>VIP PREMIUM</b>\n\n"
            "<b>VIP imkoniyatlari:</b>\n"
            "• ✅ Testisiz keyingi guruhga o'tish\n"
            "• ✅ Barcha so'z guruhlari ochiq\n"
            "• ✅ Haftalik bonus ball\n"
            "• ✅ VIP nishon profilda\n\n"
            f"Narxi: <b>{VIP_PRICE:,} so'm / oy</b>\n\n"
            "💎 VIP Sotib olish tugmasini bosing!"
        ),
    }
    txt = texts.get(section, "❓ Bo'lim topilmadi.")
    kb  = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Qo'llanmaga qaytish", callback_data="guide_back")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",          callback_data="back_menu")],
    ])
    try:
        await callback.message.edit_text(txt, reply_markup=kb)
    except Exception:
        await callback.message.answer(txt, reply_markup=kb)
    await callback.answer()


# ══════════════════════════════════════════════════
# TAKLIF VA FIKR
# ══════════════════════════════════════════════════
@dp.message(F.text == "💬 Taklif & Fikr")
async def feedback_menu(message: types.Message, state: FSMContext):
    await state.set_state(FeedbackState.waiting)
    await message.answer(
        "💬 <b>TAKLIF & FIKR</b>\n\n━━━━━━━━━━━━━━━\n"
        "🙏 <i>Botni yaxshilashga yordam bering!</i>\n\n"
        "📌 Quyidagilar haqida yozishingiz mumkin:\n"
        "  🔴 Muammo yoki xato haqida\n"
        "  🟡 Yangi funksiya taklifi\n"
        "  🟢 Umumiy fikr\n\n"
        "✍️ <b>Xabaringizni yozing:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_menu")]
        ])
    )

@dp.message(FeedbackState.waiting)
async def feedback_receive(message: types.Message, state: FSMContext):
    user_id   = message.from_user.id
    user_name = message.from_user.first_name or "Noma'lum"
    username  = f"@{message.from_user.username}" if message.from_user.username else "username yo'q"
    text      = message.text or "[media]"

    await state.clear()

    # Adminga yuborish
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💬 <b>YANGI TAKLIF/FIKR</b>\n\n"
                f"👤 Foydalanuvchi: <b>{user_name}</b> ({username})\n"
                f"🆔 ID: <code>{user_id}</code>\n\n"
                f"📝 <b>Xabar:</b>\n{text}"
            )
        except Exception:
            pass

    await message.answer(
        "✅ <b>Fikringiz qabul qilindi!</b>\n\n"
        "Rahmat! Adminlar tez orada ko'rib chiqadi. 🙏",
        reply_markup=main_kb(user_id)
    )

# ══════════════════════════════════════════════════
# TEST YARATISH
# ══════════════════════════════════════════════════
USER_TESTS: dict = {}  # { user_id: [{"q": ..., "options": [...], "answer": ...}] }

@dp.message(F.text == "📝 Test yaratish")
async def user_test_menu(message: types.Message):
    user_id = message.from_user.id
    my_tests = USER_TESTS.get(user_id, [])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi test yaratish", callback_data="create_test_start")],
        *([[InlineKeyboardButton(text=f"▶️ Mening testim ({len(my_tests)} savol)", callback_data="run_my_test")]] if my_tests else []),
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="back_menu")],
    ])
    await message.answer(
        "📝 <b>TEST YARATISH</b>\n\n━━━━━━━━━━━━━━━\n"
        "✏️ <i>O'z testingizni yarating va ishlang!</i>\n\n"
        f"📌 Sizda: <b>{len(my_tests)} ta savol</b>\n"
        "📋 Savol, 4 ta variant va to'g'ri javob kiriting",
        reply_markup=kb
    )

@dp.callback_query(F.data == "create_test_start")
async def create_test_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserTestState.waiting_question)
    await state.update_data(new_q={}, user_tests=[])
    await callback.message.edit_text(
        "📝 <b>YANGI SAVOL</b>\n\n"
        "Savolni yozing:\n\n"
        "<i>Misol: What is the translation of 'apple'?</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="back_menu")]
        ])
    )
    await callback.answer()

@dp.message(UserTestState.waiting_question)
async def create_test_question(message: types.Message, state: FSMContext):
    await state.update_data(new_q={"q": message.text})
    await state.set_state(UserTestState.waiting_options)
    await message.answer(
        "✅ Savol qabul qilindi!\n\n"
        "Endi <b>4 ta variantni</b> vergul bilan yozing:\n\n"
        "<i>Misol: olma, nok, uzum, shaftoli</i>"
    )

@dp.message(UserTestState.waiting_options)
async def create_test_options(message: types.Message, state: FSMContext):
    opts = [o.strip() for o in message.text.split(",")]
    if len(opts) < 2:
        await message.answer("❌ Kamida 2 ta variant kiriting, vergul bilan ajrating.")
        return
    if len(opts) > 4:
        opts = opts[:4]
    while len(opts) < 4:
        opts.append(f"Variant {len(opts)+1}")
    data = await state.get_data()
    data["new_q"]["options"] = opts
    await state.update_data(new_q=data["new_q"])
    await state.set_state(UserTestState.waiting_answer)
    opts_text = "\n".join([f"{i+1}. {o}" for i, o in enumerate(opts)])
    await message.answer(
        f"Variantlar:\n{opts_text}\n\n"
        "To'g'ri javobni yozing (aynan yuqoridagi kabi):"
    )

@dp.message(UserTestState.waiting_answer)
async def create_test_answer(message: types.Message, state: FSMContext):
    data    = await state.get_data()
    new_q   = data.get("new_q", {})
    answer  = message.text.strip()
    options = new_q.get("options", [])
    if answer not in options:
        opts_text = ", ".join(options)
        await message.answer(f"❌ To'g'ri javob variantlar ichida bo'lishi kerak!\nVariantlar: {opts_text}")
        return

    new_q["answer"] = answer
    user_id = message.from_user.id
    if user_id not in USER_TESTS:
        USER_TESTS[user_id] = []
    USER_TESTS[user_id].append(new_q)
    total = len(USER_TESTS[user_id])
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana savol qo'shish", callback_data="create_test_start")],
        [InlineKeyboardButton(text="▶️ Testni boshlash",     callback_data="run_my_test")],
        [InlineKeyboardButton(text="🏠 Bosh menyu",          callback_data="back_menu")],
    ])
    await message.answer(
        f"✅ <b>Savol qo'shildi!</b>\n\n"
        f"Jami savollar: <b>{total} ta</b>",
        reply_markup=kb
    )

@dp.callback_query(F.data == "run_my_test")
async def run_my_test(callback: types.CallbackQuery, state: FSMContext):
    user_id  = callback.from_user.id
    my_tests = USER_TESTS.get(user_id, [])
    if not my_tests:
        await callback.answer("❌ Avval savol yarating!", show_alert=True)
        return
    shuffled = random.sample(my_tests, len(my_tests))
    await state.set_state(UserTestState.confirm)
    await state.update_data(ut_questions=shuffled, ut_idx=0, ut_correct=0)
    await _send_user_test_q(callback.message, state, edit=True)
    await callback.answer()

async def _send_user_test_q(target, state: FSMContext, edit=False):
    data       = await state.get_data()
    questions  = data.get("ut_questions", [])
    idx        = data.get("ut_idx", 0)
    correct    = data.get("ut_correct", 0)
    total      = len(questions)
    if idx >= total:
        pct = int(correct / total * 100)
        result = "🎉 Zo'r!" if pct >= 80 else "💪 Davom eting!"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Qayta ishlash",   callback_data="run_my_test")],
            [InlineKeyboardButton(text="➕ Savol qo'shish",  callback_data="create_test_start")],
            [InlineKeyboardButton(text="🏠 Bosh menyu",      callback_data="back_menu")],
        ])
        txt = (
            f"🏁 <b>Test yakunlandi!</b>\n\n"
            f"✅ To'g'ri: <b>{correct}/{total}</b>\n"
            f"📊 Natija: <b>{pct}%</b>\n\n"
            f"{result}"
        )
        if edit:
            await target.edit_text(txt, reply_markup=kb)
        else:
            await target.answer(txt, reply_markup=kb)
        await state.clear()
        return

    q       = questions[idx]
    options = q["options"][:]
    random.shuffle(options)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt, callback_data=f"utest_{opt}_{q['answer']}")] for opt in options
    ] + [[InlineKeyboardButton(text="❌ To'xtatish", callback_data="back_menu")]])
    progress = f"{'🟩'*correct}{'⬜'*(total-correct)}"
    txt = (
        f"📝 <b>MENING TESTIM</b>  {idx+1}/{total}\n"
        f"{progress}\n\n"
        f"❓ {q['q']}"
    )
    if edit:
        await target.edit_text(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)

@dp.callback_query(F.data.startswith("utest_"), UserTestState.confirm)
async def user_test_answer(callback: types.CallbackQuery, state: FSMContext):
    _, chosen, correct = callback.data.split("_", 2)
    data = await state.get_data()
    idx     = data.get("ut_idx", 0)
    correct_count = data.get("ut_correct", 0)
    if chosen == correct:
        correct_count += 1
        await callback.answer("✅ To'g'ri!")
    else:
        await callback.answer(f"❌ Noto'g'ri! To'g'risi: {correct}", show_alert=True)
    await state.update_data(ut_idx=idx+1, ut_correct=correct_count)
    await _send_user_test_q(callback.message, state, edit=True)

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
            [InlineKeyboardButton(text="📊 Statistika",         callback_data="adm_stats")],
            [InlineKeyboardButton(text="📢 Xabar yuborish",     callback_data="adm_broadcast")],
            [InlineKeyboardButton(text="⏳ Kutilayotgan VIP",   callback_data="adm_pending")],
            [InlineKeyboardButton(text="🏆 O'yin g'oliblari", callback_data="adm_winners")],
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
        [InlineKeyboardButton(text="📊 Statistika",         callback_data="adm_stats")],
        [InlineKeyboardButton(text="📢 Xabar yuborish",     callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="⏳ Kutilayotgan VIP",   callback_data="adm_pending")],
        [InlineKeyboardButton(text="🔄 Referal nolga tush", callback_data="adm_reset_ref")],
        [InlineKeyboardButton(text="👤 1 ta referal nolga", callback_data="adm_reset_one_ref")],
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

@dp.callback_query(F.data == "adm_reset_ref")
async def adm_reset_ref_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.edit_text(
        "⚠️ <b>REFERAL STATISTIKANI NOLGA TUSHIRISH</b>\n\n"
        "Bu amal:\n"
        "• Barcha <b>referral_count → 0</b>\n"
        "• Barcha <b>referral_earnings → 0</b>\n"
        "• <b>referrals</b> jadvali tozalanadi\n\n"
        "💰 <b>Ballar o'zgarmaydi!</b>\n\n"
        "Davom etasizmi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, nolga tushir", callback_data="adm_reset_ref_confirm")],
            [InlineKeyboardButton(text="❌ Bekor",            callback_data="adm_back")],
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "adm_reset_ref_confirm")
async def adm_reset_ref_confirm_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("UPDATE users SET referral_count = 0, referral_earnings = 0")
        cur.execute("DELETE FROM referrals")
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
        await callback.message.edit_text(
            "✅ <b>Referal statistika nolga tushirildi!</b>\n\n"
            "• referral_count → 0\n"
            "• referral_earnings → 0\n"
            "• referrals jadvali tozalandi\n\n"
            "Ballar o'zgarmadi. 💰",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Admin panel", callback_data="adm_back")]
            ])
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Xatolik: {e}")
    await callback.answer()

@dp.callback_query(F.data == "adm_back")
async def adm_back_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    stats = get_stats()
    await callback.message.edit_text(
        f"👨‍💼 <b>ADMIN PANEL</b>\n\n"
        f"👥 Jami: <b>{stats['total']}</b>\n"
        f"💎 VIP: <b>{stats['vip']}</b>\n"
        f"⏳ Kutilmoqda: <b>{stats['pending_vip']}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistika",         callback_data="adm_stats")],
            [InlineKeyboardButton(text="📢 Xabar yuborish",     callback_data="adm_broadcast")],
            [InlineKeyboardButton(text="⏳ Kutilayotgan VIP",   callback_data="adm_pending")],
            [InlineKeyboardButton(text="🔄 Referal nolga tush", callback_data="adm_reset_ref")],
        [InlineKeyboardButton(text="👤 1 ta referal nolga", callback_data="adm_reset_one_ref")],
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "adm_reset_one_ref")
async def adm_reset_one_ref_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(ResetOneRefState.waiting_id)
    await callback.message.answer(
        "👤 <b>1 ta foydalanuvchi referalini nolga tushirish</b>\n\n"
        "Foydalanuvchi <b>ID</b> sini yozing:\n"
        "<i>(Telegram user ID, masalan: 123456789)</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="adm_back")]
        ])
    )
    await callback.answer()

@dp.message(ResetOneRefState.waiting_id)
async def adm_reset_one_ref_id(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not message.text or not message.text.strip().lstrip("-").isdigit():
        await message.answer("❌ Faqat raqam kiriting (ID):")
        return

    target_id = int(message.text.strip())
    user = get_user(target_id)
    if not user:
        await message.answer(
            f"❌ ID <code>{target_id}</code> topilmadi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Admin panel", callback_data="adm_back")]
            ])
        )
        await state.clear()
        return

    await state.clear()
    name     = user.get("name", "Noma'lum")
    ref_cnt  = user.get("referral_count", 0)
    ref_earn = user.get("referral_earnings", 0)

    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE users SET referral_count = 0, referral_earnings = 0 WHERE user_id = %s",
            (target_id,)
        )
        cur.execute(
            "DELETE FROM referrals WHERE referrer_id = %s",
            (target_id,)
        )
        conn.commit()
        cur.close()
        conn.close()
        await message.answer(
            f"✅ <b>Bajarildi!</b>\n\n"
            f"👤 Foydalanuvchi: <b>{name}</b> (<code>{target_id}</code>)\n"
            f"• referral_count: {ref_cnt} → <b>0</b>\n"
            f"• referral_earnings: {ref_earn} → <b>0</b>\n\n"
            f"💰 Ballar o'zgarmadi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Admin panel", callback_data="adm_back")]
            ])
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")

@dp.callback_query(F.data == "adm_winners")
async def adm_winners_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    if not PRIZE_WINNERS:
        await callback.message.answer(
            "🏆 <b>O'YIN G'OLIBLARI</b>\n\n"
            "═══════════════\n"
            "Hali g'olib aniqlanmagan."
        )
        await callback.answer()
        return
    text = "🏆 <b>O'YIN G'OLIBLARI</b>\n═══════════════\n\n"
    buttons = []
    for uid, w in PRIZE_WINNERS.items():
        uname = f"@{w['username']}" if w.get("username") else f"ID:{uid}"
        text += f"👤 <b>{w['name']}</b> ({uname})\n"
        text += f"   ⭐ Ball: {w['score']:,} | 👥 Referal: {w['ref_count']}\n\n"
        buttons.append([InlineKeyboardButton(
            text=f"👤 {w['name']} bilan bog'lanish",
            url=w["link"]
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons + [
        [InlineKeyboardButton(text="✅ O'yin tugadi (g'olib belgilash)", callback_data=f"adm_end_game_{list(PRIZE_WINNERS.keys())[-1]}")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_back")],
    ])
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_end_game_"))
async def adm_end_game_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    uid = int(callback.data.split("_")[-1])
    w   = PRIZE_WINNERS.get(uid, {})
    name  = w.get("name", "?")
    uname = f"@{w['username']}" if w.get("username") else f"ID:{uid}"
    link  = w.get("link", "#")
    # Notify all users that game is over
    user_ids = get_all_user_ids()
    for u_id in user_ids:
        try:
            await bot.send_message(
                u_id,
                "🏆 <b>O'YIN TUGADI!</b>\n\n"
                f"👑 <b>G'OLIB: {name}</b>\n\n"
                "🔄 Yangi o'yin tez orada boshlanadi!\n"
                "Kuzatib boring! 🚀"
            )
            await asyncio.sleep(0.1)
        except Exception:
            pass
    await callback.message.answer(
        f"✅ O'yin tugadi. G'olib: <b>{name}</b> ({uname})\n"
        f"👥 Barcha {len(user_ids)} foydalanuvchiga xabar yuborildi."
    )
    PRIZE_WINNERS.pop(uid, None)
    await callback.answer("O'yin tugadi!", show_alert=True)

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
    user_ids = get_all_user_ids()
    total = len(user_ids)
    progress_msg = await message.answer(f"⏳ Yuborilmoqda... (0/{total})")
    sent = fail = 0
    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
        except Exception:
            fail += 1
        if i % 10 == 0 or i == total:
            try:
                await progress_msg.edit_text(f"⏳ Yuborilmoqda... ({i}/{total})")
            except Exception:
                pass
        await asyncio.sleep(0.1)
    await progress_msg.edit_text(
        f"✅ <b>Xabar yuborildi!</b>\n\n"
        f"📨 Muvaffaqiyatli: <b>{sent}</b>\n"
        f"❌ Yuborilmadi: <b>{fail}</b>\n"
        f"👥 Jami: <b>{total}</b>"
    )
    await state.clear()

# ══════════════════════════════════════════════════
# PUL YUTUG'I BO'LIMI (duplicate o'chirildi)
# ══════════════════════════════════════════════════
async def pul_yutugi_menu_old(message: types.Message):  # DISABLED
    user_id = message.from_user.id
    user    = get_user(user_id)
    if not user:
        await message.answer("❌ Avval /start bosing.")
        return

    score     = user.get("score", 0)
    ref_count = user.get("referral_count", 0)
    prize_claimed = user.get("prize_claimed", False)

    # Ball progressi
    progress_pct = min(100, int(score / PRIZE_BALL_TARGET * 100))
    filled  = progress_pct // 10
    empty   = 10 - filled
    bar     = "█" * filled + "░" * empty

    # Referal progressi (pul yechish uchun)
    ref_ok  = ref_count >= PRIZE_MIN_REFERRAL
    ref_bar = ref_progress_bar(ref_count, PRIZE_MIN_REFERRAL)

    text = (
        "💰 <b>PUL YUTUG'I BO'LIMI</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏆 <b>1-chi sovrin — Ball to'plash:</b>\n"
        f"   Maqsad: <b>{PRIZE_BALL_TARGET:,} ball</b>\n"
        f"   Sizning ballingiz: <b>{score:,}</b>\n"
        f"   [{bar}] {progress_pct}%\n\n"

        "💳 <b>Pul yechish sharti:</b>\n"
        f"   Kamida <b>{PRIZE_MIN_REFERRAL} ta do'st</b> taklif qiling\n"
        f"   {ref_bar}\n"
        f"   {'✅ Shart bajarildi!' if ref_ok else '⏳ Davom eting...'}\n\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        "🎖 <b>2-chi sovrin — Haftalik referal:</b>\n"
        f"   Eng ko'p taklif → <b>{PRIZE_REF_AMOUNT:,} so'm</b>\n"
        f"   Sizning taklif: <b>{ref_count} ta</b>\n"
        f"   Har juma soat 18:00 hisoblanadi\n\n"

        "━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Qanday ishlaydi?</b>\n"
        "  📚 So'z o'rganish → <b>+5 ball</b>\n"
        "  🧠 To'g'ri test → <b>+10 ball</b>\n"
        "  📖 Grammatika → <b>+8 ball</b>\n"
        "  👥 Referal → <b>+50 ball</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 So'z o'rganishni boshlash", callback_data="next_word")],
        [InlineKeyboardButton(text="👥 Referal havolam",           callback_data="more_referral")],
        [InlineKeyboardButton(text="🏆 Reyting",                   callback_data="go_rating")],
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "go_rating")
async def go_rating_cb(callback: types.CallbackQuery):
    top = get_top_scores(10)
    if not top:
        await callback.answer("📊 Hali reyting yo'q.", show_alert=True)
        return
    text   = "🏆 <b>TOP-10 REYTING</b>\n\n━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇","🥈","🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, u in enumerate(top):
        name  = u.get("name") or f"User{u['user_id']}"
        score = u.get("score", 0)
        text += f"{medals[i]} <b>{name}</b> — {score} ball\n"
    await callback.message.answer(text)
    await callback.answer()


# ══════════════════════════════════════════════════
# SO'ROVNOMA TIZIMI
# ══════════════════════════════════════════════════

# Botdagi so'rovnoma savollari (siz xohlagan savollarni qo'shing)
SURVEY_QUESTIONS = [
    {
        "text": "Botda qaysi bo'limdan ko'proq foydalanasiz?",
        "options": ["📚 So'z o'rganish", "🧠 Test", "📖 Grammatika", "👥 Referal"]
    },
    {
        "text": "Yana qanday funksiyalar qo'shishimizni xohlardingiz?",
        "options": ["🗣 Audio talaffuz", "📱 Video darslar", "🤝 Do'stlar bilan o'yin", "🏅 Ko'proq sovrinlar"]
    },
    {
        "text": "Testlarni ishlash — yechish qiyinlik qilyaptimi?",
        "options": ["✅ Yo'q, qulay", "🤔 O'rta darajada", "😓 Ha, qiyin", "🔄 Ba'zida"]
    },
    {
        "text": "Botni do'stingizga tavsiya qilgan bo'larmidingiz?",
        "options": ["💯 Albatta!", "🤔 Ehtimol", "❌ Yo'q", "⏳ Hali bilmayman"]
    },
]

@dp.message(Command("survey"))
async def start_survey_cmd(message: types.Message):
    """Admin /survey yuborganda hamma userlarga so'rovnoma ketadi"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Ruxsat yo'q")
        return

    if ACTIVE_SURVEY.get("running"):
        await message.answer("⚠️ Allaqachon aktiv so'rovnoma bor. Avval /survey_result bilan natijani ko'ring.")
        return

    # So'rovnomani boshlash
    ACTIVE_SURVEY["running"]   = True
    ACTIVE_SURVEY["questions"] = SURVEY_QUESTIONS
    SURVEY_RESULTS.clear()
    SURVEY_COMPLETED_USERS.clear()

    user_ids = get_all_user_ids()
    total    = len(user_ids)
    progress = await message.answer(f"⏳ So'rovnoma yuborilmoqda... (0/{total})")

    sent = fail = 0
    for i, uid in enumerate(user_ids, 1):
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Qatnashish",  callback_data="survey_join"),
                    InlineKeyboardButton(text="❌ Rad qilish",  callback_data="survey_skip"),
                ]
            ])
            await bot.send_message(
                uid,
                "🎯 <b>KICHKINA SO'ROVNOMADAN O'TING VA</b>\n"
                "⭐️ <b>500 BALL OLING!</b>\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"📋 Jami <b>{len(SURVEY_QUESTIONS)} ta savol</b> — atigi 1 daqiqa!\n\n"
                "🎁 So'rovnomani tugatganlar avtomatik <b>+500 ball</b> oladi\n\n"
                "👇 Qatnashasizmi?",
                reply_markup=kb
            )
            sent += 1
        except Exception:
            fail += 1
        if i % 10 == 0 or i == total:
            try:
                await progress.edit_text(f"⏳ So'rovnoma yuborilmoqda... ({i}/{total})")
            except Exception:
                pass
        await asyncio.sleep(0.1)

    await progress.edit_text(
        f"✅ <b>So'rovnoma yuborildi!</b>\n\n"
        f"📨 Muvaffaqiyatli: <b>{sent}</b>\n"
        f"❌ Yuborilmadi: <b>{fail}</b>\n"
        f"👥 Jami: <b>{total}</b>\n\n"
        f"📊 Natijalarni ko'rish: /survey_result"
    )


@dp.callback_query(F.data.startswith("survey_start_"))
async def survey_start_cb(callback: types.CallbackQuery):
    """Foydalanuvchi so'rovnomani boshlaydi"""
    if not ACTIVE_SURVEY.get("running"):
        await callback.answer("❌ So'rovnoma tugagan.", show_alert=True)
        return

    user_id = callback.from_user.id
    q_idx   = int(callback.data.split("_")[2])
    questions = ACTIVE_SURVEY.get("questions", SURVEY_QUESTIONS)

    if q_idx >= len(questions):
        # Tugadi — 500 ball berish
        user_id = callback.from_user.id
        if user_id not in SURVEY_COMPLETED_USERS:
            SURVEY_COMPLETED_USERS.add(user_id)
            add_score(user_id, 500)
            await callback.message.edit_text(
                "✅ <b>Rahmat! So'rovnomani tugatdingiz!</b>\n\n"
                "🎁 Sizning hisobingizga <b>+500 ball</b> qo'shildi!\n"
                "Sizning fikringiz bizga juda muhim 🙏",
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                "✅ <b>Rahmat! So'rovnomani allaqachon tugatgansiz.</b>\n\n"
                "Sizning fikringiz bizga juda muhim 🙏",
                reply_markup=None
            )
        await callback.answer()
        return

    q = questions[q_idx]
    buttons = [
        [InlineKeyboardButton(
            text=opt,
            callback_data=f"survey_ans_{q_idx}_{opt_i}"
        )]
        for opt_i, opt in enumerate(q["options"])
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        f"📋 <b>SO'ROVNOMA</b>  {q_idx + 1}/{len(questions)}\n\n"
        f"❓ <b>{q['text']}</b>\n\n"
        f"👇 Javob tanlang:",
        reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("survey_ans_"))
async def survey_answer_cb(callback: types.CallbackQuery):
    """Foydalanuvchi javob berdi"""
    if not ACTIVE_SURVEY.get("running"):
        await callback.answer("So'rovnoma tugagan.", show_alert=True)
        return

    user_id = callback.from_user.id
    parts   = callback.data.split("_")
    q_idx   = int(parts[2])
    opt_idx = int(parts[3])

    # Javobni saqlash
    if user_id not in SURVEY_RESULTS:
        SURVEY_RESULTS[user_id] = {}
    SURVEY_RESULTS[user_id][q_idx] = opt_idx

    # Keyingi savolga o'tish
    next_q = q_idx + 1
    await callback.answer("✅ Javob qabul qilindi!")

    # survey_start_ handler orqali keyingi savolga o'tamiz
    questions = ACTIVE_SURVEY.get("questions", SURVEY_QUESTIONS)
    if next_q >= len(questions):
        user_id = callback.from_user.id
        if user_id not in SURVEY_COMPLETED_USERS:
            SURVEY_COMPLETED_USERS.add(user_id)
            add_score(user_id, 500)
            await callback.message.edit_text(
                "✅ <b>Rahmat! So'rovnomani tugatdingiz!</b>\n\n"
                "🎁 Sizning hisobingizga <b>+500 ball</b> qo'shildi! ⭐️\n"
                "Sizning fikringiz bizga juda muhim 🙏",
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                "✅ <b>Rahmat!</b> So'rovnomani allaqachon tugatgansiz. 🙏",
                reply_markup=None
            )
        return

    q = questions[next_q]
    buttons = [
        [InlineKeyboardButton(
            text=opt,
            callback_data=f"survey_ans_{next_q}_{opt_i}"
        )]
        for opt_i, opt in enumerate(q["options"])
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        f"📋 <b>SO'ROVNOMA</b>  {next_q + 1}/{len(questions)}\n\n"
        f"❓ <b>{q['text']}</b>\n\n"
        f"👇 Javob tanlang:",
        reply_markup=kb
    )


@dp.message(Command("survey_result"))
async def survey_result_cmd(message: types.Message):
    """Admin natijalarni ko'radi"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Ruxsat yo'q")
        return

    questions     = ACTIVE_SURVEY.get("questions", SURVEY_QUESTIONS)
    total_replied = len(SURVEY_RESULTS)

    if total_replied == 0:
        await message.answer(
            "📊 <b>SO'ROVNOMA NATIJALARI</b>\n\n"
            "Hali hech kim javob bermadi."
        )
        return

    text = f"📊 <b>SO'ROVNOMA NATIJALARI</b>\n"
    text += f"👥 Javob berganlar: <b>{total_replied} kishi</b>\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    for q_idx, q in enumerate(questions):
        # Har variant uchun ovozlarni sana
        counts = [0] * len(q["options"])
        for user_answers in SURVEY_RESULTS.values():
            ans = user_answers.get(q_idx)
            if ans is not None and 0 <= ans < len(q["options"]):
                counts[ans] += 1

        answered = sum(counts)
        text += f"❓ <b>{q['text']}</b>\n"
        for opt_i, opt in enumerate(q["options"]):
            cnt = counts[opt_i]
            pct = int(cnt / answered * 100) if answered else 0
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            text += f"  {opt}\n"
            text += f"  [{bar}] {cnt} kishi ({pct}%)\n"
        text += f"\n  📌 Javob berganlar: <b>{answered}</b>\n\n"
        text += "━━━━━━━━━━━━━━━━━━\n\n"

    # Xabar juda uzun bo'lsa bo'lib yuborish
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await message.answer(chunk)
    else:
        await message.answer(text)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 So'rovnomani yopish", callback_data="survey_close")]
    ])
    await message.answer("So'rovnomani yopmoqchimisiz?", reply_markup=kb)


@dp.callback_query(F.data == "survey_join")
async def survey_join_cb(callback: types.CallbackQuery):
    """Foydalanuvchi so'rovnomaga qatnashishni tangladi"""
    if not ACTIVE_SURVEY.get("running"):
        await callback.answer("❌ So'rovnoma tugagan.", show_alert=True)
        return
    # Birinchi savolga o'tish
    questions = ACTIVE_SURVEY.get("questions", SURVEY_QUESTIONS)
    if not questions:
        await callback.answer("❌ Savollar topilmadi.", show_alert=True)
        return
    q = questions[0]
    buttons = [
        [InlineKeyboardButton(
            text=opt,
            callback_data=f"survey_ans_0_{opt_i}"
        )]
        for opt_i, opt in enumerate(q["options"])
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        f"📋 <b>SO'ROVNOMA</b>  1/{len(questions)}\n\n"
        f"❓ <b>{q['text']}</b>\n\n"
        "👇 Javob tanlang:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data == "survey_skip")
async def survey_skip_cb(callback: types.CallbackQuery):
    """Foydalanuvchi rad qildi"""
    await callback.message.edit_text(
        "😔 So'rovnomadan o'tdingiz.\n\n"
        "Keyingi safar qatnashing — <b>500 ball</b> sizni kutmoqda! 🎁",
        reply_markup=None
    )
    await callback.answer("So'rovnomani rad qildingiz")

@dp.callback_query(F.data == "survey_close")
async def survey_close_cb(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    ACTIVE_SURVEY["running"] = False
    SURVEY_RESULTS.clear()
    await callback.message.edit_text("✅ So'rovnoma yopildi va natijalar tozalandi.")
    await callback.answer()



@dp.message(Command("vip_campaign"))
async def vip_campaign_cmd(message: types.Message):
    """Har bir foydalanuvchiga o'z referal havolasi bilan VIP taklif xabari yuborish"""
    if message.from_user.id not in ADMIN_IDS:
        return
    user_ids = get_all_user_ids()
    total = len(user_ids)
    progress_msg = await message.answer(f"⏳ VIP kampaniya yuborilmoqda... (0/{total})")
    bot_info = await bot.get_me()
    sent = fail = 0
    for i, uid in enumerate(user_ids, 1):
        try:
            user = get_user(uid)
            if not user:
                fail += 1
                continue
            ref_count = user.get("referral_count", 0)
            ref_link  = f"https://t.me/{bot_info.username}?start={uid}"
            needed    = max(0, 3 - ref_count)
            if needed == 0:
                status_line = "✅ Siz allaqachon VIP shartini bajardingiz! Admin tasdiqlashini kuting."
            else:
                status_line = f"Sizning taklifingiz bilan kirganlar: {ref_count}/3"
            text = (
                "🎉 <b>Tabriklaymiz!</b> Siz botimizning birinchi TOP-50 ta foydalanuvchisidan birisiz!\n\n"
                "Biz botga yangi, juda kuchli va yopiq <b>VIP funksiya</b>ni qo'shdik. "
                "(Ko'proq ball yig'ish, hamma guruh so'zlari ochiq va guruh orqali quiz ishlash va boshqa foydali funksiyalar bor).\n\n"
                "Odatda bu funksiya hammaga <b>pullik</b> bo'ladi, lekin TOP-50 likda bo'lganingiz uchun uni sizga <b>TEKIN</b> bermoqchimiz!\n\n"
                "⏳ Aksiya faqat <b>24 soat</b> davom etadi. VIP statusni hoziroq faollashtirish uchun "
                "pastdagi ssilkani <b>3 ta do'stingizga</b> (yoki guruhlarga) yuboring. "
                "Ular botga kirishi bilan, sizning akkauntingiz avtomatik tarzda <b>VIP statusiga</b> o'tadi!\n\n"
                "👇 Sizning shaxsiy ssilkangiz:\n"
                f"<code>{ref_link}</code>\n\n"
                f"Sizning taklifingiz bilan kirganlar: {ref_count}/3"
            )
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception:
            fail += 1
        if i % 10 == 0 or i == total:
            try:
                await progress_msg.edit_text(f"⏳ VIP kampaniya yuborilmoqda... ({i}/{total})")
            except Exception:
                pass
        await asyncio.sleep(0.1)
    await progress_msg.edit_text(
        f"\u2705 <b>VIP kampaniya yuborildi!</b>\n\n"
        f"\U0001f4e8 Muvaffaqiyatli: <b>{sent}</b>\n"
        f"\u274c Yuborilmadi: <b>{fail}</b>\n"
        f"\U0001f465 Jami: <b>{total}</b>"
    )

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

    # ── Bot komandalarini ro'yxatga olish ──
    private_commands = [
        BotCommand(command="start",     description="🚀 Botni boshlash"),
        BotCommand(command="menu",      description="🏠 Bosh menyu"),
        BotCommand(command="quiz",      description="🎯 So'z viktorinasi (Poll)"),
        BotCommand(command="test",      description="🧠 Test ishlash"),
        BotCommand(command="learn",     description="📚 So'z o'rganish"),
        BotCommand(command="grammar",   description="📖 Grammatika"),
        BotCommand(command="streak",    description="🔥 Streak ko'rish"),
        BotCommand(command="rating",    description="🏆 Reyting"),
        BotCommand(command="referral",  description="👥 Referal tizimi"),
        BotCommand(command="vip",       description="💎 VIP Panel"),
    ]
    group_commands = [
        BotCommand(command="quiz",     description="🎯 Viktorina boshlash"),
        BotCommand(command="stopquiz", description="⏹ Viktorinani to'xtatish"),
    ]
    await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(group_commands,   scope=BotCommandScopeAllGroupChats())
    logger.info("✅ Bot komandalari ro'yxatga olindi!")

    asyncio.create_task(weekly_bonus_task())
    asyncio.create_task(vip_expiry_task())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
