"""Recognisable number portraits, with explicit tradition and no predictions."""
import json
import re
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def data():
    return json.loads((Path(__file__).resolve().parent.parent/'knowledge/formats/number_mirror.json').read_text())

def excerpt(topic):
    d = data()
    if re.search(r'добр|жесток|слабост|kindness|weakness', topic, re.I):
        return {'kindness_and_strength': d['kindness_and_strength']}
    if not re.search(r'number_mirror|любовь.*тепло.*творчеств', topic, re.I):
        return None
    digits = {int(n) for n in re.findall(r'(?<!\d)([1-9])(?!\d)', topic)}
    return {'rule': d['rule'], 'portraits': {k:v for k,v in d['portraits'].items()
            if not digits or int(k) in digits}, 'profile': d['profile']}
