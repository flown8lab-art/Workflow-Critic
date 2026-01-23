# n8n Workflow Critic

## Overview
Веб-приложение для критического анализа n8n workflow. Анализирует экспортированный JSON workflow и предоставляет детальную критику по категориям: безопасность, архитектура, AI-промпты, стоимость, надёжность.

## Current State
Полнофункциональное приложение с анализом workflow Lead_vc.ru для B2B лидогенерации через vc.ru.

## Tech Stack
- React 19 + TypeScript
- Vite (dev server on port 5000)
- Lucide React (icons)
- Tailwind-like custom CSS

## Project Structure
```
├── src/
│   ├── App.tsx        # Main component with workflow analysis
│   ├── main.tsx       # React entry point
│   └── index.css      # Global styles
├── index.html         # HTML template
├── vite.config.ts     # Vite configuration
├── tsconfig.json      # TypeScript configuration
└── attached_assets/   # Original workflow JSON
```

## Running the Project
```bash
npm run dev
```

## Key Features
- Анализ 6 категорий: безопасность, архитектура, AI-промпты, стоимость, надёжность, код
- Severity levels: critical, warning, info
- Приоритетный план действий
- Интерактивные секции

## Recent Changes
- Initial creation (2026-01-23): Full workflow analysis application
