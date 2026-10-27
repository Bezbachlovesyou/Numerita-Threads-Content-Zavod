"""Owner's reversible text-only Threads experiment, including old local drafts."""
import os
import re
import json

def enabled():
    return os.getenv('THREADS_TEXT_ONLY','1').strip().lower() not in ('0','off','no')

def grid_enabled():
    return os.getenv('THREADS_GRID_EXCEPTION','1').strip().lower() not in ('0','off','no')

def grid_post(post):
    if not (enabled() and grid_enabled()) or getattr(post,'rubric',None) != 'grid':
        return False
    try:
        rows = json.loads(post.card)['grid']['rows']
        return len(rows)==14 and all(isinstance(row,str) and re.fullmatch(r'[0-9]{12}',row) for row in rows)
    except (ValueError,TypeError,KeyError,AttributeError):
        return False

GRID_MARKER = '[FORMAT:number_grid]'
GRID_STYLE = ('Исключение владельца: одна картинка — матрица-сетка цифр. '
              'Напиши короткую игровую подпись на 1–3 строки: какие три сочетания заметили первыми? '
              'Можно мягко пошутить. Не выдавай выбор глаз за диагноз или предсказание. '
              'Не проси листать карусель, не обещай настоящих кнопок и не перечисляй скрытые ответы.')

STYLE = ('ТЕКСТОВЫЙ ЭКСПЕРИМЕНТ: только самостоятельный текст, без картинок, видео, '
         'каруселей, подписей к карточкам и воображаемых кнопок. Цель 120–280 знаков, максимум 450. '
         'Одна бытовая сцена, наблюдение или мини-диалог, узнавание и мягкая ирония. '
         'Меньше правильных советов, терапевтических лозунгов и назиданий. Не своди каждый пост к '
         'границам, помощи и заботе о себе. Не обязан заканчивать вопросом. '
         'Нумерологические персонажи — явно сценка/шутка, не диагноз каждому по дате. '
         'Не выдумывай клиентов, личный опыт, события, доходы и прогнозы. '
         'Шути над ситуацией, не унижай человека, возраст или пол. '
         'Если задание про картинку — преврати саму идею в понятный текст, не ссылайся на изображение.')

VISUAL_KEYS = {'grid','carousel','eight_growth','one_portrait','one_scene','video'}

def allowed(rubric):
    if rubric.key == 'grid': return grid_enabled()
    return rubric.key not in VISUAL_KEYS and not re.search(r'на картинке|листай слайды|найди на изображении',rubric.text,re.I)

def needs_visual(text):
    return bool(re.search(r'на (?:этой )?картинке|листай|свайп|нажми.*кнопк|включи звук|смотри видео',text,re.I))

SAMPLES = [
    '6, 15, 24 в нумерологическом ситкоме:\n— Хочу романтический сюрприз.\n— Что для этого сделала?\n— Всё организовала. Осталось удивиться.',
    'Служба поддержки Венеры:\n— Мне любовь, красоту и творчество.\n— Вам всё сразу?\n— Да. И чтобы никто не трогал мои красивые чашки.',
    'Числа на созвоне. Нумерологический скетч:\n1: Я предлагаю.\n3: Я объясню.\n5: Я уже вышел.\n8: А протокол кто подпишет?',
    'Нумерологический суд:\n— Шестёрка обвиняется в покупке пятой свечи.\n— Возражаю. Это другой оттенок уюта.',
    '1, 10, 19, 28 в нумерологическом ситкоме:\n— Я всё решил.\n— Мы ещё не начали спорить.\n— Именно.',
    'Шуточный отзыв на нумерологическую шестёрку:\nПлюсы: красиво, тепло, вкусно.\nМинусы: теперь пледу нужен плед.',
]

async def seed(db):
    if not enabled(): return
    for i,text in enumerate(SAMPLES):
        topic = f'text-only-experiment-v1:{i}'
        if await db.claim_slot(topic):
            ident = await db.add_draft(topic,text,'text_seed')
            await db.queue_post(ident)

async def next_seed(db):
    rows = await db._rows("SELECT id FROM posts WHERE status = 'queued' AND rubric = 'text_seed' ORDER BY id LIMIT 1")
    return await db.get(rows[0]['id']) if rows else None
