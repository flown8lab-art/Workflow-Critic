import os
import json
import asyncio
import logging
import re
import aiohttp
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNELS = [
    'remote_it_jobs',
    'getitru',
    'fordev',
    'devjobs',
    'tproger_official',
    'helocareer',
    'myresume_jobs',
    'ukrainiandevjobs',
    'djinni_jobs_all',
    'finder_jobs',
]

VACANCIES_FILE = 'bot/telegram_vacancies.json'

JOB_KEYWORDS = [
    'вакансия', 'ищем', 'hiring', 'требуется', 'нужен', 'открыта позиция',
    'junior', 'middle', 'senior', 'lead', 'разработчик', 'developer',
    'менеджер', 'manager', 'аналитик', 'analyst', 'дизайнер', 'designer',
    'тестировщик', 'qa', 'devops', 'frontend', 'backend', 'fullstack',
    'python', 'java', 'javascript', 'react', 'vue', 'angular', 'node',
    'product', 'project', 'pm', 'hr', 'recruiter', 'зарплата', 'salary',
    'оклад', 'remote', 'удалённ', 'удаленн'
]

SALARY_PATTERN = re.compile(
    r'(?:от\s*)?(\d+[\s,.]?\d*)\s*(?:[-–—до]\s*(\d+[\s,.]?\d*))?\s*(?:тыс|k|к|₽|руб|rub|\$|usd|eur)?',
    re.IGNORECASE
)

def load_vacancies():
    try:
        with open(VACANCIES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_vacancies(vacancies):
    with open(VACANCIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(vacancies, f, ensure_ascii=False, indent=2)

def extract_salary(text):
    match = SALARY_PATTERN.search(text)
    if match:
        try:
            sal_from = int(match.group(1).replace(' ', '').replace(',', '').replace('.', ''))
            sal_to = int(match.group(2).replace(' ', '').replace(',', '').replace('.', '')) if match.group(2) else None
            
            if sal_from < 1000:
                sal_from *= 1000
            if sal_to and sal_to < 1000:
                sal_to *= 1000
                
            return {'from': sal_from, 'to': sal_to, 'currency': 'RUR'}
        except:
            pass
    return None

def extract_job_title(text):
    lines = text.split('\n')
    
    for line in lines[:10]:
        line = line.strip()
        if line.startswith('#') or line.startswith('@') or len(line) < 5:
            continue
        if line.startswith('http'):
            continue
            
        cleaned = re.sub(r'[#@][\w]+', '', line).strip()
        cleaned = re.sub(r'^[\s\-\–\—\•\*:]+', '', cleaned).strip()
        
        if 5 < len(cleaned) < 80:
            return cleaned[:80]
    
    cleaned_text = re.sub(r'[#@][\w]+', '', text).strip()
    first_line = cleaned_text.split('\n')[0].strip()
    if 5 < len(first_line) < 80:
        return first_line
    
    return text[:60].replace('#', '').replace('@', '') + '...'

def is_job_posting(text):
    if not text or len(text) < 50:
        return False
    
    text_lower = text.lower()
    keyword_count = sum(1 for kw in JOB_KEYWORDS if kw in text_lower)
    
    return keyword_count >= 2

def is_remote(text):
    remote_keywords = ['remote', 'удалённ', 'удаленн', 'дистанц', 'из дома', 'home office']
    text_lower = text.lower()
    return any(kw in text_lower for kw in remote_keywords)

def extract_company(text):
    patterns = [
        r'компания[:\s]+([А-Яа-яA-Za-z0-9\s]+)',
        r'в\s+([A-Z][A-Za-z0-9]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            company = match.group(1).strip()
            if 3 < len(company) < 30:
                return company
    
    return 'Telegram'

async def parse_channel_web(session, channel):
    url = f"https://t.me/s/{channel}"
    
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch {channel}: {response.status}")
                return []
            
            html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        messages = soup.find_all('div', class_='tgme_widget_message_wrap')
        
        vacancies = []
        
        for msg in messages:
            text_div = msg.find('div', class_='tgme_widget_message_text')
            if not text_div:
                continue
            
            text = text_div.get_text(separator='\n', strip=True)
            
            if not is_job_posting(text):
                continue
            
            link_tag = msg.find('a', class_='tgme_widget_message_date')
            msg_url = link_tag['href'] if link_tag else url
            
            msg_id = msg_url.split('/')[-1] if msg_url else '0'
            
            vacancy = {
                'id': f"tg_{channel}_{msg_id}",
                'name': extract_job_title(text),
                'employer': {'name': extract_company(text)},
                'salary': extract_salary(text),
                'alternate_url': msg_url,
                'area': {'name': 'Remote' if is_remote(text) else 'Россия'},
                'source': 'telegram',
                'channel': f"@{channel}",
                'text_hash': text[:100],
                'full_text': text[:1000],
                'parsed_at': datetime.now().isoformat()
            }
            
            vacancies.append(vacancy)
        
        logger.info(f"Parsed {len(vacancies)} vacancies from @{channel}")
        return vacancies
        
    except Exception as e:
        logger.error(f"Error parsing {channel}: {e}")
        return []

async def parse_all_channels():
    logger.info("Starting web parser...")
    
    existing = load_vacancies()
    existing_hashes = set(v.get('text_hash', '')[:100] for v in existing)
    
    all_new_vacancies = []
    
    async with aiohttp.ClientSession(headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }) as session:
        for channel in CHANNELS:
            try:
                vacancies = await parse_channel_web(session, channel)
                
                for vac in vacancies:
                    if vac['text_hash'] not in existing_hashes:
                        all_new_vacancies.append(vac)
                        existing_hashes.add(vac['text_hash'])
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error with {channel}: {e}")
    
    combined = all_new_vacancies + existing
    combined = combined[:500]
    
    save_vacancies(combined)
    logger.info(f"Total: {len(all_new_vacancies)} new, {len(combined)} stored")

async def main():
    await parse_all_channels()
    logger.info("Parsing complete")

if __name__ == '__main__':
    asyncio.run(main())
