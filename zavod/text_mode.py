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
GRID_STYLE = ('Исключение владельца: одна картинка — матрица чисел. '
              'Называй её «матрица» или «матрица чисел», слово «сетка» не используй. '
              'Напиши короткую игровую подпись на 1–3 строки: какие три сочетания заметили первыми? '
              'Можно мягко пошутить. Не выдавай выбор глаз за диагноз или предсказание. '
              'Не проси листать карусель, не обещай настоящих кнопок и не перечисляй скрытые ответы.')

STYLE = ('ТЕКСТОВЫЙ ЭКСПЕРИМЕНТ: только самостоятельный текст, без картинок, видео, '
         'каруселей, подписей к карточкам и воображаемых кнопок. Цель 120–280 знаков, максимум 450. '
         'Одна бытовая сцена, наблюдение или мини-диалог, узнавание и острый сатирический панч. Советский плакат словами, абсурд канцелярита, поп-артовое сопоставление бытового и торжественного.  '
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
    'Нумерологический скетч. 1, 10, 19, 28.\n— Мы всё решили вместе.\n— А меня почему не спросили?\n— Ты входишь в понятие «мы». Протокол утверждён.',
    'Скетч про девятку: 9, 18, 27.\nПомог безвозмездно.\nСчёт не выставил.\nВ голове открыл отдел взыскания благодарности.',
    '8, 17, 26. Сценка «Бывший вернулся».\n— Давай начнём с чистого листа.\n— Сначала закроем задолженность по обещаниям.\nЛюбовь любовью, акт сверки по расписанию.',
    'Протокол проверки бизнес-идеи:\nДрузья: «Гениально! Я бы купил!»\nКнопка оплаты: тишина.\nКомиссия постановила: аплодисменты в кассу не принимаются.',
    'Плакат из нумерологического скетча. 6, 15, 24:\nПЯТИЛЕТКУ УЮТА — ЗА ОДИН ВЕЧЕР!\nКуплены плед, свечи и чашка.\nНа оплату коммуналки средств не предусмотрено.',
    'Скетч про семёрку: 7, 16, 25.\n— Почему не отвечаешь?\n— Ищу смысл.\n— В моём «привет»?\n— А зачем ты его именно сегодня написал?',
    'Нумерологическая сценка. 2, 11, 20, 29:\n— Я не обиделась.\n— Тогда зачем протокол на 14 страниц?\n— Это краткое содержание.',
]

async def seed(db):
    if not enabled(): return
    # Preserve old unpublished samples as drafts; replace their queue with the owner’s sharper batch.
    await db._execute("UPDATE posts SET status = 'draft' WHERE rubric = 'text_seed' AND status = 'queued' AND topic LIKE 'text-only-experiment-v1:%'")
    for i,text in enumerate(SAMPLES):
        topic = f'text-only-satire-v2:{i}'
        if await db.claim_slot(topic):
            ident = await db.add_draft(topic,text,'text_seed')
            await db.queue_post(ident)

# Слово владельца 28.10.2026: признать, что несколько дней отвечал шаблонный код, извиниться и позвать спрашивать.
APOLOGY = ("Признаюсь: последние дни я отвечала вам как автоответчик ЖЭКа.\n"
           "Хотели сэкономить на нейросети — часть ответов собирал программный код. Числа он считал верно, а людей "
           "не слышал: вы делились датой, а получали шаблон «Какое красивое число!».\n"
           "Простите. Сбой найден и устранён — снова отвечает живая нейросеть.\n"
           "Проверьте меня: задайте в комментариях вопрос, на который я раньше ответила глупо ✨")


async def seed_apology(db):
    if await db.claim_slot("apology-code-replies-2026-10-28"):
        await db.queue_post(await db.add_draft("apology-code-replies-2026-10-28", APOLOGY, "text_seed"))


async def next_seed(db):
    rows = await db._rows("SELECT id FROM posts WHERE status = 'queued' AND rubric = 'text_seed' "
                          "ORDER BY CASE WHEN topic LIKE 'apology-%' THEN 0 ELSE 1 END, id LIMIT 1")
    return await db.get(rows[0]['id']) if rows else None
