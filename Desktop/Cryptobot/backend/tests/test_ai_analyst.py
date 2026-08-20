"""DeepSeek analyst (Variant A): commentary only, fails open."""

import pytest

from app.services.ai import analyst


class _FakeCompletions:
    def __init__(self, text="Аналитика: сетап у зоны объёма."):
        self._text = text

    async def create(self, **kwargs):
        class _Choice:
            message = type("Msg", (), {"content": self._text})()
        class _Resp:
            choices = [_Choice()]
        return _Resp()


class _FakeChat:
    def __init__(self, text):
        self.completions = _FakeCompletions(text)


class _FakeClient:
    def __init__(self, text="ok"):
        self.chat = _FakeChat(text)


@pytest.mark.asyncio
async def test_returns_commentary(monkeypatch):
    monkeypatch.setattr(analyst.settings, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(analyst, "AsyncOpenAI", lambda **kw: _FakeClient("Сетап сильный."))
    text = await analyst.analyze_signal(
        symbol="BTC/USDT", direction="BUY", entry=100.0, stop=98.0,
        tps=[104.0, 108.0], confidence=60, metadata={"reasons": ["Тренд 1h"]},
        df1h=None, df5m=None,
    )
    assert text == "Сетап сильный."


@pytest.mark.asyncio
async def test_skips_without_api_key(monkeypatch):
    monkeypatch.setattr(analyst.settings, "DEEPSEEK_API_KEY", "")
    text = await analyst.analyze_signal(
        symbol="BTC/USDT", direction="BUY", entry=100.0, stop=98.0,
        tps=[104.0], confidence=60, metadata={},
    )
    assert text == ""


@pytest.mark.asyncio
async def test_fails_open_on_api_error(monkeypatch):
    monkeypatch.setattr(analyst.settings, "DEEPSEEK_API_KEY", "sk-test")

    class _Broken:
        chat = None

    monkeypatch.setattr(analyst, "AsyncOpenAI", lambda **kw: _Broken())
    text = await analyst.analyze_signal(
        symbol="BTC/USDT", direction="BUY", entry=100.0, stop=98.0,
        tps=[104.0], confidence=60, metadata={},
    )
    assert text == ""
