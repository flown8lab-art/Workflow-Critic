from dotenv import load_dotenv
import os
import io
import json
import logging
import asyncio
import aiohttp
import requests
from datetime import datetime

load_dotenv()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_IDS = [394363189]  # Список ID администраторов

# Telegram Stars (XTR) — оплата цифровых товаров, provider_token пустой
STARS_COVER = 5
STARS_ADAPT = 5
PAYMENT_CURRENCY = "XTR"
PAYMENT_PROVIDER_TOKEN = ""  # ОСТАВЬ ПУСТЫМ для Telegram Stars
PRICE_STARS = 100  # 100 Stars для платного доступа

# Демо-лимиты бесплатных действий
FREE_COVER_LIMIT = 1
FREE_ADAPT_LIMIT = 1

STEP_START, STEP_RESUME, STEP_PREFERENCES, STEP_SEARCH, STEP_VACANCY = range(5)

# Хранилище пользователей
users = {}

user_data_store = {}
STATS_FILE = 'bot/stats.json'

HH_API_URL = "https://api.hh.ru"
TRUDVSEM_API_URL = "http://opendata.trudvsem.ru/api/v1"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def load_stats():
    try:
        with open(STATS_FILE, 'r') as f:
            stats = json.load(f)
            # Инициализация free_usage если отсутствует
            if 'free_usage' not in stats:
                stats['free_usage'] = {}
            return stats
    except:
        return {'users': [], 'total_searches': 0, 'free_usage': {}}

def save_stats(stats):
    try:
        with open(STATS_FILE, 'w') as f:
            json.dump(stats, f)
    except Exception as e:
        logger.error(f"Error saving stats: {e}")

def can_use_free(user_id: int, action_type: str) -> bool:
    """Проверяет, может ли пользователь использовать бесплатное действие."""
    stats = load_stats()
    free_usage = stats.get('free_usage', {})
    user_usage = free_usage.get(str(user_id), {})
    
    if action_type == 'cover':
        used = user_usage.get('cover', 0)
        return used < FREE_COVER_LIMIT
    elif action_type == 'adapt':
        used = user_usage.get('adapt', 0)
        return used < FREE_ADAPT_LIMIT
    return False

def mark_free_used(user_id: int, action_type: str):
    """Отмечает использование бесплатного действия пользователем."""
    stats = load_stats()
    if 'free_usage' not in stats:
        stats['free_usage'] = {}
    free_usage = stats['free_usage']
    
    user_id_str = str(user_id)
    if user_id_str not in free_usage:
        free_usage[user_id_str] = {'cover': 0, 'adapt': 0}
    
    if action_type in ('cover', 'adapt'):
        free_usage[user_id_str][action_type] = free_usage[user_id_str].get(action_type, 0) + 1
    
    save_stats(stats)

def track_user(user_id: int):
    stats = load_stats()
    if user_id not in stats['users']:
        stats['users'].append(user_id)
        save_stats(stats)

def track_search():
    stats = load_stats()
    stats['total_searches'] = stats.get('total_searches', 0) + 1
    save_stats(stats)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user(user_id)
    user_data_store[user_id] = {
        'resume': None,
        'preferences': {},
        'vacancies': [],
        'current_vacancy': None,
        'current_vacancy_index': 0
    }
    
    await update.message.reply_text(
        "Привет! Я помогу найти работу на hh.ru и подготовить отклик.\n\n"
        "Давай начнём пошагово:\n\n"
        "**Шаг 1 из 3**: Загрузи своё резюме\n"
        "Отправь файл (PDF, Word) или текст резюме.",
        parse_mode='Markdown'
    )
    return STEP_RESUME

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    stats = load_stats()
    total_users = len(stats.get('users', []))
    total_searches = stats.get('total_searches', 0)
    
    await update.message.reply_text(
        f"📊 **Статистика бота**\n\n"
        f"👥 Уникальных пользователей: {total_users}\n"
        f"🔍 Всего поисков: {total_searches}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        parse_mode='Markdown'
    )

async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Твой Telegram ID: `{user_id}`", parse_mode='Markdown')


async def receive_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    resume_text = None
    
    if user_id not in user_data_store:
        user_data_store[user_id] = {'resume': None, 'preferences': {}, 'vacancies': [], 'current_vacancy': None, 'current_vacancy_index': 0}
    
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        file_bytes = await file.download_as_bytearray()
        file_name = update.message.document.file_name.lower()
        
        if file_name.endswith('.pdf'):
            if PdfReader:
                try:
                    pdf = PdfReader(io.BytesIO(bytes(file_bytes)))
                    resume_text = ""
                    for page in pdf.pages:
                        resume_text += page.extract_text() or ""
                except Exception as e:
                    await update.message.reply_text(f"Ошибка чтения PDF: {e}\nПопробуй отправить текстом.")
                    return STEP_RESUME
            else:
                await update.message.reply_text("PDF не поддерживается. Отправь Word или текст.")
                return STEP_RESUME
                
        elif file_name.endswith('.docx'):
            if Document:
                try:
                    doc = Document(io.BytesIO(bytes(file_bytes)))
                    resume_text = "\n".join([p.text for p in doc.paragraphs])
                except Exception as e:
                    await update.message.reply_text(f"Ошибка чтения Word: {e}\nПопробуй отправить текстом.")
                    return STEP_RESUME
            else:
                await update.message.reply_text("Word не поддерживается. Отправь PDF или текст.")
                return STEP_RESUME
                
        elif file_name.endswith('.txt'):
            resume_text = bytes(file_bytes).decode('utf-8')
        else:
            await update.message.reply_text(
                "Формат не поддерживается.\n"
                "Отправь PDF, Word (.docx) или текстовый файл (.txt)"
            )
            return STEP_RESUME
    else:
        resume_text = update.message.text
    
    if not resume_text or len(resume_text.strip()) < 50:
        await update.message.reply_text(
            "Резюме слишком короткое (меньше 50 символов).\n"
            "Пожалуйста, отправь полное резюме."
        )
        return STEP_RESUME
    
    user_data_store[user_id]['resume'] = resume_text.strip()
    
    await update.message.reply_text(
        f"Резюме загружено ({len(resume_text)} символов)\n\n"
        "**Шаг 2 из 3**: Опиши свои пожелания к вакансии\n\n"
        "Напиши своими словами, что важно:\n"
        "• Удалёнка или офис?\n"
        "• Желаемая зарплата?\n"
        "• Опыт работы?\n"
        "• Город?\n\n"
        "Например: «удалёнка, от 150000, без опыта ок, Москва»\n\n"
        "Или напиши «пропустить» чтобы искать без фильтров.",
        parse_mode='Markdown'
    )
    return STEP_PREFERENCES


async def receive_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.lower().strip()
    
    if user_id not in user_data_store:
        await update.message.reply_text("Начни сначала: /start")
        return ConversationHandler.END
    
    prefs = {
        'schedule': None,
        'salary': None,
        'experience': None,
        'area': 113
    }
    
    if text != 'пропустить':
        if 'удалён' in text or 'удален' in text or 'remote' in text:
            prefs['schedule'] = 'remote'
        elif 'офис' in text:
            prefs['schedule'] = 'fullDay'
        
        import re
        salary_match = re.search(r'от\s*(\d+)\s*(тыс|к|k)?', text.replace(' ', ''), re.IGNORECASE)
        if salary_match:
            salary = int(salary_match.group(1))
            suffix = salary_match.group(2)
            if suffix and suffix.lower() in ['тыс', 'к', 'k']:
                salary = salary * 1000
            elif salary < 1000:
                salary = salary * 1000
            prefs['salary'] = salary
        
        if 'без опыт' in text or 'нет опыт' in text:
            prefs['experience'] = 'noExperience'
        elif '1-3' in text or '1 год' in text or '2 год' in text:
            prefs['experience'] = 'between1And3'
        elif '3-6' in text or '3 год' in text or '5 год' in text:
            prefs['experience'] = 'between3And6'
    
    user_data_store[user_id]['preferences'] = prefs
    
    pref_text = []
    if prefs.get('schedule') == 'remote':
        pref_text.append("удалёнка")
    if prefs.get('salary'):
        sal = prefs['salary']
        if sal >= 1000:
            pref_text.append(f"от {sal//1000}k руб")
        else:
            pref_text.append(f"от {sal} руб")
    if prefs.get('experience'):
        exp_map = {'noExperience': 'без опыта', 'between1And3': '1-3 года', 'between3And6': '3-6 лет'}
        pref_text.append(exp_map.get(prefs['experience'], ''))
    
    pref_summary = ", ".join(pref_text) if pref_text else "без фильтров"
    
    await update.message.reply_text(
        f"Фильтры: {pref_summary}\n\n"
        "**Шаг 3 из 3**: Поиск вакансий\n\n"
        "Введи должность для поиска:\n"
        "Например: «менеджер проекта» или «Python разработчик»",
        parse_mode='Markdown'
    )
    return STEP_SEARCH


JOB_SYNONYMS = {
    'менеджер проекта': ['менеджер проекта', 'менеджер проектов', 'project manager', 'руководитель проекта', 'руководитель проектов', 'проектный менеджер', 'PM'],
    'project manager': ['project manager', 'менеджер проекта', 'менеджер проектов', 'руководитель проекта', 'PM'],
    'продакт менеджер': ['продакт менеджер', 'product manager', 'продукт менеджер', 'менеджер продукта', 'product owner', 'PO'],
    'product manager': ['product manager', 'продакт менеджер', 'product owner', 'менеджер продукта'],
    'разработчик': ['разработчик', 'developer', 'программист', 'инженер-программист'],
    'аналитик': ['аналитик', 'analyst', 'бизнес-аналитик', 'системный аналитик', 'data analyst'],
    'дизайнер': ['дизайнер', 'designer', 'UI дизайнер', 'UX дизайнер', 'UI/UX', 'веб-дизайнер'],
    'маркетолог': ['маркетолог', 'marketing manager', 'интернет-маркетолог', 'digital маркетолог'],
    'hr': ['hr', 'HR менеджер', 'рекрутер', 'HR специалист', 'специалист по подбору'],
}

def expand_query(query: str) -> str:
    query_lower = query.lower().strip()
    for key, synonyms in JOB_SYNONYMS.items():
        if key in query_lower or query_lower in key:
            return ' OR '.join(synonyms[:5])
    return query

async def search_trudvsem(query: str, prefs: dict) -> list:
    try:
        params = {
            'text': query,
            'offset': 0,
            'limit': 30
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{TRUDVSEM_API_URL}/vacancies",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    return []
                data = await response.json()
        
        vacancies = []
        results = data.get('results', {}).get('vacancies', [])
        
        for item in results:
            vac = item.get('vacancy', {})
            salary_min = vac.get('salary_min')
            salary_max = vac.get('salary_max')
            
            if prefs.get('salary') and salary_max and salary_max < prefs['salary']:
                continue
            
            vacancies.append({
                'id': f"tv_{vac.get('id', '')}",
                'name': vac.get('job-name', ''),
                'employer': {'name': vac.get('company', {}).get('name', '')},
                'salary': {
                    'from': salary_min,
                    'to': salary_max,
                    'currency': 'RUR'
                } if salary_min or salary_max else None,
                'alternate_url': f"https://trudvsem.ru/vacancy/card/{vac.get('company', {}).get('companycode', '')}/{vac.get('id', '')}",
                'area': {'name': vac.get('region', {}).get('name', '')},
                'source': 'trudvsem'
            })
        return vacancies[:20]
    except Exception as e:
        logger.error(f"Trudvsem error: {e}")
        return []

def search_telegram_vacancies(query: str, prefs: dict) -> list:
    try:
        with open('bot/telegram_vacancies.json', 'r', encoding='utf-8') as f:
            all_vacancies = json.load(f)
    except:
        return []
    
    query_lower = query.lower()
    query_words = query_lower.split()
    
    results = []
    for vac in all_vacancies:
        text = (vac.get('name', '') + ' ' + vac.get('full_text', '')).lower()
        
        if any(word in text for word in query_words):
            if prefs.get('salary'):
                sal = vac.get('salary')
                if sal and sal.get('to') and sal['to'] < prefs['salary']:
                    continue
            
            results.append(vac)
    
    return results[:20]

def build_vacancy_keyboard(vacancies: list, page: int = 0, page_size: int = 10) -> list:
    start = page * page_size
    end = start + page_size
    page_vacancies = vacancies[start:end]
    total_pages = (len(vacancies) + page_size - 1) // page_size
    
    keyboard = []
    for i, vac in enumerate(page_vacancies):
        idx = start + i
        salary_text = ""
        if vac.get('salary'):
            sal = vac['salary']
            sal_from = sal.get('from') or 0
            sal_to = sal.get('to') or 0
            if sal_from and sal_to:
                salary_text = f" ({sal_from//1000}k-{sal_to//1000}k)"
            elif sal_from:
                salary_text = f" (от {sal_from//1000}k)"
            elif sal_to:
                salary_text = f" (до {sal_to//1000}k)"
        
        source = vac.get('source', 'hh')
        if source == 'hh':
            source_icon = "🔵"
        elif source == 'trudvsem':
            source_icon = "🟢"
        else:
            source_icon = "📱"
        company = vac.get('employer', {}).get('name', '')[:12]
        btn_text = f"{source_icon} {vac['name'][:32]}{salary_text} • {company}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"vac_{idx}")])
    
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{page-1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️ Ещё", callback_data=f"page_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)
    
    keyboard.append([InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")])
    return keyboard

async def search_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.message.text.strip()
    
    if user_id not in user_data_store:
        await update.message.reply_text("Начни сначала: /start")
        return ConversationHandler.END
    
    track_search()
    prefs = user_data_store[user_id].get('preferences', {})
    
    expanded_query = expand_query(query)
    
    await update.message.reply_text(f"Ищу вакансии: {query}...")
    
    try:
        params = {
            'text': expanded_query,
            'search_field': 'name',
            'per_page': 20,
            'page': 0,
            'area': prefs.get('area', 113),
            'period': 14
        }
        
        if prefs.get('schedule'):
            params['schedule'] = prefs['schedule']
        if prefs.get('salary'):
            params['salary'] = prefs['salary']
        if prefs.get('experience'):
            params['experience'] = prefs['experience']
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{HH_API_URL}/vacancies",
                params=params,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text[:200]}")
                data = await response.json()
        
        hh_vacancies = data.get('items', [])
        for vac in hh_vacancies:
            vac['source'] = 'hh'
        
        tv_vacancies = await search_trudvsem(query, prefs)
        tg_vacancies = search_telegram_vacancies(query, prefs)
        
        vacancies = hh_vacancies + tv_vacancies + tg_vacancies
        
        if not vacancies:
            await update.message.reply_text(
                "Вакансии не найдены.\n"
                "Попробуй изменить запрос или напиши новую должность:"
            )
            return STEP_SEARCH
        
        seen = set()
        unique_vacancies = []
        exclude_keywords = ['менеджер по продажам', 'sales manager', 'менеджер продаж', 
                           'торговый представитель', 'продавец-консультант', 'продавец']
        for vac in vacancies:
            name_lower = vac.get('name', '').lower()
            if any(excl in name_lower for excl in exclude_keywords):
                continue
            key = (name_lower, vac.get('employer', {}).get('name', '').lower())
            if key not in seen:
                seen.add(key)
                unique_vacancies.append(vac)
        vacancies = unique_vacancies
        
        sources = []
        if hh_vacancies:
            sources.append(f"hh.ru: {len(hh_vacancies)}")
        if tv_vacancies:
            sources.append(f"Работа России: {len(tv_vacancies)}")
        if tg_vacancies:
            sources.append(f"Telegram: {len(tg_vacancies)}")
        source_text = " + ".join(sources) if sources else ""
        
        user_data_store[user_id]['vacancies'] = vacancies
        user_data_store[user_id]['current_page'] = 0
        user_data_store[user_id]['total_found'] = len(vacancies)
        user_data_store[user_id]['source_text'] = source_text
        
        keyboard = build_vacancy_keyboard(vacancies, 0)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Найдено {len(vacancies)} вакансий ({source_text})\n\n"
            "Нажми на вакансию для просмотра:",
            reply_markup=reply_markup
        )
        return STEP_VACANCY
        
    except Exception as e:
        logger.error(f"Error searching vacancies: {e}")
        await update.message.reply_text(
            f"Ошибка при поиске: {str(e)[:100]}\n"
            "Попробуй другой запрос:"
        )
        return STEP_SEARCH


async def vacancy_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == "new_search":
        await query.edit_message_text("Введи новый поисковый запрос:")
        return STEP_SEARCH
    
    if query.data == "back_search":
        await query.edit_message_text("Введи новый поисковый запрос:")
        return STEP_SEARCH
    
    if query.data.startswith("page_"):
        page = int(query.data.split('_')[1])
        vacancies = user_data_store[user_id].get('vacancies', [])
        user_data_store[user_id]['current_page'] = page
        keyboard = build_vacancy_keyboard(vacancies, page)
        total = user_data_store[user_id].get('total_found', len(vacancies))
        await query.edit_message_text(
            f"Найдено {total} вакансий (стр. {page+1}).\n\nНажми на вакансию:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return STEP_VACANCY
    
    vacancy_index = int(query.data.split('_')[1])
    
    if user_id not in user_data_store or not user_data_store[user_id].get('vacancies'):
        await query.edit_message_text("Сессия истекла. Начни заново: /start")
        return ConversationHandler.END
    
    vacancies = user_data_store[user_id]['vacancies']
    if vacancy_index >= len(vacancies):
        await query.edit_message_text("Вакансия не найдена. Начни заново: /start")
        return ConversationHandler.END
    
    vacancy = vacancies[vacancy_index]
    source = vacancy.get('source', 'hh')
    
    await query.edit_message_text("Загружаю детали вакансии...")
    
    try:
        if source == 'telegram':
            vacancy_details = vacancy
            description = vacancy.get('full_text', vacancy.get('name', ''))[:800]
            
            salary_text = "Не указана"
            if vacancy.get('salary'):
                sal = vacancy['salary']
                if sal.get('from') and sal.get('to'):
                    salary_text = f"{sal['from']:,} - {sal['to']:,} руб."
                elif sal.get('from'):
                    salary_text = f"от {sal['from']:,} руб."
                elif sal.get('to'):
                    salary_text = f"до {sal['to']:,} руб."
            
            vacancy_info = (
                f"📱 **{vacancy.get('name', 'Вакансия')}**\n\n"
                f"Компания: {vacancy.get('employer', {}).get('name', 'Не указано')}\n"
                f"Зарплата: {salary_text}\n"
                f"Тип: {vacancy.get('work_type', 'Не указано')}\n"
                f"Канал: {vacancy.get('channel', '')}\n\n"
                f"Описание:\n{description}\n\n"
                f"Ссылка: {vacancy.get('alternate_url', vacancy.get('url', ''))}"
            )
        elif source == 'trudvsem':
            vacancy_details = vacancy
            salary_text = "Не указана"
            if vacancy.get('salary'):
                sal = vacancy['salary']
                if sal.get('from') and sal.get('to'):
                    salary_text = f"{sal['from']:,} - {sal['to']:,} руб."
                elif sal.get('from'):
                    salary_text = f"от {sal['from']:,} руб."
                elif sal.get('to'):
                    salary_text = f"до {sal['to']:,} руб."
            
            vacancy_info = (
                f"🟢 **{vacancy.get('name', 'Вакансия')}**\n\n"
                f"Компания: {vacancy.get('employer', {}).get('name', 'Не указано')}\n"
                f"Зарплата: {salary_text}\n"
                f"Регион: {vacancy.get('area', {}).get('name', 'Не указано')}\n\n"
                f"Ссылка: {vacancy.get('alternate_url', '')}"
            )
        else:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{HH_API_URL}/vacancies/{vacancy['id']}",
                    headers=HEADERS,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")
                    vacancy_details = await response.json()
            
            description = vacancy_details.get('description', '')
            from html import unescape
            import re
            description = re.sub(r'<[^>]+>', ' ', description)
            description = unescape(description)
            description = ' '.join(description.split())[:800]
            
            salary_text = "Не указана"
            if vacancy_details.get('salary'):
                sal = vacancy_details['salary']
                if sal.get('from') and sal.get('to'):
                    salary_text = f"{sal['from']:,} - {sal['to']:,} {sal.get('currency', '')}"
                elif sal.get('from'):
                    salary_text = f"от {sal['from']:,} {sal.get('currency', '')}"
                elif sal.get('to'):
                    salary_text = f"до {sal['to']:,} {sal.get('currency', '')}"
            
            vacancy_info = (
                f"🔵 **{vacancy_details['name']}**\n\n"
                f"Компания: {vacancy_details.get('employer', {}).get('name', 'Не указано')}\n"
                f"Зарплата: {salary_text}\n"
                f"Город: {vacancy_details.get('area', {}).get('name', 'Не указано')}\n"
                f"Опыт: {vacancy_details.get('experience', {}).get('name', 'Не указано')}\n"
                f"Занятость: {vacancy_details.get('schedule', {}).get('name', 'Не указано')}\n\n"
                f"Описание:\n{description}...\n\n"
                f"Ссылка: {vacancy_details.get('alternate_url', '')}"
            )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=vacancy_info,
            parse_mode='Markdown'
        )
        
        user_data_store[user_id]['current_vacancy'] = vacancy_details
        user_data_store[user_id]['current_vacancy_index'] = vacancy_index
        
        keyboard = [
            [InlineKeyboardButton("Сгенерировать сопроводительное письмо", callback_data="gen_cover")],
            [InlineKeyboardButton("Адаптировать резюме", callback_data="adapt_resume")],
            [InlineKeyboardButton("Назад к списку", callback_data="back_to_list")]
        ]
        
        if vacancy_index + 1 < len(vacancies):
            keyboard.insert(2, [InlineKeyboardButton(f"➡️ Следующая ({vacancy_index + 2} из {len(vacancies)})", callback_data=f"vac_{vacancy_index + 1}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=user_id,
            text="Что сделать?",
            reply_markup=reply_markup
        )
        return STEP_VACANCY
        
    except Exception as e:
        logger.error(f"Error getting vacancy details: {e}")
        await context.bot.send_message(chat_id=user_id, text=f"Ошибка: {str(e)}")
        return STEP_VACANCY


async def _execute_cover_generation(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Генерация сопроводительного письма (вызывается после успешной оплаты)."""
    from html import unescape
    import re
    resume = user_data_store[user_id].get('resume')
    vacancy = user_data_store[user_id].get('current_vacancy')
    if not resume or not vacancy:
        await context.bot.send_message(chat_id=user_id, text="Данные не найдены. Начни заново: /start")
        return
    description = vacancy.get('description', '')
    description = re.sub(r'<[^>]+>', ' ', description)
    description = unescape(description)
    description = ' '.join(description.split())[:2000]
    prompt = f"""Напиши сопроводительное письмо на русском языке. Пиши простым человеческим языком, как будто пишет живой человек, а не робот.

ВАКАНСИЯ:
Название: {vacancy.get('name', '')}
Компания: {vacancy.get('employer', {}).get('name', '')}
Описание: {description}

РЕЗЮМЕ КАНДИДАТА:
{resume[:2500]}

ВАЖНЫЕ ПРАВИЛА СТИЛЯ:
1. НЕ ПИШИ "С большим интересом узнал" или "С удовольствием откликаюсь" — это шаблоны
2. Начни просто: "Увидел вашу вакансию, откликнулась потому что..." или "Заинтересовала позиция, так как..."
3. НЕ ПИШИ про "уникальную технологию", "выдающиеся результаты", "динамичный контекст" — это пафос
4. Мотивация должна быть честной и win-win: "У меня есть опыт X, хочу его применять и развиваться. Вижу, что вам нужен Y — могу быть полезен"
5. Без заискивания и лести компании
6. Коротко про релевантный опыт (1-2 конкретных примера)
7. Длина: 120-180 слов максимум
8. Тон: уверенный, но не высокомерный. Деловой, но человечный.

Напиши только текст письма, без заголовков и подписей."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://replit.com",
                    "X-Title": "HH Resume Helper"
                },
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 800
                },
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                result = await response.json()
        if 'error' in result:
            raise Exception(f"API: {result['error'].get('message', result['error'])}")
        if 'choices' not in result or not result['choices']:
            raise Exception("Неожиданный ответ API")
        cover_letter = result['choices'][0]['message']['content']
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Сопроводительное письмо:**\n\n{cover_letter}",
            parse_mode='Markdown'
        )
        vacancies = user_data_store[user_id].get('vacancies', [])
        current_idx = user_data_store[user_id].get('current_vacancy_index', 0)
        keyboard = []
        if current_idx + 1 < len(vacancies[:10]):
            keyboard.append([InlineKeyboardButton(f"➡️ Следующая ({current_idx + 2} из {len(vacancies)})", callback_data=f"vac_{current_idx + 1}")])
        keyboard.append([InlineKeyboardButton("Назад к списку вакансий", callback_data="back_to_list")])
        keyboard.append([InlineKeyboardButton("Новый поиск", callback_data="new_search")])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ссылка: {vacancy.get('alternate_url', '')}\n\nСкопируй письмо и отправь на hh.ru",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error generating cover letter: {e}")
        await context.bot.send_message(chat_id=user_id, text=f"Ошибка генерации: {str(e)}")


async def _execute_adapt_resume(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Адаптация резюме под вакансию (вызывается после успешной оплаты)."""
    from html import unescape
    import re
    resume = user_data_store[user_id].get('resume')
    vacancy = user_data_store[user_id].get('current_vacancy')
    if not resume or not vacancy:
        await context.bot.send_message(chat_id=user_id, text="Данные не найдены. Начни заново: /start")
        return
    description = vacancy.get('description', '')
    description = re.sub(r'<[^>]+>', ' ', description)
    description = unescape(description)
    description = ' '.join(description.split())[:2000]
    prompt = f"""Ты редактор резюме. Дай КОНКРЕТНЫЕ правки для адаптации этого резюме под вакансию.

ВАКАНСИЯ:
{vacancy.get('name', '')} в {vacancy.get('employer', {}).get('name', '')}
{description}

РЕЗЮМЕ КАНДИДАТА:
{resume[:3000]}

ВАЖНО: Не пиши общие советы! Давай ТОЧНЫЕ правки к КОНКРЕТНЫМ местам резюме.

Формат ответа:

📝 ПРАВКИ В РЕЗЮМЕ:

1. В разделе "Опыт работы" → [название компании/должности из резюме]:
   БЫЛО: "[точная цитата из резюме]"
   СТАЛО: "[переписанная версия]"

2. В разделе "Навыки":
   ДОБАВИТЬ: [конкретный навык из требований вакансии]

3. В разделе "О себе" / "Цель":
   БЫЛО: "[цитата]"
   СТАЛО: "[новая версия]"

🎯 КЛЮЧЕВЫЕ СЛОВА ИЗ ВАКАНСИИ (добавь в резюме):
- [слово 1] — вставить в [конкретный раздел]
- [слово 2] — вставить в [конкретный раздел]

Дай 3-5 конкретных правок. Цитируй реальные фразы из резюме пользователя."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://replit.com",
                    "X-Title": "HH Resume Helper"
                },
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000
                },
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                result = await response.json()
        if 'error' in result:
            raise Exception(f"API: {result['error'].get('message', result['error'])}")
        if 'choices' not in result or not result['choices']:
            raise Exception("Неожиданный ответ API")
        recommendations = result['choices'][0]['message']['content']
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Рекомендации по адаптации резюме:**\n\n{recommendations}",
            parse_mode='Markdown'
        )
        vacancies = user_data_store[user_id].get('vacancies', [])
        current_idx = user_data_store[user_id].get('current_vacancy_index', 0)
        keyboard = []
        if current_idx + 1 < len(vacancies[:10]):
            keyboard.append([InlineKeyboardButton(f"➡️ Следующая ({current_idx + 2} из {len(vacancies)})", callback_data=f"vac_{current_idx + 1}")])
        keyboard.append([InlineKeyboardButton("Назад к списку вакансий", callback_data="back_to_list")])
        keyboard.append([InlineKeyboardButton("Новый поиск", callback_data="new_search")])
        await context.bot.send_message(
            chat_id=user_id,
            text="Что дальше?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error adapting resume: {e}")
        await context.bot.send_message(chat_id=user_id, text=f"Ошибка анализа: {str(e)}")


async def generate_cover_letter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id not in user_data_store:
        await query.edit_message_text("Сессия истекла. Начни заново: /start")
        return ConversationHandler.END
    resume = user_data_store[user_id].get('resume')
    vacancy = user_data_store[user_id].get('current_vacancy')
    if not resume:
        await query.edit_message_text("Резюме не найдено. Начни заново: /start")
        return ConversationHandler.END
    if not vacancy:
        await query.edit_message_text("Вакансия не выбрана. Начни заново: /start")
        return ConversationHandler.END
    
    # Проверка бесплатного лимита
    if can_use_free(user_id, 'cover'):
        mark_free_used(user_id, 'cover')
        await query.edit_message_text("Генерирую сопроводительное письмо (10-20 сек)...")
        await _execute_cover_generation(context, user_id)
        return STEP_VACANCY
    
    # Лимит исчерпан - отправляем invoice
    await query.edit_message_text("Ниже счёт на оплату. После оплаты письмо придёт в этот чат.")
    await context.bot.send_invoice(
        chat_id=user_id,
        title="Сопроводительное письмо (AI)",
        description="Генерация сопроводительного письма под выбранную вакансию",
        payload="cover",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency=PAYMENT_CURRENCY,
        prices=[LabeledPrice(label="Сопроводительное письмо", amount=STARS_COVER)]
    )
    return STEP_VACANCY


async def adapt_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id not in user_data_store:
        await query.edit_message_text("Сессия истекла. Начни заново: /start")
        return ConversationHandler.END
    resume = user_data_store[user_id].get('resume')
    vacancy = user_data_store[user_id].get('current_vacancy')
    if not resume or not vacancy:
        await query.edit_message_text("Данные не найдены. Начни заново: /start")
        return ConversationHandler.END
    
    # Проверка бесплатного лимита
    if can_use_free(user_id, 'adapt'):
        mark_free_used(user_id, 'adapt')
        await query.edit_message_text("Анализирую и адаптирую резюме (10-20 сек)...")
        await _execute_adapt_resume(context, user_id)
        return STEP_VACANCY
    
    # Лимит исчерпан - отправляем invoice
    await query.edit_message_text("Ниже счёт на оплату. После оплаты рекомендации придут в этот чат.")
    await context.bot.send_invoice(
        chat_id=user_id,
        title="Адаптация резюме (AI)",
        description="Рекомендации по адаптации резюме под выбранную вакансию в формате БЫЛО/СТАЛО",
        payload="adapt",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency=PAYMENT_CURRENCY,
        prices=[LabeledPrice(label="Адаптация резюме", amount=STARS_ADAPT)]
    )
    return STEP_VACANCY


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда покупки платного доступа через Telegram Stars."""
    logger.info("BUY COMMAND TRIGGERED")
    
    prices = [LabeledPrice("Доступ", 100)]
    
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title="Премиум доступ",
        description="Полный доступ",
        payload="paid_access",
        provider_token="",
        currency="XTR",
        prices=prices,
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик pre-checkout с логированием для отладки."""
    print("PRECHECKOUT TRIGGERED")
    query = update.pre_checkout_query
    payload = (query.invoice_payload or "").strip()
    logger.info(f"Pre-checkout query received: payload={payload}")
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешной оплаты."""
    if not update.message or not update.message.successful_payment:
        return
    payment = update.message.successful_payment
    user_id = update.effective_user.id
    payload = (payment.invoice_payload or "").strip()
    
    logger.info(f"Successful payment received: user_id={user_id}, payload={payload}")
    
    if payload == "cover":
        await update.message.reply_text("Оплата получена. Генерирую письмо (10–20 сек)...")
        await _execute_cover_generation(context, user_id)
    elif payload == "adapt":
        await update.message.reply_text("Оплата получена. Анализирую резюме (10–20 сек)...")
        await _execute_adapt_resume(context, user_id)
    elif payload == "HR_ANALYSIS_100":
        # TODO: сохранить user_id + payment.invoice_payload в БД
        await update.message.reply_text("✅ Оплата прошла успешно! Доступ активирован.")
    elif payload == "paid_access":
        users[user_id] = {"paid": True}
        await update.message.reply_text("Оплата прошла успешно. Доступ открыт.")
    else:
        await update.message.reply_text("Оплата зачислена. Если ожидался другой результат — напиши в поддержку.")


async def premium_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пример премиум-функции с проверкой доступа."""
    user_id = update.effective_user.id
    
    if user_id not in users or not users[user_id].get("paid"):
        await update.message.reply_text("Доступ только для оплативших. Используй /buy")
        return
    
    await update.message.reply_text("Вот премиум-функция")


async def back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id not in user_data_store or not user_data_store[user_id].get('vacancies'):
        await query.edit_message_text("Сессия истекла. Начни заново: /start")
        return ConversationHandler.END
    
    vacancies = user_data_store[user_id]['vacancies']
    page = user_data_store[user_id].get('current_page', 0)
    total = user_data_store[user_id].get('total_found', len(vacancies))
    
    keyboard = build_vacancy_keyboard(vacancies, page)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Найдено {total} вакансий.\n\nНажми на вакансию:",
        reply_markup=reply_markup
    )
    return STEP_VACANCY


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **HH Resume Helper**\n\n"
        "Автоматический поиск работы на hh.ru\n\n"
        "**Что умеет бот:**\n"
        "• Анализирует твоё резюме\n"
        "• Ищет вакансии с фильтрами (зарплата, удалёнка, опыт)\n"
        "• Генерирует сопроводительные письма\n"
        "• Даёт рекомендации по адаптации резюме\n\n"
        "**Как пользоваться:**\n"
        "1️⃣ Загрузи резюме (PDF, Word или текст)\n"
        "2️⃣ Укажи пожелания (например: «удалёнка, от 150к»)\n"
        "3️⃣ Введи должность для поиска\n"
        "4️⃣ Выбери вакансию и получи письмо\n\n"
        "**Команды:**\n"
        "/start — Начать поиск работы\n"
        "/help — Справка\n"
        "/cancel — Отменить\n\n"
        "📎 Форматы резюме: PDF, DOCX, TXT",
        parse_mode='Markdown'
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено. Для нового поиска: /start")
    return ConversationHandler.END


async def callback_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для нажатий кнопок, когда диалог не активен (сессия истекла или бот перезапущен)."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Сессия истекла или бот был перезапущен. Введи /start чтобы начать заново."
    )


async def run_parser_periodically():
    """Run telegram parser every 12 hours"""
    await asyncio.sleep(120)
    while True:
        try:
            logger.info("Starting scheduled parser run...")
            import subprocess
            result = subprocess.run(
                ['python3', 'bot/telegram_parser.py'],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                logger.info("Parser completed successfully")
            else:
                logger.error(f"Parser error: {result.stderr}")
        except Exception as e:
            logger.error(f"Parser exception: {e}")
        await asyncio.sleep(12 * 60 * 60)

async def post_init(application):
    await application.bot.set_my_commands([
        ("start", "Начать поиск работы"),
        ("help", "Справка и возможности"),
        ("cancel", "Отменить текущий поиск")
    ])
    # Запуск фоновой задачи парсера
    asyncio.create_task(run_parser_periodically())

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        logger.error("Проверьте файл .env и убедитесь, что TELEGRAM_BOT_TOKEN установлен")
        return
    
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set!")
        logger.error("Проверьте файл .env и убедитесь, что OPENROUTER_API_KEY установлен")
        return
    
    try:
        application = Application.builder().token(TOKEN).post_init(post_init).build()
    except Exception as e:
        logger.error(f"Ошибка при создании Application: {e}")
        return
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            STEP_RESUME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_resume),
                MessageHandler(filters.Document.ALL, receive_resume)
            ],
            STEP_PREFERENCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_preferences)
            ],
            STEP_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_vacancies)
            ],
            STEP_VACANCY: [
                CallbackQueryHandler(vacancy_selected, pattern=r'^vac_\d+$'),
                CallbackQueryHandler(vacancy_selected, pattern='^new_search$'),
                CallbackQueryHandler(vacancy_selected, pattern='^back_search$'),
                CallbackQueryHandler(vacancy_selected, pattern=r'^page_\d+$'),
                CallbackQueryHandler(back_to_list, pattern='^back_to_list$'),
                CallbackQueryHandler(generate_cover_letter, pattern='^gen_cover$'),
                CallbackQueryHandler(adapt_resume, pattern='^adapt_resume$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_vacancies)
            ]
        },
        fallbacks=[
            CommandHandler('start', start),
            CommandHandler('cancel', cancel)
        ],
        allow_reentry=True
    )
    
   # ===== ПЛАТЕЖИ (САМЫЙ ВЫСОКИЙ ПРИОРИТЕТ) =====
    application.add_handler(CommandHandler("buy", buy_command), group=0)
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback), group=0)
    application.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback),
        group=0
    )

    # ===== ПРОСТЫЕ КОМАНДЫ =====
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command), group=1)
    application.add_handler(CommandHandler("stats", stats_command), group=1)
    application.add_handler(CommandHandler("myid", myid_command), group=1)
    application.add_handler(CommandHandler("premium", premium_feature), group=1)

    # ===== DIALOG FLOW =====
    application.add_handler(conv_handler, group=1)

    # Обработчик нажатий кнопок вне диалога (group=2 — после conv_handler)
    application.add_handler(CallbackQueryHandler(callback_fallback), group=2)

    logger.info("Bot starting...")
    logger.info(f"TOKEN loaded: {'Yes' if TOKEN else 'No'}")
    logger.info(f"OPENROUTER_API_KEY loaded: {'Yes' if OPENROUTER_API_KEY else 'No'}")
    
    try:
        logger.info("Starting run_polling()...")
        application.run_polling(
            application.run_polling()
            drop_pending_updates=True
        )
        logger.info("run_polling() completed (this should not happen normally)")
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
