import os
import io
import logging
import aiohttp
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

STEP_START, STEP_RESUME, STEP_PREFERENCES, STEP_SEARCH, STEP_VACANCY = range(5)

user_data_store = {}

HH_API_URL = "https://api.hh.ru"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_store[user_id] = {
        'resume': None,
        'preferences': {},
        'vacancies': [],
        'current_vacancy': None
    }
    
    await update.message.reply_text(
        "Привет! Я помогу найти работу на hh.ru и подготовить отклик.\n\n"
        "Давай начнём пошагово:\n\n"
        "**Шаг 1 из 3**: Загрузи своё резюме\n"
        "Отправь файл (PDF, Word) или текст резюме.",
        parse_mode='Markdown'
    )
    return STEP_RESUME


async def receive_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    resume_text = None
    
    if user_id not in user_data_store:
        user_data_store[user_id] = {'resume': None, 'preferences': {}, 'vacancies': [], 'current_vacancy': None}
    
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
        salary_match = re.search(r'от\s*(\d+)', text.replace(' ', ''))
        if salary_match:
            prefs['salary'] = int(salary_match.group(1))
        
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
        pref_text.append(f"от {prefs['salary']} руб")
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


async def search_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.message.text.strip()
    
    if user_id not in user_data_store:
        await update.message.reply_text("Начни сначала: /start")
        return ConversationHandler.END
    
    prefs = user_data_store[user_id].get('preferences', {})
    
    await update.message.reply_text(f"Ищу вакансии: {query}...")
    
    try:
        params = {
            'text': query,
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
        
        vacancies = data.get('items', [])
        
        if not vacancies:
            await update.message.reply_text(
                "Вакансии не найдены.\n"
                "Попробуй изменить запрос или напиши новую должность:"
            )
            return STEP_SEARCH
        
        user_data_store[user_id]['vacancies'] = vacancies
        
        keyboard = []
        for i, vac in enumerate(vacancies[:10]):
            salary_text = ""
            if vac.get('salary'):
                sal = vac['salary']
                if sal.get('from') and sal.get('to'):
                    salary_text = f" | {sal['from']//1000}k-{sal['to']//1000}k"
                elif sal.get('from'):
                    salary_text = f" | от {sal['from']//1000}k"
                elif sal.get('to'):
                    salary_text = f" | до {sal['to']//1000}k"
            
            company = vac.get('employer', {}).get('name', '')[:15]
            button_text = f"{vac['name'][:25]}{salary_text}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"vac_{i}")])
        
        keyboard.append([InlineKeyboardButton("Новый поиск", callback_data="new_search")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Найдено {data.get('found', 0)} вакансий за последние 2 недели.\n"
            f"Показаны первые {min(10, len(vacancies))}:\n\n"
            "Выбери вакансию:",
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
    
    vacancy_index = int(query.data.split('_')[1])
    
    if user_id not in user_data_store or not user_data_store[user_id].get('vacancies'):
        await query.edit_message_text("Сессия истекла. Начни заново: /start")
        return ConversationHandler.END
    
    vacancies = user_data_store[user_id]['vacancies']
    if vacancy_index >= len(vacancies):
        await query.edit_message_text("Вакансия не найдена. Начни заново: /start")
        return ConversationHandler.END
    
    vacancy = vacancies[vacancy_index]
    
    await query.edit_message_text("Загружаю детали вакансии...")
    
    try:
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
            f"**{vacancy_details['name']}**\n\n"
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
        
        keyboard = [
            [InlineKeyboardButton("Сгенерировать сопроводительное письмо", callback_data="gen_cover")],
            [InlineKeyboardButton("Адаптировать резюме", callback_data="adapt_resume")],
            [InlineKeyboardButton("Назад к списку", callback_data="back_search")]
        ]
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
    
    await query.edit_message_text("Генерирую сопроводительное письмо (10-20 сек)...")
    
    description = vacancy.get('description', '')
    from html import unescape
    import re
    description = re.sub(r'<[^>]+>', ' ', description)
    description = unescape(description)
    description = ' '.join(description.split())[:2000]
    
    prompt = f"""Напиши профессиональное сопроводительное письмо на русском языке.

ВАКАНСИЯ:
Название: {vacancy.get('name', '')}
Компания: {vacancy.get('employer', {}).get('name', '')}
Описание: {description}

РЕЗЮМЕ КАНДИДАТА:
{resume[:2500]}

ТРЕБОВАНИЯ:
1. 150-250 слов
2. Показать релевантный опыт
3. Объяснить мотивацию
4. Без шаблонных фраз
5. Начать с конкретики

Напиши только текст письма."""

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
            logger.error(f"Unexpected API response: {result}")
            raise Exception("Неожиданный ответ API")
        
        cover_letter = result['choices'][0]['message']['content']
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Сопроводительное письмо:**\n\n{cover_letter}",
            parse_mode='Markdown'
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ссылка на вакансию: {vacancy.get('alternate_url', '')}\n\n"
                 "Скопируй письмо и отправь вместе с откликом на hh.ru\n\n"
                 "Для нового поиска: /start"
        )
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error generating cover letter: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ошибка генерации: {str(e)}\n\nПопробуй ещё раз или /start"
        )
        return ConversationHandler.END


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
    
    await query.edit_message_text("Анализирую и адаптирую резюме (10-20 сек)...")
    
    description = vacancy.get('description', '')
    from html import unescape
    import re
    description = re.sub(r'<[^>]+>', ' ', description)
    description = unescape(description)
    description = ' '.join(description.split())[:2000]
    
    prompt = f"""Проанализируй вакансию и резюме. Дай конкретные рекомендации.

ВАКАНСИЯ:
Название: {vacancy.get('name', '')}
Компания: {vacancy.get('employer', {}).get('name', '')}
Описание: {description}

РЕЗЮМЕ:
{resume[:3000]}

ЗАДАЧА:
1. Ключевые требования вакансии
2. Что подчеркнуть в резюме
3. Конкретные изменения формулировок
4. Ключевые слова для добавления

Формат: короткие пункты, без воды."""

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
            logger.error(f"Unexpected API response: {result}")
            raise Exception("Неожиданный ответ API")
        
        recommendations = result['choices'][0]['message']['content']
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Рекомендации по адаптации резюме:**\n\n{recommendations}",
            parse_mode='Markdown'
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text="Для нового поиска: /start"
        )
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error adapting resume: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ошибка анализа: {str(e)}\n\nПопробуй /start"
        )
        return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "**HH Resume Helper**\n\n"
        "Этот бот помогает найти работу на hh.ru:\n\n"
        "1. Загрузи резюме (PDF, Word или текст)\n"
        "2. Укажи пожелания (зарплата, удалёнка)\n"
        "3. Найди вакансии\n"
        "4. Получи сопроводительное письмо\n\n"
        "Команды:\n"
        "/start - Начать заново\n"
        "/help - Эта справка\n\n"
        "Поддерживаемые форматы резюме: PDF, DOCX, TXT, текст",
        parse_mode='Markdown'
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено. Для нового поиска: /start")
    return ConversationHandler.END


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set!")
        return
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
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
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', help_command))
    
    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
