import asyncio
import pytest
import main

@pytest.mark.asyncio
async def test_pendinglinks_rate_limit(monkeypatch):
    cog = main.LinkManagerCog(bot=None)
    cog.rate_limiter.register = lambda uid, key: None
    cog.rate_limiter.is_limited = lambda uid, key, cooldown: True
    cog.rate_limiter.get_remaining = lambda uid, key, cooldown: 1.0
    sent = {}
    class DummyCtx:
        author = type("A", (), {"id": 1, "mention": "@u"})
        async def send(self, msg, delete_after=None): sent["msg"] = msg
    await cog.pendinglinks(DummyCtx())
    assert "please wait" in sent["msg"]

@pytest.mark.asyncio
async def test_assign_category_happy(monkeypatch):
    cog = main.LinkManagerCog(bot=None)
    cog.links_to_categorize[1] = {"link": "https://x.com", "message": type("M", (), {"author": "bob"})}
    calls = {"add_saved": 0, "add_cat": 0}
    async def fake_add_saved(link_entry): calls["add_saved"] += 1
    async def fake_add_cat(cat, link): calls["add_cat"] += 1
    monkeypatch.setattr(main.storage, "add_saved_link", lambda entry: asyncio.run(fake_add_saved(entry)))
    monkeypatch.setattr(main.storage, "add_link_to_category", lambda cat, link: asyncio.run(fake_add_cat(cat, link)))
    sent = {}
    class DummyCtx:
        author = type("A", (), {"id": 1, "mention": "@u"})
        async def send(self, msg): sent["msg"] = msg
    await cog.assign_category(DummyCtx(), category_name="cat")
    assert calls["add_saved"] == 1
    assert calls["add_cat"] == 1
    assert "saved" in sent["msg"]
