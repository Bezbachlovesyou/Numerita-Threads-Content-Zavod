"""Six questions from the reference; no fabricated planetary-strength calculation."""
import json
import re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def data():
    return json.loads((Path(__file__).resolve().parent.parent/'knowledge/formats/planet_resources.json').read_text())

def excerpt(topic):
    if not re.search(r'planet_resources|сильн\w* планет|планет\w* ресурс|тем\w* планет',topic,re.I):
        return None
    d = data()
    return {'rule':d['rule'],'items':d['items'],'posts':d['posts'],
            'premium':'Персональная выдача в основной Нумерите ещё не выпущена. Не обещать её доступность.'}
