import pytest
import main

@pytest.mark.asyncio
async def test_ai_call_disabled_returns_warning(monkeypatch):
    monkeypatch.setattr(main, "AI_ENABLED", False)
    monkeypatch.setattr(main, "ai_client", None)
    out = await main.ai_call("test")
    assert "unavailable" in out.lower()

@pytest.mark.asyncio
async def test_get_ai_guidance_uses_ai_call(monkeypatch):
    async def fake_ai_call(prompt, max_retries=3, timeout=12.0):
        return "Keep\nSafe"
    monkeypatch.setattr(main, "ai_call", fake_ai_call)
    out = await main.get_ai_guidance("https://example.com")
    assert "Keep" in out
    assert "Safe" in out
