# ТЗ: ICP Qualifier — Полный пайплайн
### Финтех квалификация + анализ сайта

---

## Что делает скрипт

1. Читает CSV выгрузку из Apollo.io
2. Для каждой компании определяет — реальный ли это B2B финтех (Шаг 1)
3. Для прошедших верификацию — анализирует сайт через Jina AI + Claude (Шаг 2)
4. Сохраняет всё в один итоговый CSV

---

## Стек

- Python 3.11+
- `anthropic` — Claude API
- `requests` — запросы к Jina AI
- `pandas` — работа с CSV
- `python-dotenv` — переменные окружения

```
pip install anthropic requests pandas python-dotenv
```

---

## Структура проекта

```
/icp-qualifier
  main.py           # точка входа, запускает шаги последовательно
  step1_verify.py   # верификация: это финтех?
  step2_analyze.py  # анализ сайта через Jina + Claude
  prompts.py        # все промпты отдельным файлом
  config.py         # настройки
  utils.py          # retry, логирование, хелперы
  .env              # API ключи
  input.csv         # входной файл (выгрузка Apollo)
  output.csv        # итоговый файл (пишется по ходу)
  requirements.txt
```

---

## .env

```
ANTHROPIC_API_KEY=sk-ant-...
JINA_API_KEY=jina_...
```

---

## config.py

```python
MODEL = "claude-haiku-3-5-20251001"
INPUT_FILE = "input.csv"
OUTPUT_FILE = "output.csv"

STEP1_DELAY = 0.5       # сек между запросами к Claude на шаге 1
STEP2_JINA_DELAY = 1.0  # сек между запросами к Jina
STEP2_CLAUDE_DELAY = 0.5

MAX_RETRIES = 3
RETRY_WAIT = 10         # сек при 429 ошибке

JINA_TIMEOUT = 15       # сек таймаут на получение сайта
JINA_MIN_LENGTH = 100   # минимум символов чтобы считать ответ валидным
PAGE_TEXT_LIMIT = 8000  # обрезаем текст страницы до этого лимита
```

---

## Входной файл

`input.csv` — стандартная выгрузка из Apollo.io

Используемые колонки:
| Колонка | Описание |
|---|---|
| `Company Name` | Название |
| `Company Description` | Описание из Apollo |
| `Website` | URL сайта |
| `Industry` | Индустрия |
| `Keywords` | Ключевые слова |

Все остальные колонки Apollo — переносятся в output без изменений.

---

## ШАГ 1 — Верификация: это B2B финтех?

### Логика

Для каждой компании формируем промпт → отправляем в Claude → парсим JSON ответ → пишем результат в output.csv построчно (не в конце, а сразу).

### Промпт (prompts.py → STEP1_PROMPT)

```
You are a B2B fintech analyst. Determine whether a company belongs to a relevant fintech niche.

RELEVANT niches (must match at least one):
- B2B Payments / Payment infrastructure
- Cross-border payments / FX / Multi-currency
- Treasury management / Cash flow SaaS
- Neobank (B2B focused)
- Stablecoin / Crypto rails for B2B
- Payment orchestration / Acquiring

NOT relevant — reject these even if they call themselves fintech:
- Personal finance / consumer apps
- Insurance / Insurtech
- Accounting / Bookkeeping software
- Lending / Credit scoring
- Wealth management / Investment platforms
- HR / Payroll tools

---

Company data:
Name: {company_name}
Industry (from Apollo): {industry}
Description: {description}
Keywords: {keywords}

---

Answer in JSON only, no markdown, no text outside JSON:
{{
  "is_relevant": true or false,
  "niche": "detected niche name or null",
  "confidence": "high" or "medium" or "low",
  "reason": "one sentence max"
}}
```

### Роутинг по результату

| Условие | icp_status |
|---|---|
| `is_relevant: true` + `confidence: high` | `qualified` |
| `is_relevant: true` + `confidence: medium` | `review_needed` |
| `is_relevant: false` | `rejected` |
| Любой `confidence: low` | `review_needed` |
| Ошибка API / невалидный JSON | `error` |

### Новые колонки после Шага 1

| Колонка | Описание |
|---|---|
| `icp_status` | `qualified` / `review_needed` / `rejected` / `error` |
| `icp_niche` | Определённая ниша или null |
| `icp_confidence` | high / medium / low |
| `icp_reason` | Объяснение (1 предложение) |
| `step1_at` | Timestamp обработки |

---

## ШАГ 2 — Анализ сайта

Запускается только для строк где `icp_status == "qualified"` или `"review_needed"`.

### 2.1 Получить текст сайта через Jina AI

```python
url = f"https://r.jina.ai/{website}"
headers = {"Authorization": f"Bearer {JINA_API_KEY}"}
response = requests.get(url, headers=headers, timeout=JINA_TIMEOUT)
page_text = response.text[:PAGE_TEXT_LIMIT]
```

Jina сам рендерит страницу включая JS, обходит базовые защиты, возвращает чистый текст. Никакого Selenium, никакого парсинга HTML.

**Обработка ошибок Jina:**
- Timeout → `site_status = "unreachable"`
- HTTP 4xx / 5xx → `site_status = "unreachable"`
- Ответ короче `JINA_MIN_LENGTH` символов → `site_status = "unreachable"`
- При `unreachable` — пропускаем Claude, колонки анализа оставляем пустыми

### 2.2 Определить tech stack

Без внешних API — ищем паттерны в тексте и URL который вернул Jina:

```python
def detect_stack(page_text: str, website: str) -> str:
    text_lower = page_text.lower()
    if "wp-content" in text_lower or "wordpress" in text_lower:
        return "WordPress"
    if "webflow" in text_lower or ".webflow.io" in website:
        return "Webflow"
    if "framer.com" in text_lower or "framerusercontent" in text_lower:
        return "Framer"
    if "ghost.io" in text_lower:
        return "Ghost"
    if "squarespace" in text_lower:
        return "Squarespace"
    return "custom / unknown"
```

### 2.3 Анализ через Claude

**Промпт (prompts.py → STEP2_PROMPT):**

```
You are an expert B2B fintech website analyst at a web design agency.
We build high-converting websites for B2B fintech companies.
Our ideal client has a website that lags behind their product quality or investment stage.

Company: {company_name}
Niche: {icp_niche}
Tech stack: {tech_stack}

Homepage content:
---
{page_text}
---

Evaluate the website on 3 criteria. Be specific — reference actual content you saw, not generic observations.

1. PRODUCT CLARITY
Does the homepage clearly explain what the product actually does?
Bad signs: vague claims ("powerful platform", "seamless experience"), no concrete use cases, no screenshots or product descriptions.
Good signs: specific workflows explained, concrete customer outcomes, product screenshots described.
Score 1-5. (1 = very abstract, 5 = crystal clear)

2. CTA QUALITY
Is there a clear, specific path to demo/trial/contact?
Bad signs: generic "Contact us", buried buttons, no demo offer.
Good signs: "Book a demo", "Start free trial", "Talk to sales" — prominent and specific.
Score 1-5. (1 = no CTA or very weak, 5 = strong and prominent)

3. TRUST & CREDIBILITY
For a fintech company talking to enterprise buyers — does the site feel credible?
Bad signs: no compliance mentions, no client logos, no case studies, feels like a startup landing page.
Good signs: SOC2/PCI/ISO mentioned, recognizable client logos, security messaging, social proof.
Score 1-5. (1 = untrustworthy for fintech, 5 = enterprise-ready)

---

Answer in JSON only, no markdown:
{{
  "product_clarity_score": number,
  "product_clarity_note": "specific observation from the actual content",
  "cta_score": number,
  "cta_note": "specific observation from the actual content",
  "trust_score": number,
  "trust_note": "specific observation from the actual content",
  "overall_score": number (average of 3 scores, 1 decimal),
  "is_hot_prospect": true or false,
  "prospect_reason": "1-2 sentences: concrete reason why this company is or isn't worth outreach"
}}
```

**Правило `is_hot_prospect`:**
- `overall_score <= 2.5` → почти всегда `true`
- `overall_score >= 4.0` → почти всегда `false`
- `tech_stack == "WordPress"` → весомый сигнал в сторону `true` (боль с обновлениями)
- Финальное решение за Claude на основе всего контекста

### Новые колонки после Шага 2

| Колонка | Описание |
|---|---|
| `site_status` | `analyzed` / `unreachable` |
| `tech_stack` | WordPress / Webflow / Framer / custom / unknown |
| `product_clarity_score` | 1–5 |
| `product_clarity_note` | Наблюдение Claude |
| `cta_score` | 1–5 |
| `cta_note` | Наблюдение Claude |
| `trust_score` | 1–5 |
| `trust_note` | Наблюдение Claude |
| `overall_score` | Среднее (1–5) |
| `is_hot_prospect` | true / false |
| `prospect_reason` | Итоговый вывод Claude |
| `step2_at` | Timestamp |

---

## Докачка (важно)

Скрипт должен безопасно прерываться и перезапускаться в любой момент.

**Шаг 1:** если у строки уже заполнен `icp_status` — пропускать.
**Шаг 2:** если у строки уже заполнен `site_status` — пропускать.

Реализация: при старте читаем существующий `output.csv` (если есть), индексируем по `Company Name`, при обработке проверяем наличие значения.

---

## Логирование в консоль

```
=== STEP 1: Fintech Verification ===
[001/1000] Payoneer         → qualified ✅ (high) — B2B Payments
[002/1000] SomeInsurtech    → rejected  ❌ — Insurance, not relevant
[003/1000] ClearBank        → qualified ✅ (high) — Neobank B2B
[004/1000] WeirdFinco       → review    🔍 (low)  — unclear from description

=== STEP 2: Website Analysis ===
[001/623] Payoneer    → WordPress | score: 2.3 | HOT PROSPECT 🔥
[002/623] ClearBank   → custom    | score: 4.1 | not prospect  —
[003/623] NovaPay     → unreachable ⚠️

=== FINAL SUMMARY ===
Step 1:  qualified=623 | review=89 | rejected=261 | errors=27
Step 2:  hot_prospects=156 | not_prospects=467 | unreachable=89
Output saved to: output.csv
```

---

## Обработка ошибок (utils.py)

```python
def call_claude_with_retry(client, prompt, config):
    for attempt in range(config.MAX_RETRIES):
        try:
            response = client.messages.create(...)
            return parse_json_response(response)
        except RateLimitError:
            time.sleep(config.RETRY_WAIT)
        except Exception as e:
            if attempt == config.MAX_RETRIES - 1:
                return None  # не падаем, возвращаем None

def parse_json_response(response) -> dict | None:
    try:
        text = response.content[0].text.strip()
        return json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return None  # невалидный JSON → статус error, продолжаем
```

---

## Запуск

```bash
# установка
pip install -r requirements.txt

# добавить ключи в .env
ANTHROPIC_API_KEY=sk-ant-...
JINA_API_KEY=jina_...

# запуск полного пайплайна
python main.py

# или отдельно по шагам
python main.py --step 1
python main.py --step 2
```

---

## Примерная стоимость на 1000 компаний

| Статья | Стоимость |
|---|---|
| Claude Haiku — Шаг 1 (1000 запросов) | ~$0.10 |
| Jina AI — Шаг 2 (~700 сайтов) | ~$0 (free tier) |
| Claude Haiku — Шаг 2 (~700 запросов) | ~$0.40 |
| **Итого в день** | **~$0.50** |
| **Итого в месяц (22 раб. дня)** | **~$11** |

---

## Ожидаемая воронка на 1000 компаний

```
1000  входящих из Apollo
 623  прошли верификацию финтех (Шаг 1)
 156  горячих лидов после анализа сайта (Шаг 2)
  ~15  минут ручного review финального списка
```
