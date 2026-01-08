#!/usr/bin/env python3
"""
Digital Labour - main.py

UX / UI refinements: 
- Consistent embed builders (titles, emojis, short bullets, footers)
- Clear CTAs on buttons (Save / Ignore / Summarize / Cancel)
- Two-line AI verdicts (Keep/Skip + safety word) for link checks
- Multi-link select flow with clear instructions and safe defaults
- Summarization flow with progress + structured output template
- Error/ratelimit messaging with single action/hint
- CYBERPUNK + TERMINAL THEME for all embeds and responses
"""

import asyncio
import datetime
import io
import json
import os
import re
import time
import uuid
from typing import Optional, List, Dict, Callable, Awaitable
from urllib.parse import urlparse

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

import storage
from utils import logger, is_valid_url, RateLimiter, EventCleanup
SESSION_ID = str(uuid.uuid4())

load_dotenv()

# Optional Google Gemini client (set GEMINI_API_KEY to enable)
try:
    from google import genai  # type: ignore
except Exception:
    genai = None

GEMINI_API_KEY = os. environ.get("GEMINI_API_KEY")


def _has_model(client, model_name: str) -> bool:
    try:
        return hasattr(client, "models") and hasattr(client.models, "generate_content")
    except Exception:
        return False


if GEMINI_API_KEY and genai is not None:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    AI_ENABLED = True and _has_model(ai_client, "gemini-2.0-flash-exp")
    if AI_ENABLED:
        logger.info("✅ Google Gemini AI enabled")
    else:
        logger.warning("⚠️ AI client missing generate_content; AI disabled")
else:
    ai_client = None
    AI_ENABLED = False
    logger.warning("⚠️ AI disabled - Add GEMINI_API_KEY to enable")

# Defaults (can be overridden per-guild)
AUTO_DELETE_ENABLED = os.environ.get("AUTO_DELETE_ENABLED", "1") == "1"
try:
    AUTO_DELETE_SECONDS_DEFAULT = int(os.environ. get("AUTO_DELETE_AFTER", "5"))
except ValueError:
    AUTO_DELETE_SECONDS_DEFAULT = 5

BATCH_WINDOW_SECONDS = 3
BATCH_THRESHOLD_DEFAULT = 5
CONFIRM_TIMEOUT = 4
AI_PROMPT_LIMIT = 12000  # cap prompt length defensively

# Storage files (used by storage module)
RULES_FILE = "server_rules.txt"

URL_REGEX = r'(? :https?://|www\.)\S+'
IGNORED_EXTENSIONS = ['.gif', '.png', '.jpg', '.jpeg', '. webp', '.bmp', '.mp4', '.mov', '. avi']

# Context site provided by user
COMMUNITY_LEARNING_URL = os.environ.get("COMMUNITY_LEARNING_URL", "https://share.google/yf57dJNzEyAVM0asz")

# ---------------------------------------------------------------------------
# Cyberpunk Theme Helpers
# ---------------------------------------------------------------------------

def make_cyberpunk_header(title: str, subtitle: str = "") -> str:
    """Generate cyberpunk ASCII art header"""
    header = f"""```ansi
[2;36m╔═══════════════════════════════════════════════╗[0m
[2;36m║[0m  [1;37m{title[: 40]: ^40}[0m  [2;36m║[0m
"""
    if subtitle:
        header += f"[2;36m║[0m  [2;33m{subtitle[:40]:^40}[0m  [2;36m║[0m\n"
    header += "[2;36m╚═══════════════════════════════════════════════╝[0m\n```"
    return header


def make_status_indicator(status: str) -> str:
    """Return colored status badge"""
    badges = {
        "online": "[1;32m[ONLINE][0m",
        "ok": "[1;32m[OK][0m",
        "error": "[1;31m[ERROR][0m",
        "warning": "[1;33m[! ][0m",
        "safe": "[1;32m[SAFE][0m",
        "caution": "[1;33m[CAUTION][0m",
        "unsafe": "[1;31m[UNSAFE][0m",
        "processing": "[1;36m[PROCESSING][0m",
    }
    return badges. get(status. lower(), f"[1;37m[{status.upper()}][0m")


def make_progress_bar(percentage: int, width: int = 20) -> str:
    """Create ASCII progress bar"""
    filled = int((percentage / 100) * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[1;32m{bar}[0m [1;37m{percentage}%[0m"


# ---------------------------------------------------------------------------
# Enhanced Embed / UI helpers
# ---------------------------------------------------------------------------

def make_embed(
    title: str,
    description: str = "",
    color: discord.Color = discord.Color.blurple(),
    footer: str = "",
    fields: Optional[List[Dict[str, str]]] = None,
) -> discord.Embed:
    """Enhanced embed builder"""
    embed = discord.Embed(title=title[: 256], description=description[:4000], color=color)
    if fields:
        for f in fields:
            embed.add_field(
                name=f. get("name", "")[:256],
                value=f.get("value", "")[:1024],
                inline=f.get("inline", False),
            )
    if footer:
        embed.set_footer(text=footer[:2048])
    embed.timestamp = datetime.datetime.utcnow()
    return embed


def verdict_embed(link: str, verdict_text: str, reason: str, author_mention: str = "") -> discord.Embed:
    """Enhanced AI verdict with cyberpunk terminal styling"""
    
    # Determine color based on verdict
    if "Keep" in verdict_text or "Safe" in verdict_text:
        color = 0x00FF9C
        status = make_status_indicator("safe")
    elif "Skip" in verdict_text or "Caution" in verdict_text: 
        color = 0xFF6600
        status = make_status_indicator("caution")
    elif "Unsafe" in verdict_text: 
        color = 0xFF0055
        status = make_status_indicator("unsafe")
    else:
        color = 0x00D9FF
        status = make_status_indicator("processing")
    
    header = """```ansi
[2;36m╔═══════════════════════════════════════╗[0m
[2;36m║[0m  [1;37m📎 LINK ANALYSIS COMPLETE[0m           [2;36m║[0m
[2;36m╚═══════════════════════════════════════╝[0m
```"""
    
    verdict_box = f"""```ansi
[1;36m┌─[0m [1;37mAI VERDICT[0m [1;36m────────────────────────────┐[0m
[1;36m│[0m
[1;36m│[0m {status} [1;37m{verdict_text}[0m
[1;36m│[0m
[1;36m│[0m [2;37mReason:[0m [1;37m{reason[: 50]}[0m
[1;36m│[0m
[1;36m└────────────────────────────────────────┘[0m

[2;35m>_[0m [2;37mURL:[0m [2;36m{link[: 60]}{'...' if len(link) > 60 else ''}[0m
```"""
    
    footer_text = f"Analyzed for {author_mention}" if author_mention else "Neural analysis complete"
    
    return make_embed(
        title="",
        description=header + verdict_box,
        color=color,
        footer=footer_text,
    )


def multi_link_embed(count: int) -> discord.Embed:
    """Cyberpunk multi-link selection prompt"""
    header = make_cyberpunk_header("MULTIPLE LINKS DETECTED", f"{count} URLs found")
    
    content = f"""```ansi
[1;36m>_[0m [1;37mSelect the links you want to save[0m
[2;36m├─>[0m [2;37mUse the dropdown menu below[0m
[2;36m├─>[0m [2;37mYou can select multiple links[0m
[2;36m└─>[0m [2;37mIgnore the rest automatically[0m
```

**💡 Tip:** Choose only what you need for better organization."""
    
    return make_embed(
        title="",
        description=header + content,
        color=0xFFFF00,
        footer="Batch selection mode active",
    )


def summarize_progress_embed(filename: str) -> discord.Embed:
    """Terminal-style progress indicator"""
    header = """```ansi
[1;35m>_[0m [1;35m[PROCESSING][0m [1;37mDOCUMENT ANALYSIS[0m
```"""
    
    progress = f"""```ansi
[2;36m┌─[0m [1;37mFILE[0m [2;36m────────────────────────────────┐[0m
[2;36m│[0m [1;33m{filename[: 35]}[0m
[2;36m└──────────────────────────────────────┘[0m

[1;36m>_[0m [2;37mExtracting text.. .[0m
[1;36m>_[0m [2;37mAnalyzing content...[0m
[1;36m>_[0m [2;37mGenerating summary...[0m

{make_progress_bar(66, 30)}
```"""
    
    return make_embed(
        title="",
        description=header + progress,
        color=0xFF00FF,
        footer="AI summarization in progress • Please wait",
    )


def summarize_result_embed(filename: str, body: str, requester: str) -> discord.Embed:
    """Structured summary output with cyberpunk styling"""
    header = f"""```ansi
[2;35m╔═══════════════════════════════════════╗[0m
[2;35m║[0m  [1;37m📝 SUMMARY COMPLETE[0m                 [2;35m║[0m
[2;35m╚═══════════════════════════════════════╝[0m

[1;36m>_[0m [1;37mFile:[0m [1;33m{filename[:40]}[0m
```"""
    
    summary_content = body[:3500] if len(body) > 3500 else body
    
    return make_embed(
        title="",
        description=header + f"\n{summary_content}",
        color=0x00FF9C,
        footer=f"Summarized for {requester} • AI-powered analysis",
    )


def error_embed(msg: str) -> discord.Embed:
    """Cyberpunk-styled error message with red alert theme"""
    header = """```ansi
[1;31m╔═══════════════════════════════════════╗[0m
[1;31m║[0m  [1;37m⚠️  SYSTEM ERROR DETECTED[0m          [1;31m║[0m
[1;31m╚═══════════════════════════════════════╝[0m
```"""
    
    error_content = f"""```ansi
[2;31m>_[0m [1;31m[ERROR][0m [2;37m{msg[:200]}[0m
```

**🔧 Action Required:** Check your input and try again."""
    
    return make_embed(
        title="",
        description=header + error_content,
        color=0xFF0055,
        footer="If this persists, contact an administrator",
    )


def ratelimit_embed(wait_s: float) -> discord.Embed:
    """Cooldown timer with visual progress bar"""
    header = """```ansi
[1;33m╔═══════════════════════════════════════╗[0m
[1;33m║[0m  [1;37m⏳ COOLDOWN ACTIVE[0m                  [1;33m║[0m
[1;33m╚═══════════════════════════════════════╝[0m
```"""
    
    cooldown_bar = make_progress_bar(int((wait_s / 10) * 100), 25)
    
    content = f"""```ansi
[2;33m>_[0m [1;33m[! ][0m [2;37mPlease wait {wait_s:. 1f} seconds[0m

{cooldown_bar}
```

**⚡ Tip:** This prevents spam and keeps the bot responsive."""
    
    return make_embed(
        title="",
        description=header + content,
        color=0xFF6600,
        footer="Rate limit protection active",
    )


def make_cyberpunk_help_embed() -> discord.Embed:
    """Full cyberpunk + terminal themed help embed"""
    embed = discord.Embed(title="", description="", color=0x00FF9C)
    
    # ASCII Art Header
    header = """```ansi
[2;36m╔═══════════════════════════════════════════════╗[0m
[2;35m║[0m  [1;36m▓█████▄  ██▓  ▄████  ██▓▄▄▄█████▓ ▄▄▄       ██▓    [0m [2;35m║[0m
[2;35m║[0m  [1;36m▒██▀ ██▌▓██▒ ██▒ ▀█▒▓██▒▓  ██▒ ▓▒▒████▄    ▓██▒    [0m [2;35m║[0m
[2;35m║[0m  [1;35m░██   █▌▒██▒▒██░▄▄▄░▒██▒▒ ▓██░ ▒░▒█��  ▀█▄  ▒██░    [0m [2;35m║[0m
[2;35m║[0m  [1;35m░▓█▄   ▌░██░░▓█  ██▓░██░░ ▓██▓ ░ ░██▄▄▄▄██ ▒██░    [0m [2;35m║[0m
[2;35m║[0m  [1;33m░▒████▓ ░██░░▒▓███▀▒░██░  ▒██▒ ░  ▓█   ▓██▒░██████▒[0m [2;35m║[0m
[2;35m║[0m  [1;33m ▒▒▓  ▒ ░▓   ░▒   ▒ ░▓    ▒ ░░    ▒▒   ▓▒█░░ ▒░▓  ░[0m [2;35m║[0m
[2;36m╚═══════════════════════════════════════════════╝[0m
[1;32m>_[0m [1;37mLABOUR BOT v3.0[0m [2;33m// NEURAL LINK MANAGER[0m
[2;35m>_[0m [2;37mStatus:[0m [1;32m[ONLINE][0m [2;33m// Session:  ACTIVE[0m
```"""
    
    embed.description = header
    
    # Link Operations
    link_commands = """```ansi
[1;36m┌─[0m [1;37mLINK_OPERATIONS[0m [1;36m─────────────────────────────────┐[0m
[1;36m│[0m
[1;32m│ ▸[0m [1;33m/pendinglinks[0m
[1;36m│   └─>[0m Review queued links from burst detection
[1;36m│[0m
[1;32m│ ▸[0m [1;33m/category[0m [2;35m<name>[0m
[1;36m│   └─>[0m Assign category to pending link
[1;36m│[0m
[1;32m│ ▸[0m [1;33m/cancel[0m
[1;36m│   └─>[0m Abort current link save operation
[1;36m│[0m
[1;32m│ ▸[0m [1;33m/getlinks[0m [2;35m[category][0m
[1;36m│   └─>[0m Retrieve saved links (filter optional)
[1;36m│[0m
[1;32m│ ▸[0m [1;33m/deletelink[0m [2;35m<number>[0m
[1;36m│   └─>[0m Remove link by index number
[1;36m│[0m
[1;36m└───────────────────────────────────────────────┘[0m
```"""
    
    embed.add_field(name="\u200b", value=link_commands, inline=False)
    
    # Analysis Commands
    search_commands = """```ansi
[1;35m┌─[0m [1;37mANALYSIS_MODULES[0m [1;35m─────────────────────────────────┐[0m
[1;35m│[0m
[1;32m│ ▸[0m [1;33m/analyze[0m [2;35m<url>[0m
[1;35m│   └─>[0m AI-powered link safety & relevance check
[1;35m│[0m
[1;32m│ ▸[0m [1;33m/searchlinks[0m [2;35m<term>[0m
[1;35m│   └─>[0m Full-text search across saved links
[1;35m│[0m
[1;32m│ ▸[0m [1;33m/stats[0m
[1;35m│   └─>[0m Display analytics dashboard
[1;35m│[0m
[1;32m│ ▸[0m [1;33m/recent[0m
[1;35m│   └─>[0m Show 5 most recent saves
[1;35m│[0m
[1;35m└───────────────────────────────────────────────┘[0m
```"""
    
    embed.add_field(name="\u200b", value=search_commands, inline=False)
    
    # Organization
    org_commands = """```ansi
[1;33m┌─[0m [1;37mORGANIZATION_SYSTEMS[0m [1;33m─────────────────────────────┐[0m
[1;33m│[0m
[1;32m│ ▸[0m [1;33m/categories[0m
[1;33m│   └─>[0m List all categories with link counts
[1;33m│[0m
[1;32m│ ▸[0m [1;33m/deletecategory[0m [2;35m<name>[0m
[1;33m│   └─>[0m Remove category and all its links
[1;33m│[0m
[1;32m│ ▸[0m [1;33m/clearlinks[0m [2;31m[ADMIN][0m
[1;33m│   └─>[0m Purge all saved data (requires confirmation)
[1;33m│[0m
[1;33m└───────────────────────────────────────────────┘[0m
```"""
    
    embed.add_field(name="\u200b", value=org_commands, inline=False)
    
    # Features
    features = """```ansi
[2;36m┌─[0m [1;37mSYSTEM_FEATURES[0m [2;36m──────────────────────────────────┐[0m
[2;36m│[0m
[1;32m│ ◆[0m [1;37mAuto Link Detection[0m [2;33m// Captures URLs automatically[0m
[1;32m│ ◆[0m [1;37mAI Safety Check[0m [2;33m// Evaluates relevance & safety[0m
[1;32m│ ◆[0m [1;37mDocument Summarization[0m [2;33m// . txt/.pdf/. docx support[0m
[1;32m│ ◆[0m [1;37mBurst Protection[0m [2;33m// Queues links during spam[0m
[1;32m│ ◆[0m [1;37mSmart Categorization[0m [2;33m// Organize by topics[0m
[2;36m│[0m
[2;36m└───────────────────────────────────────────────┘[0m
```"""
    
    embed.add_field(name="\u200b", value=features, inline=False)
    
    footer_text = """```ansi
[2;35m╔═══════════════════════════════════════════════╗[0m
[2;35m║[0m [1;33m⚡[0m [2;37mTIP:[0m [1;37mMention me + question for AI help[0m        [2;35m║[0m
[2;35m║[0m [1;33m⚡[0m [2;37mDrop a link → AI verdict → Save/Ignore[0m      [2;35m║[0m
[2;35m║[0m [1;33m⚡[0m [2;37mUpload document → Click summarize button[0m   [2;35m║[0m
[2;35m╚═══════════════════════════════════════════════╝[0m
[2;33m>_[0m [2;37mPowered by Gemini AI[0m [1;35m//[0m [2;37mMade for Digital Labour[0m
```"""
    
    embed.add_field(name="\u200b", value=footer_text, inline=False)
    
    embed.set_footer(text="[SYSTEM] Neural Link Established • Use /cmdinfo <command> for details")
    embed.timestamp = datetime.datetime.utcnow()
    
    return embed


def make_compact_help_embed() -> discord.Embed:
    """Compact mobile-friendly version"""
    embed = discord.Embed(
        title="⚡ LABOUR BOT // COMMAND INDEX",
        description="```ansi\n[1;32m>_[0m [1;37mNeural Link Manager v3.0[0m\n```",
        color=0x00FF9C
    )
    
    commands_list = """
**🔗 Link Operations**
`/pendinglinks` • `/category` • `/cancel` • `/getlinks` • `/deletelink`

**🔍 Analysis & Search**
`/analyze` • `/searchlinks` • `/stats` • `/recent`

**📁 Organization**
`/categories` • `/deletecategory` • `/clearlinks`

**✨ Smart Features**
→ Auto-detect & AI check links
→ Summarize documents (. pdf/. docx/. txt)
→ Mention me for AI help
→ Burst protection queuing
    """
    
    embed.description += commands_list
    embed.set_footer(text="💡 Drop any link for AI analysis • Upload docs for instant summary")
    embed.timestamp = datetime.datetime.utcnow()
    
    return embed


# ---------------------------------------------------------------------------
# Safe send helper
# ---------------------------------------------------------------------------
async def safe_send(target, content=None, embed=None, ephemeral=False, view=None):
    """Attempt to send a message safely; log and swallow failures."""
    try:
        if hasattr(target, "send"):
            return await target.send(content=content, embed=embed, view=view)
        if hasattr(target, "response"):
            return await target.response.send_message(content=content, embed=embed, ephemeral=ephemeral, view=view)
        if hasattr(target, "followup"):
            return await target. followup.send(content=content, embed=embed, ephemeral=ephemeral, view=view)
    except Exception as e:
        logger.error(f"Send failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Guild config (with storage fallback)
# ---------------------------------------------------------------------------
class GuildConfig:
    def __init__(self):
        self._mem = {}  # {guild_id: {"auto_delete_seconds": int, "batch_threshold": int}}

    def load(self, guild_id:  Optional[int]) -> Dict[str, int]:
        if not guild_id:
            return {}
        try:
            if hasattr(storage, "get_guild_config"):
                cfg = storage.get_guild_config(guild_id) or {}
                self._mem[guild_id] = cfg
                return cfg
        except Exception as e:
            logger.debug(f"load guild config failed: {e}")
        return self._mem.get(guild_id, {})

    def save(self, guild_id: Optional[int], cfg: Dict[str, int]):
        if not guild_id: 
            return
        self._mem[guild_id] = cfg
        try:
            if hasattr(storage, "set_guild_config"):
                storage. set_guild_config(guild_id, cfg)
        except Exception as e:
            logger.debug(f"save guild config failed:  {e}")

    def get_value(self, guild_id: Optional[int], key: str, default):
        cfg = self.load(guild_id)
        return cfg.get(key, default)


guild_config = GuildConfig()

# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------

async def ai_call(prompt: str, max_retries: int = 3, timeout: float = 18.0) -> str:
    """Wrapper to call the GenAI client in a background thread."""
    if not AI_ENABLED or ai_client is None:
        return "⚠️ AI unavailable.  Set GEMINI_API_KEY to enable AI features."
    if len(prompt) > AI_PROMPT_LIMIT:
        logger.debug(f"Prompt truncated from {len(prompt)} to {AI_PROMPT_LIMIT}")
        prompt = prompt[:AI_PROMPT_LIMIT]
    if not _has_model(ai_client, "gemini-2.0-flash-exp"):
        return "⚠️ AI model not available. Please check the client version."
    for attempt in range(max_retries):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    ai_client.models.generate_content,
                    model='gemini-2.0-flash-exp',
                    contents=prompt
                ),
                timeout=timeout
            )
            return getattr(response, "text", str(response))
        except asyncio.TimeoutError:
            if attempt == max_retries - 1:
                logger.error("AI timeout")
                return "⚠️ AI timeout. Try again later."
            await asyncio.sleep(1 * (attempt + 1))
        except Exception as e:
            logger.error(f"AI error: {e}")
            if attempt == max_retries - 1:
                return f"⚠️ AI error: {e}"
            await asyncio.sleep(1 * (attempt + 1))


async def get_ai_guidance(url: str) -> str:
    # Two-line, strict format
    prompt = f"""Evaluate this URL for study purposes and safety in exactly 2 lines: 

URL: {url}

Format: 
Line 1: Keep or Skip
Line 2: One short sentence explaining why and mention safety (Safe/Suspect/Unsafe)
"""
    return await ai_call(prompt, max_retries=3, timeout=12.0)


async def ai_improve_rules(rules_text: str, server_summary: str = "") -> str:
    instruction = (
        "You are a patient teacher and community mentor helping moderators of a student-focused Discord server. "
        "Audience: students from rural India (limited tech/job knowledge). Use very simple language, short sentences, and numbered steps. "
        "Provide immediate highlights and a clear checklist.  Do NOT share private data."
    )
    prompt = (
        instruction
        + "\n\nServer summary:\n" + (server_summary or "No summary")
        + "\n\nCurrent rules text:\n" + rules_text
        + "\n\nRespond with headings:\n"
        "1) Friendly strengths summary (2 lines)\n"
        "2) Immediate highlights (3-6 bullets)\n"
        "3) Simple numbered improvements (step-by-step)\n"
        "4) Rewrite a concise rules block suitable to pin\n"
        "5) Short moderator enforcement & teaching steps (2-4)\n"
    )
    return await ai_call(prompt, max_retries=3, timeout=25.0)


async def ai_server_audit(guild:  discord.Guild, topic: str, extra_context: str = "") -> str:
    try:
        parts = [
            f"Server: {guild.name}",
            f"Members: {guild.member_count}",
            f"Roles: {', '.join([r.name for r in guild. roles if r.name != '@everyone'][: 20])}"
        ]
        categories = []
        for c in guild.categories:
            categories.append(f"{c.name}({len(c.channels)})")
        parts.append("Categories:  " + ", ".join(categories[: 10]))
        server_summary = "\n".join(parts)
    except Exception: 
        server_summary = "No summary available."
    instruction = (
        "You are a kind teacher for rural students.  Use simple words and numbered steps. "
        "Provide:  one-line advice, immediate actions (3-6), a 1-3 month plan, 'how to teach' in 3 steps, channel suggestions, and short moderator scripts."
    )
    prompt = (
        instruction
        + f"\n\nTopic: {topic}\nServer summary:\n{server_summary}\nExtra context:\n{extra_context}\nWebsite: {COMMUNITY_LEARNING_URL}\n"
    )
    return await ai_call(prompt, max_retries=3, timeout=30.0)


async def ai_avatar_advice(desired_tone: str = "friendly") -> str:
    prompt = (
        "You are a gentle design guide for students with little tech experience. "
        "Suggest 3 avatar styles, why each works, and simple steps to create or choose one on phone."
        f"\nDesired tone: {desired_tone}"
    )
    return await ai_call(prompt, max_retries=2, timeout=12.0)


async def ai_channel_suggestions(guild: discord.Guild, focus:  str = "study & career") -> str:
    try:
        sample = []
        for c in guild.categories[: 8]: 
            sample.append(f"{c.name}: {', '.join([ch.name for ch in c.channels][: 6])}")
        uncategorized = [ch. name for ch in guild.channels if not getattr(ch, "category", None)]
        if uncategorized:
            sample.append("Uncat: " + ", ".join(uncategorized[: 6]))
        server_sample = " | ".join(sample[: 10]) or "No sample"
    except Exception:
        server_sample = "No sample"
    prompt = (
        "You are a patient teacher.  Suggest 6-12 channel ideas grouped by category with 1-line descriptions, "
        "prioritizing low-effort, high-value channels for rural students and career help.\n\n"
        f"Server sample: {server_sample}\nFocus: {focus}"
    )
    return await ai_call(prompt, max_retries=3, timeout=18.0)


# ---------------------------------------------------------------------------
# Document summarization helpers
# ---------------------------------------------------------------------------

async def download_bytes(url: str) -> Optional[bytes]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.debug(f"download_bytes non-200 for {url}: {resp.status}")
    except Exception as e:
        logger.debug(f"download_bytes error for {url}: {e}")
    return None


def extract_text_from_bytes(filename: str, data: bytes) -> Optional[str]:
    name = filename.lower()
    try:
        if name.endswith(". txt"):
            try:
                return data.decode("utf-8", errors="replace")
            except Exception:
                return data.decode("latin-1", errors="replace")
        if name.endswith(".pdf"):
            try:
                from PyPDF2 import PdfReader  # type: ignore
                with io.BytesIO(data) as bio:
                    reader = PdfReader(bio)
                    pages = []
                    for p in reader.pages:
                        pages.append(p.extract_text() or "")
                    return "\n". join(pages)
            except Exception as e:
                logger.debug(f"PDF extraction error: {e}")
                return None
        if name.endswith(". docx"):
            try:
                import docx  # type: ignore
                with io.BytesIO(data) as bio:
                    doc = docx.Document(bio)
                    return "\n".join(p.text for p in doc.paragraphs)
            except Exception as e:
                logger.debug(f"DOCX extraction error: {e}")
                return None
    except Exception as e:
        logger.debug(f"extract_text_from_bytes error: {e}")
    return None


async def summarize_document_bytes(filename: str, data: bytes, context_note: str = "") -> str:
    text = extract_text_from_bytes(filename, data)
    if not text:
        return "⚠️ Couldn't extract text.  For PDF/DOCX ensure PyPDF2 and python-docx are installed or provide a . txt version."
    excerpt = text[:40000]
    prompt = (
        "You are a gentle teacher.  Summarize this document for rural students in simple language.\n"
        "Use this structure:\n"
        "1) One-line summary\n2) 3 key points (bullets)\n3) 3 simple action steps\n4) A one-paragraph moderator-ready summary\n\n"
        f"Context note: {context_note}\n\nDocument excerpt:\n{excerpt}"
    )
    return await ai_call(prompt, max_retries=3, timeout=25.0)


# ---------------------------------------------------------------------------
# Utilities & storage helpers
# ---------------------------------------------------------------------------

def is_media_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
        for ext in IGNORED_EXTENSIONS:
            if path.endswith(ext):
                return True
        media_domains = ['giphy.com', 'tenor. com', 'imgur.com', 'gyazo.com', 'streamable.com', 'clippy. gg', 'cdn.discordapp.com', 'media.discordapp. net']
        domain = parsed.netloc.lower()
        return any(md in domain for md in media_domains)
    except Exception:
        return False


def load_rules() -> str:
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "📒 Server Rules:\n1.  Be respectful.\n2. Share educational content only.\n3. No spam."

# ---------------------------------------------------------------------------
# Bot and Views
# ---------------------------------------------------------------------------

intents = discord.Intents. default()
intents.message_content = True
intents. reactions = True
intents.members = True


def get_prefix(bot, message):
    prefixes = ["!"]
    return commands.when_mentioned_or(*prefixes)(bot, message)


class MyBot(commands.Bot):
    async def setup_hook(self):
        # ADD COG FIRST (before syncing)
        await self.add_cog(LinkManagerCog(self))
        logger.info("✅ LinkManager cog added")
        
        synced_commands = []
        try:
            global_synced = await self.tree.sync()
            synced_commands. extend(global_synced)
            logger.info(f"✅ Synced {len(global_synced)} commands globally")
        except Exception as e:
            logger.error(f"Global sync failed: {e}")

        test_guild_id = os.environ.get("TEST_GUILD_ID")
        if test_guild_id:
            try:
                guild_id = int(test_guild_id)
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                guild_synced = await self.tree.sync(guild=guild)
                logger.info(f"✅ Synced {len(guild_synced)} commands to test guild {guild_id}")
            except Exception as e:
                logger.error(f"Test guild sync failed: {e}")

        logger.info(f"✅ Total commands synced: {len(synced_commands)}")
        bot = MyBot(command_prefix=get_prefix, intents=intents, help_command=None)
# ---------------------------------------------------------------------------
# UI Views
# ---------------------------------------------------------------------------

class SummarizeView(discord.ui.View):
    def __init__(self, file_url: str, filename: str, author_id: int, context_note: str, cog):
        super().__init__(timeout=300)
        self.file_url = file_url
        self. filename = filename
        self.author_id = author_id
        self.context_note = context_note
        self.cog = cog
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await safe_send(interaction. response, embed=error_embed("Only the uploader can request summarization. "), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Summarize", style=discord.ButtonStyle.green, emoji="📝")
    async def summarize_button(self, interaction: discord. Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
            data = await download_bytes(self. file_url)
            if not data:
                await safe_send(interaction.followup, embed=error_embed("Failed to download the file."), ephemeral=True)
                return
            progress = await safe_send(interaction.followup, embed=summarize_progress_embed(self.filename), ephemeral=True)
            summary = await summarize_document_bytes(self.filename, data, context_note=self.context_note)
            embed = summarize_result_embed(self.filename, summary[: 3800], interaction.user.mention)
            await safe_send(interaction.channel, embed=embed)
            if progress and hasattr(progress, "edit"):
                try:
                    await progress.edit(content=None, embed=make_embed("✅ Done", "Summary posted.", discord.Color.green()))
                except Exception: 
                    pass
        except Exception as e:
            logger.error(f"Summarize button failed: {e}")
            await safe_send(interaction.followup, embed=error_embed("Summarization failed.  Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui. button(label="Cancel", style=discord.ButtonStyle. secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_send(interaction.response, content="Cancelled summarization.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass


class DisclaimerView(discord.ui. View):
    def __init__(self, links: list, author_id: int, original_message, cog):
        super().__init__(timeout=60)
        self.links = links
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await safe_send(interaction. response, embed=error_embed("This is not for you."), ephemeral=True)
            return False
        return True

    @discord.ui. button(label="Save links", style=discord.ButtonStyle. green, emoji="✅")
    async def yes_button(self, interaction, button):
        await interaction.response.defer()
        try:
            await self.message.delete()
        except Exception:
            pass
        links_data = [{"url": link} for link in self.links]
        embed = multi_link_embed(len(self.links))
        selection_view = MultiLinkSelectView(links_data, self. author_id, self.original_message, self.cog)
        prompt_msg = await safe_send(interaction.channel, embed=embed, view=selection_view)
        if prompt_msg:
            selection_view.message = prompt_msg

    @discord.ui.button(label="Ignore", style=discord.ButtonStyle. secondary, emoji="❌")
    async def no_button(self, interaction, button):
        await safe_send(interaction.response, content="👍 Ignoring these links.", ephemeral=True)
        try:
            await self.message. delete()
        except Exception: 
            pass


class LinkActionView(discord.ui.View):
    def __init__(self, link: str, author_id: int, original_message, pending_db_id: str, cog, ai_verdict: str = ""):
        super().__init__(timeout=300)
        self.link = link
        self.author_id = author_id
        self.original_message = original_message
        self.pending_db_id = pending_db_id
        self.cog = cog
        self.message = None
        self.ai_verdict = ai_verdict

    async def interaction_check(self, interaction):
        if interaction.user. id != self.author_id:
            await safe_send(interaction.response, embed=error_embed("This button is not for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green, emoji="💾")
    async def save_button(self, interaction, button):
        try:
            await asyncio.to_thread(storage.delete_pending_link_by_id, self.pending_db_id)
            if interaction.message. id in self.cog.pending_links:
                del self.cog.pending_links[interaction.message.id]
            self.cog.links_to_categorize[self.author_id] = {"link": self.link, "message":  self.original_message}
            prefix = await self.cog._get_preferred_prefix(self.original_message) if self.original_message else "!"
            await safe_send(interaction.response, content=f"✅ Link marked for saving!  Use `{prefix}category <name>` to finalize.", ephemeral=True)
        except Exception as e: 
            logger.error(f"Save failed: {e}")
            await safe_send(interaction.response, embed=error_embed("Failed to mark link for saving.  Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child. disabled = True
            try: 
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Ignore", style=discord.ButtonStyle.secondary, emoji="👋")
    async def ignore_button(self, interaction, button):
        confirm_view = ConfirmDeleteView(self.link, self.author_id, self.original_message, self.pending_db_id, interaction.message.id, self.cog)
        await safe_send(interaction.response, content="Are you sure you want to delete this link?", ephemeral=True)
        try:
            await interaction.message.edit(view=confirm_view)
        except Exception:
            pass


class MultiLinkSelectView(discord.ui.View):
    def __init__(self, links: list, author_id: int, original_message, cog):
        super().__init__(timeout=300)
        self.links = links
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.selected_links = []
        self. message = None
        options = []
        max_options = min(len(links), 25)
        for idx in range(max_options):
            url = links[idx]. get("url", "")
            label = f"Link {idx+1}"
            desc = url if len(url) <= 100 else url[:97] + "..."
            options.append(discord. SelectOption(label=label, value=str(idx), description=desc))
        if not options:
            options.append(discord.SelectOption(label="No valid links", value="0", description="Error"))

        select = discord.ui.Select(
            placeholder=f"Select links to save ({min(len(links),25)} available)",
            min_values=1,
            max_values=min(len(options), 25),
            options=options,
            custom_id="link_selector"
        )
        self.add_item(select)

    async def interaction_check(self, interaction):
        if interaction.user. id != self.author_id:
            await safe_send(interaction.response, embed=error_embed("Not your selection."), ephemeral=True)
            return False
        if interaction.data. get("custom_id") == "link_selector":
            values = interaction.data.get("values", [])
            self.selected_links = [int(v) for v in values]
            await interaction.response.defer()
            if self.selected_links:
                confirm_view = ConfirmMultiLinkView(self.links, set(self.selected_links), self.author_id, self.original_message, self.cog)
                confirm_msg = await safe_send(interaction.channel, content=f"✅ {len(self.selected_links)} link(s) selected. Confirm to save?", view=confirm_view)
                if confirm_msg: 
                    confirm_view.message = confirm_msg
                for child in self.children:
                    child.disabled = True
                try:
                    if self.message:
                        await self.message.edit(view=self)
                except Exception:
                    pass
            return False
        return True


class ConfirmMultiLinkView(discord.ui.View):
    def __init__(self, links: list, selected_indices:  set, author_id: int, original_message, cog):
        super().__init__(timeout=60)
        self.links = links
        self.selected_indices = selected_indices
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.message = None

    @discord.ui.button(label="Save selected", style=discord.ButtonStyle. green, emoji="💾")
    async def confirm_button(self, interaction, button):
        await interaction.response.defer()
        saved_count = 0
        for idx in self.selected_indices:
            try:
                link = self.links[idx]["url"]
                pending_entry = {
                    "user_id": interaction.user.id,
                    "link": link,
                    "channel_id": interaction.channel.id,
                    "original_message_id": self.original_message.id if self.original_message else 0,
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
                pending_id = await asyncio.to_thread(storage. add_pending_link, pending_entry)
                saved_count += 1
                self.cog.links_to_categorize[interaction.user.id] = {
                    "link": link,
                    "message": self. original_message,
                    "pending_db_id": pending_id
                }
                await safe_send(
                    interaction.channel,
                    content=(
                        f"{interaction.user.mention}, link {saved_count} saved to queue!\n"
                        f"Use `!category <name>` to save or `!cancel` to skip.\n"
                        f"`{link[: 100]}{'...' if len(link)>100 else ''}`"
                    )
                )
            except Exception as e:
                logger.error(f"Error saving link {idx}: {e}")
                await safe_send(interaction.channel, embed=error_embed("Failed to save one of the links. Please try again."))
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui. button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction, button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, link: str, author_id: int, original_message, pending_db_id: str, bot_msg_id: int, cog):
        super().__init__(timeout=60)
        self.link = link
        self.author_id = author_id
        self.original_message = original_message
        self.pending_db_id = pending_db_id
        self.bot_msg_id = bot_msg_id
        self.cog = cog
        self.message = None

    @discord.ui.button(label="Delete", style=discord.ButtonStyle. danger, emoji="🗑️")
    async def confirm_button(self, interaction, button):
        try:
            if self.original_message:
                try:
                    await self.original_message.delete()
                except Exception:
                    pass
            try:
                bot_msg = await interaction.channel.fetch_message(self.bot_msg_id)
                await bot_msg.delete()
            except Exception:
                pass
            try:
                await asyncio.to_thread(storage.delete_pending_link_by_id, self.pending_db_id)
            except Exception as e:
                logger.error(f"Pending delete failed: {e}")
            if self.bot_msg_id in self.cog.pending_links:
                del self.cog.pending_links[self.bot_msg_id]
            await safe_send(interaction.response, content="🗑️ Link deleted.", ephemeral=True)
        except Exception as e:
            logger.error(f"Confirm delete failed: {e}")
            await safe_send(interaction. response, embed=error_embed("Could not delete link. Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui. button(label="Keep", style=discord.ButtonStyle. secondary, emoji="↩️")
    async def cancel_button(self, interaction, button):
        await safe_send(interaction.response, content="Deletion cancelled.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message. edit(view=self)
        except Exception:
            pass


class ConfirmYesNoView(discord.ui.View):
    """Button-based confirmation to replace reactions for reliability."""
    def __init__(self, author_id: int, on_confirm: Callable[[], Awaitable[None]], prompt: str = "Are you sure?", timeout:  int = 60):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.on_confirm = on_confirm
        self.prompt = prompt

    async def interaction_check(self, interaction:  discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await safe_send(interaction. response, embed=error_embed("Not for you."), ephemeral=True)
            return False
        return True

    @discord.ui. button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response. defer()
        try:
            await self.on_confirm()
            await safe_send(interaction.followup, content="✅ Done.", ephemeral=True)
        except Exception as e:
            logger.error(f"ConfirmYesNoView error: {e}")
            await safe_send(interaction.followup, embed=error_embed("Failed to complete action. "), ephemeral=True)
        finally:
            for child in self.children:
                child. disabled = True
            try: 
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="No", style=discord.ButtonStyle. secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_send(interaction.response, content="Cancelled.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Cog implementation
# ---------------------------------------------------------------------------

class LinkManagerCog(commands.Cog, name="LinkManager"):
    def __init__(self, bot:  commands.Bot):
        self.bot = bot
        self.pending_links = {}
        self. pending_batches = {}
        self.pending_delete_confirmations = {}
        self.links_to_categorize = {}
        self.pending_category_deletion = {}
        self.pending_clear_all = {}
        self.processed_messages = set()
        self.event_cleanup = EventCleanup()
        self.rate_limiter = RateLimiter()
        self.pendinglinks_in_progress = set()
        self.cleanup_task = None

    def prune_processed(self, max_size=50000):
        if len(self.processed_messages) > max_size:
            self. processed_messages = set(list(self.processed_messages)[-max_size:])

    async def ensure_roles_exist(self):
        guild = None
        for g in self.bot.guilds:
            guild = g
            break
        if not guild:
            return
        required_roles = ["Male", "Female", "Other", "Data Science", "IT", "Other Department", "1st Year", "2nd Year", "3rd Year", "4th Year", "Graduate"]
        for role_name in required_roles:
            if not discord.utils.get(guild. roles, name=role_name):
                try:
                    await guild.create_role(name=role_name)
                except Exception as e:
                    logger. debug(f"Failed to create role {role_name}: {e}")

    async def cleanup_old_channel_events(self):
        while True:
            try:
                await asyncio.sleep(3600)
                self.event_cleanup.cleanup_memory()
                logger.info("Cleaned up old channel events")
            except Exception as e:
                logger.error(f"Event cleanup error: {e}")

    async def _get_preferred_prefix(self, message: Optional[discord.Message]) -> str:
        try:
            cp = self.bot.command_prefix
            if callable(cp):
                maybe = cp(self.bot, message)
                if asyncio.iscoroutine(maybe):
                    prefix = await maybe
                else: 
                    prefix = maybe
            else:
                prefix = cp
        except Exception: 
            prefix = "!"
        if isinstance(prefix, (list, tuple)):
            for p in prefix:
                if p and not p.startswith("<@"):
                    return p
            return prefix[0] if prefix else "!"
        return prefix or "!"

    async def _delete_if_no_response(self, bot_message, original_message, pending_db_id, delay=None):
        gid = original_message.guild.id if original_message and original_message.guild else None
        per_guild_delay = guild_config.get_value(gid, "auto_delete_seconds", AUTO_DELETE_SECONDS_DEFAULT)
        delay = delay if delay is not None else per_guild_delay
        if not AUTO_DELETE_ENABLED: 
            return
        await asyncio.sleep(delay)
        try:
            if bot_message and bot_message.id in self.pending_links:
                try:
                    await bot_message.delete()
                except Exception:
                    pass
                try:
                    del self.pending_links[bot_message.id]
                except Exception:
                    pass
                try:
                    await asyncio.to_thread(storage.delete_pending_link_by_id, pending_db_id)
                except Exception: 
                    pass
        except Exception as e:
            logger.debug(f"_delete_if_no_response error: {e}")

    async def _handle_mention_query(self, message: discord.Message) -> bool:
        user_id = message.author.id
        if self.rate_limiter.is_limited(user_id, "ai_mention", cooldown=8.0):
            remaining = self.rate_limiter. get_remaining(user_id, "ai_mention", cooldown=8.0)
            await safe_send(message. channel, embed=ratelimit_embed(remaining))
            return True

        content = (message.content or "").strip()
        mention_forms = (f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>")
        for m in mention_forms:
            content = content.replace(m, "")
        text = content.strip().lower()

        if re.search(r"\bwhat(? :'s| is)?  the server rules\b", text) or ("server rules" in text and "what" in text):
            rules_text = None
            if message.guild:
                ch = discord.utils.get(message.guild.text_channels, name="rules")
                if ch: 
                    try:
                        pinned = await ch.pins()
                        if pinned:
                            rules_text = pinned[0].content
                        else:
                            async for m in ch.history(limit=50):
                                if m.content and len(m.content) > 40 and not m.author.bot:
                                    rules_text = m. content
                                    break
                    except Exception:
                        rules_text = None
            if not rules_text:
                rules_text = load_rules()
            embed = make_embed(
                title="📒 Server Rules",
                description="\n".join(rules_text. splitlines()[:15])[: 1900] or "Rules not found.",
                color=discord.Color. blue(),
                footer="Mention me with 'improve rules' to get AI suggestions."
            )
            await safe_send(message.channel, embed=embed)
            return True

        if ("improv" in text or "suggest" in text or "review" in text) and ("#" in message.content or "channel" in text):
            rules_text = None
            channel_asked = None
            m = re.search(r"<#(\d+)>", message.content or "")
            if m and message.guild:
                try:
                    channel_asked = message.guild.get_channel(int(m.group(1)))
                except Exception:
                    channel_asked = None
            if not channel_asked and message.guild:
                for ch in message.guild.channels:
                    if ch.name and ch.name.lower() in text:
                        channel_asked = ch
                        break
            if channel_asked:
                try: 
                    pinned = []
                    if isinstance(channel_asked, discord.TextChannel):
                        pinned = await channel_asked.pins()
                    if pinned:
                        rules_text = pinned[0].content
                    else:
                        if isinstance(channel_asked, discord.TextChannel):
                            async for m2 in channel_asked.history(limit=50):
                                if m2.content and len(m2.content) > 40 and not m2.author.bot:
                                    rules_text = m2.content
                                    break
                except Exception: 
                    rules_text = None
            if not rules_text: 
                rules_text = load_rules()
            server_summary = f"{message.guild.name} — members: {message.guild.member_count}" if message.guild else ""
            await message.channel.trigger_typing()
            ai_response = await ai_improve_rules(rules_text or "No content found", server_summary)
            preview = "\n".join(ai_response. splitlines()[:8])
            await safe_send(message.channel, embed=make_embed("🧠 AI:  Improvements", preview[: 1500], discord.Color.teal()))
            for chunk in (ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if any(k in text for k in ("career", "job", "placement", "interview", "resume", "cv", "jobs")):
            extra_ctx = f"User question: {content. strip()}\nWebsite: {COMMUNITY_LEARNING_URL}\nAudience: rural students"
            await message.channel.trigger_typing()
            ai_response = await ai_server_audit(message.guild, topic="career guidance for students", extra_context=extra_ctx)
            preview = "\n". join(ai_response. splitlines()[:6])
            await safe_send(message.channel, embed=make_embed("🎯 AI:  Career Guidance", preview[: 1500], discord.Color.dark_gold()))
            for chunk in (ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if "how to learn" in text and "discord" in text or re.search(r"\bhow to use discord\b", text) or "learn using discord" in text:
            teacher_prompt = (
                "You are a patient teacher.  Explain, in numbered short steps, how students can use Discord to learn:  "
                "join channels, read pinned messages, use reactions, use slash commands, ask for help.  Add 3 safety tips."
            )
            ai_response = await ai_call(teacher_prompt, max_retries=2, timeout=12.0)
            await safe_send(message.channel, embed=make_embed("📘 Learning Discord (simple)", "\n".join(ai_response. splitlines()[:10])[:1500], discord.Color.green()))
            for chunk in (ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if "avatar" in text or "profile picture" in text or "which avatar" in text: 
            tone = "friendly, professional"
            m = re.search(r"tone[:\-]\s*([a-z, ]+)", text)
            if m:
                tone = m.group(1).strip()
            ai_response = await ai_avatar_advice(desired_tone=tone)
            await safe_send(message.channel, embed=make_embed("🖼️ Avatar suggestions", "\n".join(ai_response.splitlines()[:8])[:1500], discord.Color.purple()))
            for chunk in (ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if "what more channels" in text or "channels to create" in text or "suggest channels" in text:
            suggestions = await ai_channel_suggestions(message.guild, focus="study, career, low-resource teaching")
            await safe_send(message.channel, embed=make_embed("📂 Channel suggestions", "\n".join(suggestions.splitlines()[:8])[:1500], discord.Color.gold()))
            for chunk in (suggestions[i:i+1900] for i in range(0, len(suggestions), 1900)):
                await safe_send(message. channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if "prefix" in text or "command prefix" in text: 
            prefix = await self._get_preferred_prefix(message)
            await safe_send(message.channel, content=f"👋 My active command prefix is `{prefix}` — you can also use slash (/) commands.")
            return True

        return False

    @commands. Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user or message.id in self.processed_messages:
            return
        self.processed_messages.add(message.id)
        self.prune_processed()

        await self.bot.process_commands(message)

        try:
            if self.bot.user in message.mentions:
                handled = await self._handle_mention_query(message)
                if handled:
                    return
                prefix = await self._get_preferred_prefix(message)
                embed = make_embed(
                    title="👋 Welcome to Digital Labour",
                    description=(
                        "I help save links, summarize docs, and guide students.\n"
                        f"Prefix: `{prefix}` or use slash commands.\n"
                        "Try:  drop a link or type `/help`."
                    ),
                    color=discord.Color.blurple(),
                )
                await safe_send(message. channel, embed=embed)
                return
        except Exception: 
            logger.debug("mention handler error", exc_info=True)

        try:
            file_candidates = []
            for att in message.attachments:
                fn = att.filename. lower()
                if fn.endswith((".txt", ".pdf", ".docx")):
                    file_candidates. append((att. url, att.filename))
            for m in re.finditer(URL_REGEX, message.content or ""):
                url = m.group(0)
                if urlparse(url).path.lower().endswith((".txt", ".pdf", ".docx")):
                    file_candidates.append((url, os.path.basename(urlparse(url).path)))
            if file_candidates:
                for url, filename in file_candidates: 
                    view = SummarizeView(file_url=url, filename=filename, author_id=message.author.id, context_note=f"Uploaded in #{message.channel.name} by {message.author.display_name}", cog=self)
                    prompt_msg = await safe_send(message.channel, embed=make_embed("📝 Document detected", f"{message.author.mention}, click to summarize **{filename}**.", discord.Color.blurple()), view=view)
                    if prompt_msg:
                        view.message = prompt_msg
        except Exception:
            logger.debug("file summarize trigger error", exc_info=True)

        onboarding_data = storage.load_onboarding_data()
        user_id = str(message.author.id)
        if user_id in onboarding_data:
            user_data = onboarding_data[user_id]
            if user_data.get("state") == "college":
                user_data["data"]["college"] = message.content
                user_data["state"] = "referral"
                embed = make_embed(
                    title="Onboarding - Referral",
                    description="Who referred you to this server? (Type a name or 'None')",
                    color=discord. Color.green()
                )
                msg = await safe_send(message. channel, embed=embed)
                user_data["message_id"] = msg.id if msg else 0
                onboarding_data[user_id] = user_data
                storage.save_onboarding_data(onboarding_data)
                try:
                    await message.delete()
                except Exception:
                    pass
                return
            elif user_data.get("state") == "referral":
                user_data["data"]["referral"] = message.content
                user_data["state"] = "confirm"
                embed = make_embed(title="Please Confirm Your Information", color=discord.Color.blue())
                embed.add_field(name="Gender", value=user_data["data"]["gender"], inline=True)
                embed.add_field(name="Department", value=user_data["data"]["department"], inline=True)
                embed.add_field(name="Year", value=user_data["data"]["year"], inline=True)
                embed.add_field(name="College", value=user_data["data"]["college"], inline=True)
                embed.add_field(name="Referral", value=user_data["data"]["referral"], inline=True)
                embed.set_footer(text="React with ✅ to confirm or ❌ to start over")
                msg = await safe_send(message.channel, embed=embed)
                if msg:
                    try:
                        await msg.add_reaction('✅')
                        await msg.add_reaction('❌')
                    except Exception: 
                        pass
                    user_data["message_id"] = msg.id
                onboarding_data[user_id] = user_data
                storage.save_onboarding_data(onboarding_data)
                try:
                    await message.delete()
                except Exception:
                    pass
                return

        try:
            urls = [m.group(0) for m in re.finditer(URL_REGEX, message.content or "")]
        except re.error:
            urls = []

        if urls:
            non_media_links = [link for link in urls if not is_media_url(link) and is_valid_url(link)]
            if len(non_media_links) > 1:
                if len(non_media_links) > 25:
                    await safe_send(message.channel, embed=make_embed("📎 Many links detected", f"Found {len(non_media_links)} links. Processing in batches.  Use `!pendinglinks` to review.", discord.Color.gold()))
                    dropdown_links = non_media_links[:25]
                    remaining = non_media_links[25:]
                    for link in remaining:
                        try:
                            pending_entry = {
                                "user_id": message.author.id,
                                "link": link,
                                "channel_id": message.channel.id,
                                "original_message_id": message.id,
                                "timestamp": datetime.datetime.utcnow().isoformat()
                            }
                            pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                            self.pending_batches.setdefault(message.author.id, []).append({"link": link, "original_message":  message, "timestamp": time.time(), "pending_db_id": pending_id})
                        except Exception as e:
                            logger.error(f"Failed to queue link (batch overflow): {e}")
                            await safe_send(message.channel, embed=error_embed("Failed to queue one of the links. Please try again. "))
                else:
                    dropdown_links = non_media_links
                disclaimer_embed = multi_link_embed(len(non_media_links))
                disclaimer_view = DisclaimerView(dropdown_links, message.author.id, message, self)
                disclaimer_msg = await safe_send(message.channel, embed=disclaimer_embed, view=disclaimer_view)
                if disclaimer_msg:
                    disclaimer_view.message = disclaimer_msg
                return

            for link in non_media_links:
                ch_id = message.channel.id
                now = time.time()
                self.event_cleanup.add_event(ch_id, now)
                self.event_cleanup.cleanup_old_events(ch_id, BATCH_WINDOW_SECONDS)
                event_count = self.event_cleanup.get_event_count(ch_id, BATCH_WINDOW_SECONDS)
                gid = message.guild.id if message.guild else None
                per_guild_threshold = guild_config. get_value(gid, "batch_threshold", BATCH_THRESHOLD_DEFAULT)
                if event_count > per_guild_threshold:
                    try:
                        pending_entry = {
                            "user_id": message.author.id,
                            "link": link,
                            "channel_id": message.channel.id,
                            "original_message_id": message.id,
                            "timestamp": datetime.datetime.utcnow().isoformat()
                        }
                        pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                        self.pending_batches.setdefault(message.author.id, []).append({"link": link, "original_message": message, "timestamp":  now, "pending_db_id":  pending_id})
                        try:
                            await message.add_reaction("🗂️")
                        except Exception: 
                            pass
                        continue
                    except Exception as e: 
                        logger.error(f"Failed to queue link (burst): {e}")
                        await safe_send(message.channel, embed=error_embed("Failed to queue this link. Please try again."))
                        continue
                try:
                    pending_entry = {
                        "user_id": message.author.id,
                        "link": link,
                        "channel_id": message.channel.id,
                        "original_message_id": message.id,
                        "timestamp": datetime.datetime.utcnow().isoformat()
                    }
                    pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                    guidance = await get_ai_guidance(link)
                    lines = guidance.splitlines()
                    verdict_line = lines[0] if lines else "Keep/Skip"
                    reason_line = lines[1] if len(lines) > 1 else "No reason provided."
                    embed = verdict_embed(link, verdict_line, reason_line, author_mention=message.author.mention)
                    view = LinkActionView(link, message.author. id, message, pending_id, self, ai_verdict=guidance)
                    ask_msg = await safe_send(message.channel, embed=embed, view=view)
                    if pending_id:
                        try:
                            await asyncio.to_thread(storage. update_pending_with_bot_msg_id, pending_id, getattr(ask_msg, "id", None))
                        except Exception as e:
                            logger.error(f"Failed to update pending with bot msg id: {e}")
                    self.pending_links[getattr(ask_msg, "id", None)] = {"link": link, "author_id": message.author.id, "original_message": message, "pending_db_id": pending_id}
                    try:
                        asyncio.create_task(self._delete_if_no_response(ask_msg, message, pending_id))
                    except Exception: 
                        pass
                except Exception as e:
                    logger. error(f"Failed to process link: {e}")
                    await safe_send(message.channel, embed=error_embed("Failed to handle this link. Please try again."))

    # ---------------------------------------------------------------------
    # Hybrid commands
    # ---------------------------------------------------------------------

    @commands.hybrid_command(name="help", description="Display full command reference with cyberpunk UI")
    async def show_help(self, ctx: commands.Context, compact: bool = False):
        """Enhanced help command with cyberpunk aesthetics"""
        if compact: 
            embed = make_compact_help_embed()
        else:
            embed = make_cyberpunk_help_embed()
        await safe_send(ctx, embed=embed)

    @commands.hybrid_command(name="cmdinfo", description="Get detailed info about a specific command")
    async def command_info(self, ctx: commands.Context, command_name: str):
        """Detailed command information with examples"""
        cmd_details = {
            "pendinglinks": {
                "desc": "Review all links queued during burst detection",
                "usage": "/pendinglinks",
                "example": "Use after seeing 🗂️ reaction on messages",
                "color": 0x00FF9C
            },
            "category": {
                "desc": "Assign a category name to save your pending link",
                "usage": "/category <category_name>",
                "example": "`/category Python-Tutorials`",
                "color": 0xFF00FF
            },
            "analyze": {
                "desc": "Get AI-powered safety & relevance analysis",
                "usage":  "/analyze <url>",
                "example": "`/analyze https://github.com/awesome-repo`",
                "color": 0xFFFF00
            },
        }
        
        cmd = cmd_details.get(command_name.lower())
        
        if not cmd:
            await safe_send(ctx, embed=error_embed(f"Command '{command_name}' not found.  Use `/help` for full list."))
            return
        
        header = f"""```ansi
[1;36m>_ COMMAND:[0m [1;33m{command_name. upper()}[0m
```"""
        
        embed = discord.Embed(
            title="",
            description=header + f"\n**{cmd.get('desc', 'No description')}**",
            color=cmd.get('color', 0x00D9FF)
        )
        
        if 'usage' in cmd:
            embed.add_field(name="📝 Usage", value=f"```\n{cmd['usage']}\n```", inline=False)
        
        if 'example' in cmd:
            embed.add_field(name="💡 Example", value=cmd['example'], inline=False)
        
        embed.set_footer(text="[SYSTEM] Use /help for full command list")
        embed.timestamp = datetime.datetime.utcnow()
        
        await safe_send(ctx, embed=embed)

    @commands.hybrid_command(name="pendinglinks", description="Review your pending links captured during bursts")
    async def pendinglinks(self, ctx: commands.Context):
        user_id = ctx.author.id
        if self.rate_limiter.is_limited(user_id, "pendinglinks", cooldown=5.0):
            remaining = self.rate_limiter. get_remaining(user_id, "pendinglinks", cooldown=5.0)
            await safe_send(ctx, embed=ratelimit_embed(remaining))
            return
        if user_id in self.pendinglinks_in_progress:
            await safe_send(ctx, content=f"{ctx.author.mention}, you have a pending review in progress.")
            return
        self. pendinglinks_in_progress. add(user_id)
        try:
            try:
                pending_from_db = await asyncio.to_thread(storage. get_pending_links_for_user, user_id)
            except Exception as e:
                logger.error(f"pendinglinks fetch failed: {e}")
                await safe_send(ctx, embed=error_embed("Could not load pending links right now. Please try again. "))
                return
            batch = self.pending_batches.get(user_id, [])
            if not pending_from_db and not batch:
                await safe_send(ctx, content=f"{ctx.author.mention}, you have no pending links.")
                return
            for db_entry in pending_from_db:
                link = db_entry. get("link")
                pending_id = db_entry.get("_id")
                orig_msg_id = db_entry.get("original_message_id")
                orig_msg = None
                try:
                    orig_msg = await ctx.channel.fetch_message(orig_msg_id)
                except Exception: 
                    pass
                guidance = await get_ai_guidance(link)
                lines = guidance. splitlines()
                verdict_line = lines[0] if lines else "Keep/Skip"
                reason_line = lines[1] if len(lines) > 1 else "No reason provided."
                embed = verdict_embed(link, verdict_line, reason_line, author_mention=ctx.author. mention)
                view = LinkActionView(link, ctx.author. id, orig_msg, pending_id, self, ai_verdict=guidance)
                ask_msg = await safe_send(ctx, embed=embed, view=view)
                if pending_id:
                    try: 
                        await asyncio.to_thread(storage.update_pending_with_bot_msg_id, pending_id, getattr(ask_msg, "id", None))
                    except Exception as e:
                        logger.error(f"Failed to update pending with bot msg id: {e}")
                self.pending_links[getattr(ask_msg, "id", None)] = {"link": link, "author_id": ctx.author.id, "original_message": orig_msg, "pending_db_id":  pending_id}
                try: 
                    asyncio.create_task(self._delete_if_no_response(ask_msg, orig_msg, pending_id))
                except Exception:
                    pass
            for entry in batch:
                link = entry["link"]
                orig_msg = entry. get("original_message")
                pending_id = entry.get("pending_db_id")
                guidance = await get_ai_guidance(link)
                lines = guidance.splitlines()
                verdict_line = lines[0] if lines else "Keep/Skip"
                reason_line = lines[1] if len(lines) > 1 else "No reason provided."
                embed = verdict_embed(link, verdict_line, reason_line, author_mention=ctx.author.mention)
                view = LinkActionView(link, ctx.author.id, orig_msg, pending_id, self, ai_verdict=guidance)
                ask_msg = await safe_send(ctx, embed=embed, view=view)
                if pending_id:
                    try:
                        await asyncio. to_thread(storage.update_pending_with_bot_msg_id, pending_id, getattr(ask_msg, "id", None))
                    except Exception as e:
                        logger.error(f"Failed to update pending with bot msg id: {e}")
                self.pending_links[getattr(ask_msg, "id", None)] = {"link": link, "author_id": ctx. author.id, "original_message": orig_msg, "pending_db_id": pending_id}
                try:
                    asyncio.create_task(self._delete_if_no_response(ask_msg, orig_msg, pending_id))
                except Exception:
                    pass
            if user_id in self.pending_batches:
                del self.pending_batches[user_id]
        finally:
            self. pendinglinks_in_progress. discard(user_id)

    @commands.hybrid_command(name="category", description="Assign a category to a saved link")
    async def assign_category(self, ctx: commands.Context, *, category_name: str):
        if ctx.author.id not in self. links_to_categorize:
            await safe_send(ctx, content=f"No pending link to categorize, {ctx.author.mention}")
            return
        link_data = self.links_to_categorize[ctx.author.id]
        link = link_data["link"]
        message = link_data["message"]
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            link_entry = {"url": link, "timestamp": timestamp, "author":  str(message.author) if (message and message.author) else "Unknown", "category": category_name}
            await asyncio.to_thread(storage.add_saved_link, link_entry)
            await asyncio.to_thread(storage. add_link_to_category, category_name, link)
            await safe_send(ctx, content=f"✅ Link saved to '{category_name}', {ctx.author.mention}!")
            del self.links_to_categorize[ctx.author.id]
        except Exception as e:
            logger.error(f"assign_category failed: {e}")
            await safe_send(ctx, embed=error_embed("Failed to save the link. Please try again."))

    @commands.hybrid_command(name="cancel", description="Cancel saving a pending link")
    async def cancel_save(self, ctx: commands.Context):
        if ctx.author.id in self.links_to_categorize:
            del self.links_to_categorize[ctx.author.id]
            await safe_send(ctx, content=f"Link save cancelled, {ctx.author.mention}")
        else:
            await safe_send(ctx, content=f"No pending link, {ctx.author.mention}")

    @commands.hybrid_command(name="getlinks", description="Retrieve all saved links or filter by category")
    async def get_links(self, ctx: commands.Context, category: Optional[str] = None):
        links = storage.get_saved_links()
        if not links:
            await safe_send(ctx, content="No links saved yet!")
            return
        if category:
            filtered = [l for l in links if l. get("category", "").lower() == category.lower()]
            if not filtered: 
                await safe_send(ctx, content=f"No links found in category '{category}'")
                return
            links = filtered
            title = f"Links in '{category}':"
        else:
            title = "All saved links:"
        response = f"**{title}**\n\n"
        for i, link in enumerate(links, 1):
            response += f"{i}. **{link. get('category','Uncategorized')}** - {link['url']}\n   *(by {link. get('author','Unknown')}, {link.get('timestamp','')})*\n"
            if len(response) > 1500:
                await safe_send(ctx, content=response)
                response = ""
        if response:
            await safe_send(ctx, content=response)

    @commands.hybrid_command(name="categories", description="List categories")
    async def list_categories(self, ctx: commands.Context):
        categories = storage.get_categories()
        if not categories: 
            await safe_send(ctx, content="No categories created yet!")
            return
        response = "**📂 Categories:**\n"
        for cat, links in categories.items():
            response += f"• {cat} ({len(links)} links)\n"
        await safe_send(ctx, content=response)

    @commands.hybrid_command(name="deletelink", description="Delete a link by number")
    async def delete_link(self, ctx: commands.Context, link_number: int):
        try:
            links = storage.get_saved_links()
            if not links:
                await safe_send(ctx, content="No links to delete!")
                return
            if link_number < 1 or link_number > len(links):
                await safe_send(ctx, content=f"Invalid number! Use 1-{len(links)}.")
                return
            removed = links.pop(link_number - 1)
            storage.clear_saved_links()
            for l in links:
                storage.add_saved_link(l)
            cats = storage.get_categories()
            cat_name = removed. get("category")
            if cat_name in cats and removed. get("url") in cats[cat_name]:
                cats[cat_name].remove(removed.get("url"))
                if not cats[cat_name]: 
                    del cats[cat_name]
                storage.clear_categories()
                for k, vs in cats.items():
                    for v in vs:
                        storage.add_link_to_category(k, v)
            await safe_send(ctx, content=f"✅ Link {link_number} deleted!")
        except Exception as e: 
            logger.error(f"delete_link failed: {e}")
            await safe_send(ctx, embed=error_embed("Failed to delete the link. Please try again. "))

    @commands.hybrid_command(name="deletecategory", description="Delete a category and its links")
    async def delete_category(self, ctx: commands. Context, *, category_name: str):
        cats = storage.get_categories()
        if category_name not in cats:
            await safe_send(ctx, content=f"Category '{category_name}' doesn't exist!")
            return

        async def do_delete():
            storage.clear_categories()
            for k, vs in cats.items():
                if k == category_name:
                    continue
                for v in vs: 
                    storage.add_link_to_category(k, v)
            links = storage.get_saved_links()
            remaining = [l for l in links if l.get("category") != category_name]
            storage.clear_saved_links()
            for l in remaining:
                storage.add_saved_link(l)

        view = ConfirmYesNoView(author_id=ctx.author.id, on_confirm=do_delete, prompt=f"Delete '{category_name}'?")
        msg = await safe_send(ctx, content=f"Delete '{category_name}' and its {len(cats[category_name])} links?", view=view)
        if not msg:
            await safe_send(ctx, embed=error_embed("Failed to attach confirmation buttons.  Please try again."))

    @commands.hybrid_command(name="clearlinks", description="Clear all links (Admin)")
    @commands.has_permissions(administrator=True)
    async def clear_links(self, ctx: commands.Context):
        async def do_clear():
            storage.clear_categories()
            storage.clear_saved_links()

        view = ConfirmYesNoView(author_id=ctx.author.id, on_confirm=do_clear, prompt="Delete ALL links and categories?")
        msg = await safe_send(ctx, content="⚠️ Delete ALL links and categories?", view=view)
        if not msg: 
            await safe_send(ctx, embed=error_embed("Failed to attach confirmation buttons. Please try again."))

    @commands.hybrid_command(name="setconfig", description="(Admin) Set per-guild config:  auto_delete_seconds, batch_threshold")
    @commands.has_permissions(manage_guild=True)
    async def set_config(self, ctx: commands.Context, auto_delete_seconds: Optional[int] = None, batch_threshold: Optional[int] = None):
        gid = ctx.guild.id if ctx.guild else None
        cfg = guild_config. load(gid) if gid else {}
        if auto_delete_seconds is not None and auto_delete_seconds > 0:
            cfg["auto_delete_seconds"] = auto_delete_seconds
        if batch_threshold is not None and batch_threshold > 0:
            cfg["batch_threshold"] = batch_threshold
        guild_config.save(gid, cfg)
        await safe_send(ctx, content=f"Config updated:  {cfg}")

    @commands.hybrid_command(name="showconfig", description="Show current per-guild config")
    async def show_config(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else None
        cfg = guild_config.load(gid) if gid else {}
        await safe_send(ctx, content=f"Config: {cfg or 'defaults'}")

    @commands.hybrid_command(name="searchlinks", description="Search saved links")
    async def search_links(self, ctx: commands. Context, *, search_term: str):
        links = storage.get_saved_links()
        results = [l for l in links if search_term. lower() in l.get("url", "").lower() or search_term.lower() in l.get("category", "").lower()]
        if not results:
            await safe_send(ctx, content=f"No results for '{search_term}'")
            return
        response = f"**🔍 Search results for '{search_term}':**\n\n"
        for i, link in enumerate(results, 1):
            response += f"{i}. **{link.get('category','Uncategorized')}** - {link['url']}\n"
            if len(response) > 1500:
                await safe_send(ctx, content=response)
                response = ""
        if response:
            await safe_send(ctx, content=response)

    @commands.hybrid_command(name="analyze", description="Get AI guidance on a link")
    async def analyze_link(self, ctx: commands.Context, url: str):
        if self.rate_limiter.is_limited(ctx.author.id, "analyze", cooldown=10.0):
            remaining = self.rate_limiter. get_remaining(ctx.author. id, "analyze", cooldown=10.0)
            await safe_send(ctx, embed=ratelimit_embed(remaining))
            return
        if not is_valid_url(url):
            await safe_send(ctx, content=f"{ctx.author.mention}, invalid URL.")
            return
        async with ctx.typing():
            guidance = await get_ai_guidance(url)
            lines = guidance.splitlines()
            verdict_line = lines[0] if lines else "Keep/Skip"
            reason_line = lines[1] if len(lines) > 1 else "No reason provided."
            embed = verdict_embed(url, verdict_line, reason_line, author_mention=ctx.author.mention)
            await safe_send(ctx, embed=embed)

    @commands.hybrid_command(name="stats", description="Show link stats")
    async def show_stats(self, ctx: commands.Context):
        links = storage.get_saved_links()
        if not links:
            await safe_send(ctx, content="No data for statistics!")
            return
        total = len(links)
        categories = {}
        domains = {}
        authors = {}
        for l in links:
            cat = l.get("category", "Uncategorized")
            categories[cat] = categories.get(cat, 0) + 1
            try:
                domain = urlparse(l["url"]).netloc. lower()
                if domain. startswith("www."):
                    domain = domain[4:]
                domains[domain] = domains.get(domain, 0) + 1
            except Exception:
                pass
            author = l.get("author", "Unknown")
            authors[author] = authors.get(author, 0) + 1
        embed = make_embed(title="📊 Link Stats", description=f"Total links:  **{total}**", color=discord.Color.gold())
        embed.add_field(name="Top Categories", value="\n".join([f"• {k}:  {v}" for k, v in sorted(categories.items(), key=lambda x: -x[1])[:5]]) or "None", inline=False)
        embed.add_field(name="Top Domains", value="\n".join([f"• {k}: {v}" for k, v in sorted(domains.items(), key=lambda x: -x[1])[:5]]) or "None", inline=False)
        embed.add_field(name="Top Contributors", value="\n".join([f"• {k}: {v}" for k, v in sorted(authors.items(), key=lambda x: -x[1])[:5]]) or "None", inline=False)
        await safe_send(ctx, embed=embed)

    @commands.hybrid_command(name="recent", description="Show 5 most recent links")
    async def show_recent(self, ctx: commands.Context):
        links = storage.get_saved_links()
        if not links:
            await safe_send(ctx, content="No links saved yet!")
            return
        recent = links[-5:][: :-1]
        response = "**🕒 Recently Saved:**\n\n"
        for i, l in enumerate(recent, 1):
            response += f"{i}. **[{l. get('category','Uncategorized')}]** {l['url']}\n   *by {l.get('author','Unknown')} at {l.get('timestamp','')}*\n"
        await safe_send(ctx, content=response)

    @commands.hybrid_command(name="audit_server", description="(Admin) Run an AI audit for a topic")
    @commands.has_permissions(manage_guild=True)
    async def audit_server(self, ctx: commands.Context, *, topic: str = "full server"):
        await ctx.defer()
        guild = ctx.guild
        if not guild:
            await safe_send(ctx, content="This must be used in a server.")
            return
        ai_resp = await ai_server_audit(guild, topic=topic, extra_context=f"Requested by {ctx.author.display_name}.  Site: {COMMUNITY_LEARNING_URL}")
        preview = "\n". join(ai_resp. splitlines()[:8])
        await safe_send(ctx, embed=make_embed(f"AI Audit:  {topic}", preview[: 1500], discord.Color.green()))
        for chunk in (ai_resp[i:i+1900] for i in range(0, len(ai_resp), 1900)):
            await safe_send(ctx, content=chunk)

# ---------------------------------------------------------------------------
# Events & startup
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    ready_banner = f"""
╔═══════════════════════════════════════════════╗
║  🤖 DIGITAL LABOUR BOT ONLINE                 ║
╚═══════════════════════════════════════════════╝
>_ User: {bot.user} (ID: {bot.user.id})
>_ PID: {os.getpid()}
>_ Session: {SESSION_ID[: 8]}
>_ AI:   {'ENABLED ✅' if AI_ENABLED else 'DISABLED ⚠️'}
>_ Guilds: {len(bot.guilds)}
╚═══════════════════════════════════════════════╝
"""
    logger.info(ready_banner)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await safe_send(ctx, content="Missing argument!  Check `! help`.")
    elif isinstance(error, commands.CheckFailure):
        await safe_send(ctx, content="You don't have permission.")
    elif isinstance(error, commands.BadArgument):
        await safe_send(ctx, content="Invalid argument type.")
    else:
        logger.error(f"Command error: {error}", exc_info=True)

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN not set!")
    logger.info("Starting Labour Bot...")
    async with bot:
        await bot. start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
