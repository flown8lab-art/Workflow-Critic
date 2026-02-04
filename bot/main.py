import os
import logging
import aiohttp
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')

WAITING_RESUME, WAITING_SEARCH, SELECTING_VACANCY = range(3)

user_data_store = {}

HH_API_URL = "https://api.hh.ru"
HEADERS = {'User-Agent': 'HHResumeHelper/1.0 (api@example.com)'}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я помогу тебе найти работу на hh.ru\n\n"
        "Вот что я умею:\n"
        "/search - Поиск вакансий\n"
        "/resume - Загрузить своё резюме\n"
        "/help - Помощь\n\n"
        "Для начала отправь мне своё резюме (текстом или файлом .txt)"
    )
    return WAITING_RESUME


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды бота:\n\n"
        "/start - Начать работу\n"
        "/search - Поиск вакансий на hh.ru\n"
        "/resume - Загрузить/обновить резюме\n"
        "/status - Статус текущего резюме\n"
        "/help - Эта справка\n\n"
        "Как пользоваться:\n"
        "1. Загрузи своё резюме\n"
        "2. Ищи вакансии командой /search\n"
        "3. Выбери вакансию и получи сопроводительное письмо"
    )


async def receive_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        file_bytes = await file.download_as_bytearray()
        resume_text = file_bytes.decode('utf-8')
    else:
        resume_text = update.message.text
    
    if len(resume_text) < 50:
        await update.message.reply_text(
            "Резюме слишком короткое. Пожалуйста, отправь полное резюме."
        )
        return WAITING_RESUME
    
    user_data_store[user_id] = {
        'resume': resume_text,
        'vacancies': []
    }
    
    await update.message.reply_text(
        "Резюме сохранено!\n\n"
        "Теперь используй /search чтобы найти вакансии.\n"
        "Например: /search Python разработчик Москва"
    )
    return ConversationHandler.END


async def search_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "Укажи поисковый запрос:\n"
            "/search Python разработчик\n"
            "/search менеджер продаж Москва"
        )
        return
    
    query = ' '.join(context.args)
    await update.message.reply_text(f"Ищу вакансии: {query}...")
    
    try:
        params = {
            'text': query,
            'per_page': 10,
            'page': 0,
            'area': 113
        }
        
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
            await update.message.reply_text("Вакансии не найдены. Попробуй другой запрос.")
            return
        
        if user_id not in user_data_store:
            user_data_store[user_id] = {'resume': None, 'vacancies': []}
        
        user_data_store[user_id]['vacancies'] = vacancies
        
        keyboard = []
        for i, vac in enumerate(vacancies[:10]):
            salary_text = ""
            if vac.get('salary'):
                sal = vac['salary']
                if sal.get('from') and sal.get('to'):
                    salary_text = f" ({sal['from']}-{sal['to']} {sal.get('currency', '')})"
                elif sal.get('from'):
                    salary_text = f" (от {sal['from']} {sal.get('currency', '')})"
                elif sal.get('to'):
                    salary_text = f" (до {sal['to']} {sal.get('currency', '')})"
            
            button_text = f"{vac['name'][:30]}{salary_text}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"vac_{i}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Найдено {data.get('found', 0)} вакансий. Выбери одну:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error searching vacancies: {e}")
        await update.message.reply_text(f"Ошибка при поиске: {str(e)}")


async def vacancy_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    vacancy_index = int(query.data.split('_')[1])
    
    if user_id not in user_data_store or not user_data_store[user_id].get('vacancies'):
        await query.edit_message_text("Сначала выполни поиск /search")
        return
    
    vacancies = user_data_store[user_id]['vacancies']
    if vacancy_index >= len(vacancies):
        await query.edit_message_text("Вакансия не найдена")
        return
    
    vacancy = vacancies[vacancy_index]
    
    await query.edit_message_text("Загружаю детали вакансии...")
    
    try:
        response = requests.get(
            f"{HH_API_URL}/vacancies/{vacancy['id']}",
            headers=HEADERS,
            timeout=10
        )
        response.raise_for_status()
        vacancy_details = response.json()
        
        description = vacancy_details.get('description', '')
        from html import unescape
        import re
        description = re.sub(r'<[^>]+>', ' ', description)
        description = unescape(description)
        description = ' '.join(description.split())[:1500]
        
        salary_text = "Не указана"
        if vacancy_details.get('salary'):
            sal = vacancy_details['salary']
            if sal.get('from') and sal.get('to'):
                salary_text = f"{sal['from']}-{sal['to']} {sal.get('currency', '')}"
            elif sal.get('from'):
                salary_text = f"от {sal['from']} {sal.get('currency', '')}"
            elif sal.get('to'):
                salary_text = f"до {sal['to']} {sal.get('currency', '')}"
        
        vacancy_info = (
            f"**{vacancy_details['name']}**\n"
            f"Компания: {vacancy_details.get('employer', {}).get('name', 'Не указано')}\n"
            f"Зарплата: {salary_text}\n"
            f"Город: {vacancy_details.get('area', {}).get('name', 'Не указано')}\n\n"
            f"Описание:\n{description[:500]}...\n\n"
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
            [InlineKeyboardButton("Назад к поиску", callback_data="back_search")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=user_id,
            text="Что сделать с этой вакансией?",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error getting vacancy details: {e}")
        await context.bot.send_message(chat_id=user_id, text=f"Ошибка: {str(e)}")


async def generate_cover_letter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id not in user_data_store:
        await query.edit_message_text("Сначала загрузи резюме командой /resume")
        return
    
    resume = user_data_store[user_id].get('resume')
    vacancy = user_data_store[user_id].get('current_vacancy')
    
    if not vacancy:
        await query.edit_message_text("Сначала выбери вакансию")
        return
    
    if not resume:
        await query.edit_message_text(
            "Загрузи своё резюме для генерации персонализированного письма.\n"
            "Отправь текст резюме или используй /resume"
        )
        return
    
    await query.edit_message_text("Генерирую сопроводительное письмо...")
    
    description = vacancy.get('description', '')
    from html import unescape
    import re
    description = re.sub(r'<[^>]+>', ' ', description)
    description = unescape(description)
    description = ' '.join(description.split())[:2000]
    
    prompt = f"""Напиши профессиональное сопроводительное письмо на русском языке для отклика на вакансию.

ВАКАНСИЯ:
Название: {vacancy.get('name', '')}
Компания: {vacancy.get('employer', {}).get('name', '')}
Описание: {description}

РЕЗЮМЕ КАНДИДАТА:
{resume[:2000]}

ТРЕБОВАНИЯ К ПИСЬМУ:
1. Письмо должно быть кратким (150-250 слов)
2. Показать релевантный опыт из резюме
3. Объяснить мотивацию работать именно в этой компании
4. Быть профессиональным, но не формальным
5. Не использовать шаблонные фразы типа "я ответственный и коммуникабельный"
6. Начать с конкретики, не с "Здравствуйте, меня зовут..."

Напиши только текст письма, без комментариев."""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        cover_letter = result['choices'][0]['message']['content']
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Сопроводительное письмо:**\n\n{cover_letter}\n\n"
                 f"Ссылка на вакансию: {vacancy.get('alternate_url', '')}",
            parse_mode='Markdown'
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text="Скопируй письмо и отправь его вместе с откликом на hh.ru"
        )
        
    except Exception as e:
        logger.error(f"Error generating cover letter: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ошибка генерации: {str(e)}"
        )


async def adapt_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id not in user_data_store:
        await query.edit_message_text("Сначала загрузи резюме командой /resume")
        return
    
    resume = user_data_store[user_id].get('resume')
    vacancy = user_data_store[user_id].get('current_vacancy')
    
    if not vacancy:
        await query.edit_message_text("Сначала выбери вакансию")
        return
    
    if not resume:
        await query.edit_message_text("Загрузи своё резюме для адаптации")
        return
    
    await query.edit_message_text("Анализирую вакансию и адаптирую резюме...")
    
    description = vacancy.get('description', '')
    from html import unescape
    import re
    description = re.sub(r'<[^>]+>', ' ', description)
    description = unescape(description)
    description = ' '.join(description.split())[:2000]
    
    prompt = f"""Проанализируй вакансию и резюме. Предложи конкретные изменения в резюме, чтобы оно лучше соответствовало вакансии.

ВАКАНСИЯ:
Название: {vacancy.get('name', '')}
Компания: {vacancy.get('employer', {}).get('name', '')}
Описание: {description}

ТЕКУЩЕЕ РЕЗЮМЕ:
{resume[:3000]}

ЗАДАЧА:
1. Выдели ключевые требования вакансии
2. Найди в резюме релевантный опыт
3. Предложи, какие навыки и достижения выделить
4. Предложи, какие формулировки изменить
5. Укажи, какие ключевые слова добавить

Формат ответа:
- Ключевые требования вакансии: ...
- Что подчеркнуть в резюме: ...
- Конкретные изменения: ...
- Рекомендуемые ключевые слова: ..."""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        recommendations = result['choices'][0]['message']['content']
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Рекомендации по адаптации резюме:**\n\n{recommendations}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error adapting resume: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ошибка анализа: {str(e)}"
        )


async def back_to_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Используй /search для нового поиска")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_data_store or not user_data_store[user_id].get('resume'):
        await update.message.reply_text(
            "Резюме не загружено.\n"
            "Отправь своё резюме текстом или файлом .txt"
        )
        return
    
    resume = user_data_store[user_id]['resume']
    await update.message.reply_text(
        f"Резюме загружено ({len(resume)} символов)\n\n"
        f"Превью:\n{resume[:300]}...\n\n"
        f"Используй /search для поиска вакансий"
    )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправь своё резюме:\n"
        "- Текстом прямо в чат\n"
        "- Или файлом .txt\n\n"
        "Резюме будет использоваться для генерации персонализированных писем."
    )
    return WAITING_RESUME


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if len(text) > 100:
        user_data_store[user_id] = {
            'resume': text,
            'vacancies': []
        }
        await update.message.reply_text(
            "Резюме сохранено!\n"
            "Используй /search для поиска вакансий."
        )
    else:
        await update.message.reply_text(
            "Не понял команду. Используй /help для справки.\n\n"
            "Если хочешь загрузить резюме, отправь полный текст (больше 100 символов)."
        )


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set!")
        return
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('resume', resume_command)
        ],
        states={
            WAITING_RESUME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_resume),
                MessageHandler(filters.Document.TEXT, receive_resume)
            ]
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('search', search_vacancies))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CallbackQueryHandler(vacancy_selected, pattern=r'^vac_\d+$'))
    application.add_handler(CallbackQueryHandler(generate_cover_letter, pattern='^gen_cover$'))
    application.add_handler(CallbackQueryHandler(adapt_resume, pattern='^adapt_resume$'))
    application.add_handler(CallbackQueryHandler(back_to_search, pattern='^back_search$'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
