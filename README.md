# Numerita Threads Content Zavod

Контент-завод для Threads, которым управляют через Telegram-бота.

## Как это работает

1. Вы пишете боту тему поста (или `/new <тема>`).
2. Claude пишет пост в голосе бренда (правила в `prompts/brand_voice.md`).
3. Бот присылает черновик с кнопками и голосовое сообщение, где пост зачитывает женский голос в 2 раза быстрее обычного.
4. Кнопки под черновиком:
   - ✅ Опубликовать — сразу в Threads;
   - 🕒 Через час / Завтра 10:00 — в расписание;
   - 🔄 Переписать — новый вариант на ту же тему;
   - 🔊 Озвучить — прислать голосовое ещё раз;
   - 🗑 Удалить.
5. `/queue` показывает черновики, запланированные посты и посты с ошибками.

Ботом могут пользоваться только админы из `ADMIN_IDS`.

## Запуск

Нужен Python 3.11 или новее.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполните ключи
python -m zavod
```

### Что вписать в `.env`

| Переменная | Где взять |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → `/newbot` |
| `ADMIN_IDS` | Ваш Telegram ID, например через @userinfobot |
| `ANTHROPIC_API_KEY` | https://platform.claude.com → API Keys |
| `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN` | Приложение Meta с Threads API. Пока они пустые, посты только сохраняются, а при публикации бот пишет, что Threads не подключён |
| `TTS_VOICE`, `TTS_RATE`, `TTS_AUTO` | Голос, скорость и автоозвучка. По умолчанию женский голос Светлана, `+100%` (×2), автоозвучка включена |

## Структура

```
zavod/
  __main__.py     запуск бота и планировщика
  bot.py          команды, кнопки, планировщик публикаций
  generator.py    генерация постов через Claude API
  threads_api.py  публикация в Threads
  tts.py          озвучка (edge-tts)
  storage.py      SQLite: черновики, расписание, статусы
  config.py       настройки из .env
prompts/
  brand_voice.md  голос бренда — отредактируйте под Numerita
```
