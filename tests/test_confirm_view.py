import pytest
import main

@pytest.mark.asyncio
async def test_confirm_yes_no_view_allows_author(monkeypatch):
    called = {"ok": False}
    async def on_confirm():
        called["ok"] = True

    view = main.ConfirmYesNoView(author_id=1, on_confirm=on_confirm)
    class DummyUser: id = 1
    class DummyResp:
        async def send_message(self, *a, **k): pass
        async def defer(self): pass
    class DummyFup:
        async def send(self, *a, **k): pass
    class DummyMsg:
        async def edit(self, *a, **k): pass
    class DummyInteraction:
        def __init__(self):
            self.user = DummyUser()
            self.response = DummyResp()
            self.followup = DummyFup()
            self.message = DummyMsg()
    inter = DummyInteraction()
    assert await view.interaction_check(inter) is True
    await view.yes(inter, None)  # simulate pressing yes
    assert called["ok"] is True

@pytest.mark.asyncio
async def test_confirm_yes_no_view_blocks_other():
    view = main.ConfirmYesNoView(author_id=1, on_confirm=lambda: None)
    class DummyUser: id = 2
    class DummyResp:
        async def send_message(self, *a, **k): pass
    class DummyInteraction:
        def __init__(self):
            self.user = DummyUser()
            self.response = DummyResp()
    inter = DummyInteraction()
    assert await view.interaction_check(inter) is False
