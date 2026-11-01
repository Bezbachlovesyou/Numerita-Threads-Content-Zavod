import asyncio
import unittest
from unittest.mock import patch

import httpx

from zavod import generator as G


class Fake:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def post(self, url, headers=None, json=None):
        self.calls.append(json)
        code, body = self.replies.pop(0)
        return httpx.Response(code, json=body, request=httpx.Request("POST", url))


class P402(unittest.TestCase):
    def _gen(self):
        g = G.Generator.__new__(G.Generator)
        g.api_key, g.model, g.system = "k", "m/x", "sys"

        async def noop(*a, **k): pass
        g._record_cost = noop
        return g

    def test_retries_after_402_and_shrinks_request(self):
        ok = (200, {"choices": [{"message": {"content": "готово"}, "finish_reason": "stop"}], "usage": {}})
        fake = Fake([(402, {"error": {"message": "You requested up to 4000 tokens, but can only afford 900"}}), ok])
        async def nosleep(*a): pass
        with patch("httpx.AsyncClient", fake), patch("asyncio.sleep", nosleep):
            out = asyncio.run(self._gen()._complete("sys", "p", max_tokens=4000))
        self.assertEqual(out, "готово")
        self.assertEqual(fake.calls[1]["max_tokens"], 880)

    def test_persistent_402_shows_real_reason(self):
        body = (402, {"error": {"message": "Key limit exceeded"}})
        fake = Fake([body, body, body])
        async def nosleep(*a): pass
        with patch("httpx.AsyncClient", fake), patch("asyncio.sleep", nosleep):
            with self.assertRaises(G.GenerationError) as cm:
                asyncio.run(self._gen()._complete("sys", "p"))
        self.assertIn("Key limit exceeded", str(cm.exception))
        self.assertEqual(len(fake.calls), 3)


if __name__ == "__main__":
    unittest.main()
