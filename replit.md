# HH Resume Helper Bot

## Overview
Telegram-бот для автоматизации поиска работы на hh.ru. Анализирует резюме, ищет вакансии с фильтрами, генерирует сопроводительные письма и адаптирует резюме под конкретные позиции.

## Current State
Полнофункциональный Telegram-бот с пошаговым интерфейсом.

## Tech Stack
- Python 3.11 + python-telegram-bot
- aiohttp для асинхронных HTTP-запросов
- OpenRouter API (GPT-4o-mini) для генерации текстов
- hh.ru API для поиска вакансий
- PyPDF2 + python-docx для парсинга резюме

## Project Structure
```
├── bot/
│   └── main.py         # Telegram bot (ConversationHandler)
├── src/                # Legacy n8n workflow analyzer (inactive)
├── attached_assets/    # Original workflow JSON files
└── pyproject.toml      # Python dependencies
```

## Running the Bot
Workflow "Telegram Bot" runs: `python bot/main.py`

## Bot Features
1. **Пошаговый флоу**: START → RESUME → PREFERENCES → SEARCH → VACANCY
2. **Парсинг резюме**: PDF, Word (.docx), TXT, текст
3. **Фильтры вакансий**: последние 2 недели, зарплата, удалёнка, опыт
4. **AI-генерация**: сопроводительные письма и рекомендации по резюме
5. **hh.ru API**: поиск с параметрами period=14, schedule, salary, experience

## Environment Variables (Secrets)
- TELEGRAM_BOT_TOKEN
- OPENROUTER_API_KEY
- SESSION_SECRET

## Recent Changes
- 2026-02-04: Fixed conversation loop, added step-by-step guidance
- 2026-02-04: Added PDF/Word resume parsing (PyPDF2, python-docx)
- 2026-02-04: Added vacancy filters (2 weeks, salary, remote)
- 2026-02-04: Fixed hh.ru User-Agent blacklist issue
- 2026-02-04: Switched to aiohttp for async HTTP
