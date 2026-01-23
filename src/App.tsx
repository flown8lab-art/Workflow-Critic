import { useState } from 'react'
import { AlertTriangle, Shield, Zap, Brain, DollarSign, Clock, CheckCircle, XCircle, AlertCircle, ChevronDown, ChevronUp, Target, Workflow, Code, Database } from 'lucide-react'

interface Issue {
  severity: 'critical' | 'warning' | 'info'
  title: string
  description: string
  recommendation: string
}

interface Section {
  id: string
  title: string
  icon: React.ReactNode
  issues: Issue[]
  expanded: boolean
}

function App() {
  const [sections, setSections] = useState<Section[]>([
    {
      id: 'security',
      title: 'Безопасность',
      icon: <Shield className="w-5 h-5" />,
      expanded: true,
      issues: [
        {
          severity: 'critical',
          title: 'VK API токен захардкожен в workflow',
          description: 'Access token VK API (vk1.a._4FZgEpebv197wM7...) указан напрямую в параметрах HTTP Request. Это критическая уязвимость: токен виден всем, кто имеет доступ к workflow, и может быть скомпрометирован.',
          recommendation: 'Переместите токен в n8n Credentials (создайте Header Auth credential) или используйте переменные окружения через $env. Немедленно отзовите текущий токен и сгенерируйте новый.'
        },
        {
          severity: 'warning',
          title: 'OpenRouter API credentials видны в экспорте',
          description: 'ID credentials (U5jyQ3LOrGaTDwev) экспортируется вместе с workflow. Хотя сам ключ не виден, это создаёт trace для потенциальных атак.',
          recommendation: 'При публикации workflow удаляйте секции credentials или используйте плейсхолдеры.'
        },
        {
          severity: 'warning',
          title: 'Google Sheets OAuth credentials в экспорте',
          description: 'Аналогично, OAuth credentials для Google Sheets (Gfm53OWJPiDe8dUG) экспортируются с workflow.',
          recommendation: 'Создайте отдельный workflow template без привязки к конкретным credentials.'
        }
      ]
    },
    {
      id: 'architecture',
      title: 'Архитектура и логика',
      icon: <Workflow className="w-5 h-5" />,
      expanded: true,
      issues: [
        {
          severity: 'critical',
          title: 'Нет дедупликации обработанных статей',
          description: 'Workflow запускается каждые 3 часа и читает RSS. Одни и те же статьи будут обрабатываться повторно, создавая дубликаты в Google Sheets и тратя токены AI.',
          recommendation: 'Добавьте проверку через Google Sheets Lookup или используйте Redis/базу данных для хранения обработанных URL. Альтернатива: сравнивайте pubDate с последним запуском.'
        },
        {
          severity: 'warning',
          title: 'HTTP Request1 → example.com - мёртвый нод',
          description: 'Нод "HTTP Request1" делает запрос к https://example.com без какой-либо логики. Это выглядит как забытый тестовый нод или placeholder.',
          recommendation: 'Удалите этот нод или замените на реальную логику. Он только добавляет latency.'
        },
        {
          severity: 'warning',
          title: 'Edit Fields1 устанавливает неиспользуемые поля',
          description: 'Поля source="zen", purpose="find_business_pain", version="v1" устанавливаются, но нигде не используются в дальнейшем потоке.',
          recommendation: 'Удалите неиспользуемые поля или добавьте их в финальный output для трекинга.'
        },
        {
          severity: 'info',
          title: 'Отключённая ветка VK API',
          description: 'Нод "ID групп ->" и "HTTP Request" (VK API) существуют, но не подключены к основному потоку. Это незавершённая функциональность.',
          recommendation: 'Либо завершите интеграцию с VK, либо удалите эти ноды для чистоты workflow.'
        },
        {
          severity: 'info',
          title: 'Двойная фильтрация: regex + AI',
          description: 'Сначала статьи фильтруются regex по ключевым словам (If2), затем AI проверяет релевантность. Это избыточно, но экономит токены.',
          recommendation: 'Хороший подход! Можно оптимизировать regex, добавив негативные паттерны для отсечения явно нерелевантного контента.'
        }
      ]
    },
    {
      id: 'prompts',
      title: 'AI-промпты и модели',
      icon: <Brain className="w-5 h-5" />,
      expanded: true,
      issues: [
        {
          severity: 'warning',
          title: 'Промпт анализа смешивает system и user роли',
          description: 'В ноде "Анализ статей" основная инструкция в text (user), а контент статьи в systemMessage. Это инвертированная логика: обычно инструкции идут в system.',
          recommendation: 'Переместите инструкции в systemMessage, а данные статьи передавайте в text. Это даст более стабильные результаты.'
        },
        {
          severity: 'warning',
          title: 'JSON в промпте без structured output',
          description: 'Промпты требуют JSON-ответ, но используется обычный текстовый режим. Есть Code нод для парсинга, но он может падать на невалидном JSON.',
          recommendation: 'Используйте функцию Structured Output в LangChain-нодах или добавьте retry-логику в Code нод при ошибке парсинга.'
        },
        {
          severity: 'info',
          title: 'GPT-4o-mini через OpenRouter - хороший выбор',
          description: 'Модель gpt-4o-mini оптимальна для таких задач: достаточно умная для анализа, но экономичная по токенам.',
          recommendation: 'Можно экспериментировать с Claude 3 Haiku или Gemini Flash для сравнения cost/quality.'
        },
        {
          severity: 'warning',
          title: 'Промпт комментария может генерировать детектируемый AI-текст',
          description: 'Несмотря на инструкции "не звучать как ИИ", без few-shot примеров модель всё равно может выдавать шаблонные фразы.',
          recommendation: 'Добавьте 2-3 примера реальных комментариев в стиле, который вы хотите. Few-shot learning значительно улучшит результат.'
        }
      ]
    },
    {
      id: 'cost',
      title: 'Стоимость и эффективность',
      icon: <DollarSign className="w-5 h-5" />,
      expanded: true,
      issues: [
        {
          severity: 'warning',
          title: 'Потенциальный перерасход на дубликаты',
          description: 'Без дедупликации каждый запуск (8 раз в день) обрабатывает ~20-50 статей из RSS. При ~30% hit rate это 6-15 AI-вызовов × 2 (анализ + комментарий) = 12-30 вызовов. Повторы увеличивают это в 3-5 раз.',
          recommendation: 'С дедупликацией вы сократите расходы на 70-80%. Ориентировочно: $0.5-2/день без дедупликации vs $0.1-0.5/день с ней.'
        },
        {
          severity: 'info',
          title: 'Интервал 3 часа может быть избыточным',
          description: 'vc.ru публикует ~50-100 статей в день. Проверка каждые 3 часа (8 раз) избыточна для большинства use cases.',
          recommendation: 'Рассмотрите интервал 6-12 часов. Для срочного реагирования используйте webhook при появлении новых статей.'
        }
      ]
    },
    {
      id: 'reliability',
      title: 'Надёжность и error handling',
      icon: <AlertCircle className="w-5 h-5" />,
      expanded: true,
      issues: [
        {
          severity: 'critical',
          title: 'Нет обработки ошибок AI',
          description: 'Если OpenRouter вернёт ошибку (rate limit, timeout, invalid response), весь workflow упадёт. Code-ноды бросают Error без graceful handling.',
          recommendation: 'Добавьте Error Trigger workflow или используйте try-catch в Code нодах. Настройте retry policy в HTTP/AI нодах.'
        },
        {
          severity: 'warning',
          title: 'Нет уведомлений об ошибках',
          description: 'При падении workflow вы не узнаете об этом, пока не проверите вручную.',
          recommendation: 'Добавьте Error Trigger → Telegram/Email нод для алертинга. n8n поддерживает это из коробки.'
        },
        {
          severity: 'warning',
          title: 'Google Sheets как единственное хранилище',
          description: 'Google Sheets имеет лимиты на API calls и может быть недоступен. Нет backup или fallback.',
          recommendation: 'Рассмотрите добавление записи в Airtable или Notion как backup. Или используйте n8n internal database для промежуточного хранения.'
        }
      ]
    },
    {
      id: 'code',
      title: 'Качество кода',
      icon: <Code className="w-5 h-5" />,
      expanded: false,
      issues: [
        {
          severity: 'info',
          title: 'Дублирование Code нодов',
          description: 'Ноды "Code in JavaScript" и "Code in JavaScript1" содержат идентичный код для парсинга JSON.',
          recommendation: 'Создайте один переиспользуемый Code нод или вынесите логику в n8n Function Item.'
        },
        {
          severity: 'info',
          title: 'Regex фильтр может пропускать релевантное',
          description: 'Regex "бизнес|компан|выручк|..." использует stems без учёта морфологии. "Бизнесмен" пройдёт, а "предприниматель" нет.',
          recommendation: 'Расширьте regex или рассмотрите использование AI для первичной фильтрации с более дешёвой моделью.'
        }
      ]
    }
  ])

  const toggleSection = (id: string) => {
    setSections(prev => prev.map(s => 
      s.id === id ? { ...s, expanded: !s.expanded } : s
    ))
  }

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'critical': return <XCircle className="w-5 h-5 text-red-400" />
      case 'warning': return <AlertTriangle className="w-5 h-5 text-yellow-400" />
      default: return <CheckCircle className="w-5 h-5 text-blue-400" />
    }
  }

  const getSeverityBg = (severity: string) => {
    switch (severity) {
      case 'critical': return 'border-red-500/30 bg-red-500/5'
      case 'warning': return 'border-yellow-500/30 bg-yellow-500/5'
      default: return 'border-blue-500/30 bg-blue-500/5'
    }
  }

  const countIssues = () => {
    const counts = { critical: 0, warning: 0, info: 0 }
    sections.forEach(s => s.issues.forEach(i => counts[i.severity]++))
    return counts
  }

  const counts = countIssues()

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <header className="text-center mb-10">
          <h1 className="text-3xl md:text-4xl font-bold bg-gradient-to-r from-purple-400 via-pink-400 to-orange-400 bg-clip-text text-transparent mb-3">
            Критический анализ n8n Workflow
          </h1>
          <p className="text-gray-400 text-lg">Lead_vc.ru - B2B лидогенерация через vc.ru</p>
        </header>

        <div className="grid grid-cols-3 gap-4 mb-8">
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-red-400">{counts.critical}</div>
            <div className="text-sm text-gray-400">Критических</div>
          </div>
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-yellow-400">{counts.warning}</div>
            <div className="text-sm text-gray-400">Предупреждений</div>
          </div>
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-blue-400">{counts.info}</div>
            <div className="text-sm text-gray-400">Рекомендаций</div>
          </div>
        </div>

        <div className="bg-gradient-to-br from-purple-500/10 to-pink-500/10 border border-purple-500/20 rounded-xl p-6 mb-8">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Target className="w-5 h-5 text-purple-400" />
            Общая оценка workflow
          </h2>
          <p className="text-gray-300 mb-4">
            Workflow реализует интересную идею автоматической генерации B2B-комментариев на vc.ru. 
            Архитектура в целом логична: RSS → фильтрация → AI-анализ → генерация → сохранение.
          </p>
          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <h3 className="font-medium text-green-400 mb-2">Что хорошо:</h3>
              <ul className="text-sm text-gray-400 space-y-1">
                <li>• Двухуровневая фильтрация (regex + AI) экономит токены</li>
                <li>• Выбор GPT-4o-mini через OpenRouter оптимален</li>
                <li>• Структура промптов достаточно детальная</li>
                <li>• Google Sheets для ревью перед публикацией - правильно</li>
              </ul>
            </div>
            <div>
              <h3 className="font-medium text-red-400 mb-2">Что критично исправить:</h3>
              <ul className="text-sm text-gray-400 space-y-1">
                <li>• Убрать захардкоженный VK токен немедленно</li>
                <li>• Добавить дедупликацию обработанных статей</li>
                <li>• Настроить error handling и алертинг</li>
                <li>• Удалить мёртвые ноды (example.com, VK branch)</li>
              </ul>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          {sections.map(section => (
            <div key={section.id} className="bg-gray-800/50 border border-gray-700/50 rounded-xl overflow-hidden">
              <button
                onClick={() => toggleSection(section.id)}
                className="w-full p-4 flex items-center justify-between hover:bg-gray-700/30 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-purple-400">{section.icon}</span>
                  <span className="font-semibold">{section.title}</span>
                  <span className="text-sm text-gray-500">({section.issues.length})</span>
                </div>
                {section.expanded ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
              </button>
              
              {section.expanded && (
                <div className="p-4 pt-0 space-y-3">
                  {section.issues.map((issue, idx) => (
                    <div key={idx} className={`border rounded-lg p-4 ${getSeverityBg(issue.severity)}`}>
                      <div className="flex items-start gap-3">
                        {getSeverityIcon(issue.severity)}
                        <div className="flex-1">
                          <h4 className="font-medium mb-1">{issue.title}</h4>
                          <p className="text-sm text-gray-400 mb-3">{issue.description}</p>
                          <div className="bg-gray-900/50 rounded-lg p-3">
                            <p className="text-sm text-green-400">
                              <span className="font-medium">Рекомендация:</span> {issue.recommendation}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="mt-8 bg-gray-800/30 border border-gray-700/50 rounded-xl p-6">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Zap className="w-5 h-5 text-yellow-400" />
            Приоритетный план действий
          </h2>
          <ol className="space-y-3 text-gray-300">
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-red-500/20 text-red-400 rounded-full flex items-center justify-center text-sm font-bold">1</span>
              <span><strong>Сейчас:</strong> Отзовите VK токен и перенесите в n8n Credentials</span>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-red-500/20 text-red-400 rounded-full flex items-center justify-center text-sm font-bold">2</span>
              <span><strong>Сегодня:</strong> Добавьте дедупликацию через Google Sheets Lookup по URL</span>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-yellow-500/20 text-yellow-400 rounded-full flex items-center justify-center text-sm font-bold">3</span>
              <span><strong>На неделе:</strong> Настройте Error Trigger с уведомлениями в Telegram</span>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-yellow-500/20 text-yellow-400 rounded-full flex items-center justify-center text-sm font-bold">4</span>
              <span><strong>На неделе:</strong> Переработайте промпты: system/user roles, добавьте few-shot примеры</span>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 w-6 h-6 bg-blue-500/20 text-blue-400 rounded-full flex items-center justify-center text-sm font-bold">5</span>
              <span><strong>Позже:</strong> Удалите мёртвые ноды, оптимизируйте интервал запуска</span>
            </li>
          </ol>
        </div>

        <footer className="mt-8 text-center text-gray-500 text-sm">
          Анализ выполнен на основе экспортированного JSON workflow Lead_vc.ru
        </footer>
      </div>
    </div>
  )
}

export default App
