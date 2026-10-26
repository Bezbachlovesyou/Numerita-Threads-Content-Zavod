"""Солнечные портреты: редакционные образы по проверенной символике KB."""
import json
import re
from functools import lru_cache
from pathlib import Path
from .cards import Card

PATH = Path(__file__).resolve().parent.parent / 'knowledge' / 'formats' / 'solar_portraits.json'
TOPIC = re.compile(r'one_portrait|one_scene|солнечн\w*\s+(?:образ|архетип)|(?:женщин\w*|мужчин\w*)[ -]единичк', re.I)


@lru_cache(maxsize=1)
def data():
    return json.loads(PATH.read_text(encoding='utf-8'))


def choose(rng):
    return rng.choice(data()['decks'])


def cards(deck, palette):
    return [Card(text, number='1', label=deck['label'] if index == 0 else 'СОЛНЦЕ', cta='reply', cta_text=button,
                 palette=palette, dates='1 · 10 · 19 · 28') for index, (text, button) in enumerate(deck['slides'])]


def topic(deck):
    return ('\nСолнечный портрет one_portrait, вариант ' + deck['id'] + '. Все карточки про число 1 '
            '(родились 1, 10, 19, 28), независимо от других подстановок. '
            'Подпись должна соответствовать именно этому сюжету, без нового обещания разбора.\n'
            + '\n'.join(text for text, _ in deck['slides'])
            + '\nПример подписи: ' + deck['caption'])


def excerpt(topic_text):
    if not TOPIC.search(topic_text):
        return None
    return {'status': data()['number']['boundary'], 'number': data()['number'],
            'voice': 'Литературная теплота, поддержка и юмор о гордыне или контроле, не о боли человека. '
                     'Женщина не обязана руководить, мужчина не обязан скрывать уязвимость. '
                     'Не смешивать число души и число судьбы; Таро — отдельная символика, не расчёт даты.'}
