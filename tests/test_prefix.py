import pytest
import main

@pytest.mark.asyncio
async def test_get_preferred_prefix_list():
    class DummyBot:
        command_prefix = ["!", "$"]
    prefix = await main.LinkManagerCog._get_preferred_prefix(main.LinkManagerCog, DummyBot(), None)
    assert prefix in ("!", "$")

@pytest.mark.asyncio
async def test_get_preferred_prefix_callable():
    class DummyBot:
        async def cp(self, bot, message): return "?"
        command_prefix = lambda self, bot, msg: "?"
    bot = DummyBot()
    prefix = await main.LinkManagerCog._get_preferred_prefix(main.LinkManagerCog, bot, None)
    assert prefix == "?"
