# Менеджер подписок

Telegram-бот для учёта подписок и напоминаний о списаниях.

## Возможности

- Добавление подписок через диалог `/add`
- Список активных с кнопками **Оплатил** / **Отложить** / **Отменить**
- Ежедневные напоминания в 10:00 UTC за N дней до списания
- Локальное хранение в SQLite

## Стек

Python 3.11+, aiogram v3, aiosqlite, APScheduler, python-dotenv.

## Установка

```bash
cd telegram-subscription-manager
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Заполни `.env` и запусти:

```bash
python main.py
```

Логи пишутся в `bot.log`.

## Ключи

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather): `/newbot` → скопируй токен в `.env` |
| `REMIND_DAYS_BEFORE` | За сколько дней напоминать (по умолчанию `2`) |

## Команды

| Команда | Описание |
|---|---|
| `/start` | Регистрация и краткая справка |
| `/add` | Диалог: название → дата (ДД.ММ.ГГГГ) → сумма → валюта |
| `/list` | Активные подписки + кнопки действий |
| `/cancel <id>` | Пометить подписку как `cancelled` |

### Кнопки

- **Оплатил** — дата списания +1 месяц
- **Отложить** — +3 дня
- **Отменить** — `status=cancelled`

## Структура

```
main.py
database.py
scheduler.py
handlers/subscriptions.py
requirements.txt
.env.example
```
