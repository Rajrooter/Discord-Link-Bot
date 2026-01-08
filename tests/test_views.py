import pytest
import main

class DummyUser:
    def __init__(self, id): self.id = id
    mention = "<@user>"
    display_name = "user"

class DummyInteraction:
    def __init__(self, user_id=1):
        self.user = DummyUser(user_id)
        self.response = type("Resp", (), {"send_message": lambda *a, **k: None, "defer": lambda *a, **k: None})()
        self.followup = type("Fup", (), {"send": lambda *a, **k: None})()
        self.channel = type("Chan", (), {"send": lambda *a, **k: None})()
        self.message = type("Msg", (), {"edit": lambda *a, **k: None})()

@pytest.mark.asyncio
async def test_summarize_view_interaction_check_allows_author():
    view = main.SummarizeView("url", "file.txt", author_id=1, context_note="", cog=None)
    allowed = await view.interaction_check(DummyInteraction(user_id=1))
    assert allowed is True

@pytest.mark.asyncio
async def test_summarize_view_interaction_check_blocks_other():
    view = main.SummarizeView("url", "file.txt", author_id=1, context_note="", cog=None)
    allowed = await view.interaction_check(DummyInteraction(user_id=2))
    assert allowed is False
