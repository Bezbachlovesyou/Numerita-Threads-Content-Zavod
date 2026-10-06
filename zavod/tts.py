"""Озвучка постов бесплатными голосами Microsoft Edge (edge-tts)."""

import edge_tts


async def synthesize(text: str, voice: str, rate: str) -> bytes:
    """Возвращает MP3 с озвученным текстом. rate: "+100%" — в 2 раза быстрее."""
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)
