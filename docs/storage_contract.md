# Storage Contract (Reference)

This documents the expected schema/contract between `main.py` and the `storage` module.

## Pending links
- Added via: `add_pending_link(entry: dict) -> pending_id`
- Expected fields:
  - `user_id` (int)
  - `link` (str, URL)
  - `channel_id` (int)
  - `original_message_id` (int)
  - `timestamp` (ISO string)
- Updated via: `update_pending_with_bot_msg_id(pending_id, bot_msg_id)`
- Deleted via: `delete_pending_link_by_id(pending_id)`
- Queried via: `get_pending_links_for_user(user_id) -> list[dict]` with keys above plus `_id`

## Saved links
- Added via: `add_saved_link(entry: dict)`
  - `url` (str)
  - `timestamp` (str or ISO)
  - `author` (str)
  - `category` (str)
- Retrieved via: `get_saved_links() -> list[dict]`
- Cleared via: `clear_saved_links()`

## Categories
- Added via: `add_link_to_category(category: str, url: str)`
- Retrieved via: `get_categories() -> dict[str, list[str]]`
- Cleared via: `clear_categories()`

## Onboarding
- Loaded via: `load_onboarding_data() -> dict`
- Saved via: `save_onboarding_data(data: dict)`

## Optional (if implemented) Guild Config
- `get_guild_config(guild_id) -> dict`
- `set_guild_config(guild_id, config: dict)`

### Notes
- All functions should be thread-safe if called via `asyncio.to_thread`.
- Implementations should tolerate missing or malformed fields gracefully.
