"""Common evidence boundaries for every text generation, including custom editorial calls."""
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def runtime():
    p=Path(__file__).resolve().parent.parent/'knowledge/honesty_policy.json'
    return json.loads(p.read_text(encoding='utf-8'))['runtime']

def apply(system):
    rule=runtime()
    return system if rule in system else rule+'\n\n'+system
