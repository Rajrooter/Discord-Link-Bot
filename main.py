#!/usr/bin/env python3
"""
Digital Labour - main.py
Features:  embed UI, 4-button link actions, link shortening, multi-guild scoping,
exports (CSV/PDF placeholder), expiry/archiving with background sweeper,
context menus at top-level, document summarization, AI link verdicts. 
"""

import asyncio
import datetime
import io
import os
import re
import time
import uuid
import urllib.parse
import csv
from typing import Optional, List, Dict, Callable, Awaitable
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def _has_model(client, model_name: str) -> bool:
    try:
        return hasattr(client, "models") and hasattr(client.models, "generate_content")
    except Exception:
        return False


if GEMINI_API_KEY and genai is not None:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    AI_ENABLED = bool(_has_model(ai_client, "gemini-2.0-flash-exp"))
    if AI_ENABLED: 
        logger.info("✅ Google Gemini AI enabled")
    else:
        logger.warning("⚠️ AI client missing generate_content; AI disabled")
else:
    ai_client = None
    AI_ENABLED = False
    logger.warning("⚠️ AI disabled - Add GEMINI_API_KEY to enable")

AUTO_DELETE_ENABLED = os.environ.get("AUTO_DELETE_ENABLED", "1") == "1"
try:
    AUTO_DELETE_SECONDS_DEFAULT = int(os.environ.get("AUTO_DELETE_AFTER", "5"))
except ValueError:
    AUTO_DELETE_SECONDS_DEFAULT = 5

BATCH_WINDOW_SECONDS = 3
BATCH_THRESHOLD_DEFAULT = 5
CONFIRM_TIMEOUT = 4
AI_PROMPT_LIMIT = 12000

RULES_FILE = "server_rules.txt"

# Fixed URL regex - more reliable pattern
URL_REGEX = r'https?://[^\s<>"{}|\\^`\[\]]+'

IGNORED_EXTENSIONS = ['.gif', '.png', '.jpg', '. jpeg', '.webp', '.bmp', '.mp4', '.mov', '.avi']

COMMUNITY_LEARNING_URL = os.environ.get("COMMUNITY_LEARNING_URL", "https://share.google/yf57dJNzEyAVM0asz")

MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/html",
    "application/pdf",
    "application/rtf",
    "application/msword",
    "application/vnd. openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "application/octet-stream",
}
EXCEL_TYPES = {". xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".csv"}
HTML_TYPES = {".html", ".htm", ".xhtml", ".asp", ".aspx"}
TEXTISH_TYPES = {".txt", ".rtf", ". doc", ".docx", ".wps", ".csv"}

SECURITY_ALERT_CHANNEL_ID = int(os.environ. get("SECURITY_ALERT_CHANNEL_ID", "0") or 0)


# ---------------------------------------------------------------------------
# Guild Config Helper
# ---------------------------------------------------------------------------

class GuildConfig: 
    """Simple per-guild configuration manager."""
    
    def __init__(self):
        self._configs:  Dict[int, Dict] = {}
    
    def load(self, guild_id: Optional[int]) -> Dict:
        if guild_id is None:
            return {}
        return self._configs.get(guild_id, {})
    
    def save(self, guild_id: Optional[int], config:  Dict):
        if guild_id is not None:
            self._configs[guild_id] = config
    
    def get_value(self, guild_id: Optional[int], key: str, default):
        cfg = self.load(guild_id)
        return cfg.get(key, default)


guild_config = GuildConfig()


# ---------------------------------------------------------------------------
# AI Helper Functions
# ---------------------------------------------------------------------------

async def ai_call(prompt: str, max_retries: int = 2, timeout: float = 15.0) -> str:
    """Make an AI call with retries and timeout."""
    if not AI_ENABLED or ai_client is None: 
        return "AI is not available."
    
    for attempt in range(max_retries):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    ai_client.models.generate_content,
                    model="gemini-2.0-flash-exp",
                    contents=prompt[: AI_PROMPT_LIMIT]
                ),
                timeout=timeout
            )
            if response and hasattr(response, 'text'):
                return response.text
            return "No response from AI."
        except asyncio. TimeoutError: 
            logger.warning(f"AI call timeout (attempt {attempt + 1})")
        except Exception as e: 
            logger.error(f"AI call error:  {e}")
    return "AI request failed after retries."


async def get_ai_guidance(url: str) -> str:
    """Get AI verdict on a URL."""
    if not AI_ENABLED: 
        return "Keep\nAI analysis unavailable - manual review recommended."
    
    prompt = (
        f"Analyze this URL for safety and educational value.  "
        f"First line: 'Keep' or 'Skip'.  Second line: Brief reason (max 50 words).\n"
        f"URL: {url}"
    )
    return await ai_call(prompt, max_retries=2, timeout=12.0)


async def ai_improve_rules(rules_text: str, server_summary: str) -> str:
    """Get AI suggestions for improving server rules."""
    prompt = (
        f"Review these Discord server rules and suggest improvements.  "
        f"Be concise, practical, and kid-friendly.\n"
        f"Server:  {server_summary}\n"
        f"Current rules:\n{rules_text[: 3000]}"
    )
    return await ai_call(prompt, max_retries=2, timeout=15.0)


async def ai_server_audit(guild:  discord.Guild, topic: str = "general", extra_context: str = "") -> str:
    """Run an AI audit on server structure."""
    channels = [ch. name for ch in guild. text_channels[: 20]]
    prompt = (
        f"Audit this Discord server for '{topic}'.\n"
        f"Server:  {guild.name}, Members: {guild.member_count}\n"
        f"Channels: {', '.join(channels)}\n"
        f"{extra_context}\n"
        f"Provide actionable recommendations."
    )
    return await ai_call(prompt, max_retries=2, timeout=20.0)


async def ai_avatar_advice(desired_tone: str = "professional") -> str:
    """Get AI advice on avatar selection."""
    prompt = (
        f"Suggest Discord avatar ideas for a {desired_tone} tone.  "
        f"Give 5 brief suggestions with reasoning."
    )
    return await ai_call(prompt, max_retries=2, timeout=10.0)


async def ai_channel_suggestions(guild: discord.Guild, focus: str = "") -> str:
    """Get AI suggestions for new channels."""
    existing = [ch.name for ch in guild.text_channels[:15]]
    prompt = (
        f"Suggest new Discord channels for this server.\n"
        f"Existing:  {', '.join(existing)}\n"
        f"Focus: {focus}\n"
        f"Provide 5 channel suggestions with descriptions."
    )
    return await ai_call(prompt, max_retries=2, timeout=12.0)


async def download_bytes(url: str) -> Optional[bytes]:
    """Download file bytes from URL."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    content_length = resp.headers.get('Content-Length')
                    if content_length and int(content_length) > MAX_DOWNLOAD_BYTES: 
                        return None
                    return await resp.read()
    except Exception as e:
        logger.error(f"Download failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def security_alert(bot: commands.Bot, message: str):
    logger.warning(f"[SECURITY] {message}")
    if not SECURITY_ALERT_CHANNEL_ID:
        return
    try:
        ch = bot.get_channel(SECURITY_ALERT_CHANNEL_ID)
        if ch:
            await safe_send(ch, content=f"🚨 **Security Alert:** {message}")
    except Exception as e:
        logger. error(f"Failed to send security alert:  {e}")


def error_message(msg: str) -> str:
    return f"⚠️ **Error:** {msg}"


def ratelimit_message(wait_s: float) -> str:
    return f"⏳ **Slow down!** Please wait {wait_s:. 1f} seconds before using this again."


def verdict_message(link: str, verdict: str, reason:  str, author_mention: str = "") -> str:
    status = "✅" if "Keep" in verdict else "⚠️"
    mention_text = f"\n_{author_mention}_" if author_mention else ""
    return f"{status} **{verdict}**\n{reason}\n\n`{link[: 100]}{'...' if len(link) > 100 else ''}`{mention_text}"


def multi_link_message(count: int) -> str:
    return f"📎 **{count} links detected! **\nSelect the links you want to save using the dropdown below."


def summarize_progress_message(filename: str) -> str:
    return f"📝 **Summarizing:** {filename}\nPlease wait..."


def summarize_result_message(filename:  str, body: str, requester: str) -> str:
    return f"📝 **Summary:   {filename}**\n\n{body}\n\n_Summarized for {requester}_"


async def link_preview(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or "link"
        path = parsed.path[: 60] + ("..." if len(parsed.path) > 60 else "")
        return f"🔗 **Preview:** `{host}{path}`"
    except Exception: 
        return "🔗 Preview unavailable."


async def ack_interaction(interaction: discord.Interaction, *, ephemeral: bool = True):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
    except Exception: 
        pass


def make_verdict_embed(link: str, verdict_line: str, reason_line: str, preview: str) -> discord.Embed:
    embed = discord. Embed(
        title=verdict_line,
        description=reason_line,
        color=0x00C853 if "Keep" in verdict_line else 0xFFA000
    )
    embed.add_field(name="Link", value=f"`{link}`", inline=False)
    if preview:
        embed.add_field(name="Preview", value=preview, inline=False)
    embed.set_footer(text="Choose:  Save now • Save later • Shorten • Cancel")
    return embed


def make_cyberpunk_help_embed() -> discord.Embed:
    embed = discord.Embed(title="", description="", color=0x00FF9C)
    embed.description = """```ansi
[2;36m╔═══════════════════════════════════════════════╗[0m
[2;35m║[0m  [1;36m▓█████▄  ██▓  ▄████  ██▓▄▄▄█████▓ ▄▄▄       ██▓    [0m [2;35m║[0m
[2;35m║[0m  [1;36m▒██▀ ██▌▓██▒ ██▒ ▀█▒▓██▒▓  ██▒ ▓▒▒████▄    ▓██▒    [0m [2;35m║[0m
[2;35m║[0m  [1;35m░██   █▌▒██▒▒██░▄▄▄░▒██▒▒ ▓██░ ▒░▒██▄▀█▄  ▒██░    [0m [2;35m║[0m
[2;35m║[0m  [1;35m░▓█▄   ▌░██░░▓█  ██▓░██░░ ▓██▓ ░ ░██▄▄▄▄██ ▒██░    [0m [2;35m║[0m
[2;35m║[0m  [1;33m░▒████▓ ░██░░▒▓███▀▒░██░  ▒██▒ ░  ▓█   ▓██▒░██████▒[0m [2;35m║[0m
[2;35m║[0m  [1;33m ▒▒▓  ▒ ░▓   ░▒   ▒ ░▓    ▒ ░░    ▒▒   ▓▒█░░ ▒░▓  ░[0m [2;35m║[0m
[2;36m╚═══════════════════════════════════════════════╝[0m
[1;32m>_[0m [1;37mLABOUR BOT v3.0[0m [2;33m// NEURAL LINK MANAGER[0m
[2;35m>_[0m [2;37mStatus:[0m [1;32m[ONLINE][0m [2;33m// Session:   ACTIVE[0m
```"""
    embed.add_field(
        name="\u200b",
        value="""```ansi
[1;36m┌─[0m [1;37mLINK_OPERATIONS[0m [1;36m─────────────────────────────────┐[0m
[1;32m│ ▸[0m [1;33m/pendinglinks[0m
[1;32m│ ▸[0m [1;33m/category[0m <name>
[1;32m│ ▸[0m [1;33m/cancel[0m
[1;32m│ ▸[0m [1;33m/getlinks[0m [category]
[1;32m│ ▸[0m [1;33m/deletelink[0m <number>
[1;36m└───────────────────────────────────────────────┘[0m
```""",
        inline=False,
    )
    embed.add_field(
        name="\u200b",
        value="""```ansi
[1;35m┌─[0m [1;37mANALYSIS_MODULES[0m [1;35m─────────────────────────────────┐[0m
[1;32m│ ▸[0m [1;33m/analyze[0m <url>
[1;32m│ ▸[0m [1;33m/searchlinks[0m <term>
[1;32m│ ▸[0m [1;33m/stats[0m
[1;32m│ ▸[0m [1;33m/recent[0m
[1;35m└───────────────────────────────────────────────┘[0m
```""",
        inline=False,
    )
    embed.add_field(
        name="\u200b",
        value="""```ansi
[1;33m┌─[0m [1;37mORGANIZATION_SYSTEMS[0m [1;33m─────────────────────────────┐[0m
[1;32m│ ▸[0m [1;33m/categories[0m
[1;32m│ ▸[0m [1;33m/deletecategory[0m <name>
[1;32m│ ▸[0m [1;33m/clearlinks[0m [ADMIN]
[1;33m└───────────────────────────────────────────────┘[0m
```""",
        inline=False,
    )
    embed.add_field(
        name="\u200b",
        value="""```ansi
[2;36m┌─[0m [1;37mSYSTEM_FEATURES[0m [2;36m──────────────────────────────────┐[0m
[1;32m│ ◆[0m Auto Link Detection
[1;32m│ ◆[0m AI Safety Check
[1;32m│ ◆[0m Document Summarization (. pdf/. docx/. txt/. csv/. xls[x])
[1;32m│ ◆[0m Burst Protection
[1;32m│ ◆[0m Smart Categorization
[2;36m└───────────────────────────────────────────────┘[0m
```""",
        inline=False,
    )
    embed.add_field(
        name="\u200b",
        value="""```ansi
[2;35m╔═══════════════════════════════════════════════╗[0m
[2;35m║[0m ⚡ TIP:  Mention me + question for AI help      [2;35m║[0m
[2;35m║[0m ⚡ Drop a link → AI verdict → Save/Ignore      [2;35m║[0m
[2;35m║[0m ⚡ Upload document → Click summarize button    [2;35m║[0m
[2;35m╚═══════════════════════════════════════════════╝[0m
[2;33m>_[0m Powered by Gemini AI // Made for Digital Labour
```""",
        inline=False,
    )
    embed.set_footer(text="[SYSTEM] Neural Link Established • Use /cmdinfo <command> for details")
    embed.timestamp = datetime.datetime.utcnow()
    return embed


def make_compact_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚡ LABOUR BOT // COMMAND INDEX",
        description="`Neural Link Manager v3.0`",
        color=0x5865F2
    )
    embed.add_field(
        name="🔗 Link Operations",
        value="`/pendinglinks` • `/category` • `/cancel` • `/getlinks` • `/deletelink`",
        inline=False
    )
    embed.add_field(
        name="🔍 Analysis & Search",
        value="`/analyze` • `/searchlinks` • `/stats` • `/recent`",
        inline=False
    )
    embed.add_field(
        name="🗂️ Organization",
        value="`/categories` • `/deletecategory` • `/clearlinks`",
        inline=False
    )
    embed.add_field(
        name="✨ Smart Features",
        value=(
            "→ Auto-detect & AI check links\n"
            "→ Summarize documents (. pdf/.docx/. txt/.csv/.xls[x])\n"
            "→ Mention me for AI help\n"
            "→ Burst protection queuing"
        ),
        inline=False
    )
    embed.set_footer(text="💡 Drop any link for AI analysis • Upload docs for instant summary")
    embed.timestamp = datetime. datetime.utcnow()
    return embed


async def safe_send(target, content=None, embed=None, ephemeral=False, view=None, **extra):
    try:
        kwargs = {"content": content, "embed": embed}
        kwargs.update(extra)
        if isinstance(view, discord.ui.View):
            kwargs["view"] = view
        if hasattr(target, "send"):
            return await target.send(**kwargs)
        if hasattr(target, "response"):
            return await target.response.send_message(ephemeral=ephemeral, **kwargs)
        if hasattr(target, "followup"):
            return await target.followup.send(ephemeral=ephemeral, **kwargs)
    except Exception as e: 
        logger.error(f"Send failed: {e}")
    return None


def filter_links_by_guild(links, guild_id:  Optional[int]):
    if guild_id is None:
        return links
    scoped = []
    for l in links:
        gid = l.get("guild_id")
        if gid is None or gid == guild_id:
            scoped.append(l)
    return scoped


def export_links_csv(links):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["url", "category", "author", "timestamp", "archived", "expires_at"])
    for l in links:
        writer.writerow([
            l. get("url", ""),
            l.get("category", ""),
            l.get("author", ""),
            l.get("timestamp", ""),
            l.get("archived", False),
            l.get("expires_at", "")
        ])
    buf.seek(0)
    return buf. getvalue().encode("utf-8")


def export_links_pdf_placeholder():
    return b"PDF export not implemented; install reportlab to enable real PDF output."


# ---------------------------------------------------------------------------
# Extraction/summarization helpers
# ---------------------------------------------------------------------------

async def shorten_link(url: str) -> Optional[str]:
    try:
        safe_url = urllib.parse.quote(url, safe=": /?#[]@! $&'()*+,;=")
        api = f"http://tinyurl.com/api-create.php?url={safe_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api, timeout=8) as resp:
                if resp.status == 200:
                    short = (await resp.text()).strip()
                    if short. startswith("http"):
                        return short
    except Exception as e:
        logger.debug(f"shorten_link error: {e}")
    return None


def excel_preview_table(data:  bytes, filename: str, max_rows: int = 5) -> Optional[str]:
    try:
        import pandas as pd
        ext = os.path.splitext(filename. lower())[1]
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(data))
        else:
            df = pd.read_excel(io.BytesIO(data), engine=None)
        if df.empty:
            return "*(No rows to display)*"
        return df.head(max_rows).to_markdown(index=False)
    except Exception as e:
        logger.debug(f"excel_preview_table error:  {e}")
        return None


def extract_text_from_bytes(filename: str, data: bytes) -> Optional[str]:
    name = filename.lower()
    try:
        ext = os.path. splitext(name)[1]
        if ext in EXCEL_TYPES: 
            try:
                import pandas as pd
                if ext == ".csv": 
                    df = pd.read_csv(io.BytesIO(data))
                else:
                    df = pd. read_excel(io.BytesIO(data), engine=None)
                if df.empty:
                    return "(No rows)"
                return df. head(20).to_csv(index=False)
            except Exception as e:
                logger.debug(f"Excel/CSV extraction error: {e}")
                if ext == ".csv":
                    try:
                        return data.decode("utf-8", errors="replace")
                    except Exception:
                        return data.decode("latin-1", errors="replace")
                return None
        if name.endswith(".txt"):
            try:
                return data.decode("utf-8", errors="replace")
            except Exception:
                return data.decode("latin-1", errors="replace")
        if name.endswith(". pdf"):
            try:
                from PyPDF2 import PdfReader
                with io.BytesIO(data) as bio:
                    reader = PdfReader(bio)
                    pages = [p.extract_text() or "" for p in reader.pages]
                    return "\n". join(pages)
            except Exception as e:
                logger. debug(f"PDF extraction error: {e}")
                return None
        if name. endswith(".docx"):
            try:
                import docx
                with io.BytesIO(data) as bio:
                    doc = docx.Document(bio)
                    return "\n".join(p.text for p in doc.paragraphs)
            except Exception as e:
                logger.debug(f"DOCX extraction error: {e}")
                return None
        if name.endswith((".html", ".htm", ".xhtml", ".asp", ".aspx")):
            try: 
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(data, "html.parser")
                return soup.get_text(" ", strip=True)
            except Exception as e:
                logger. debug(f"HTML extraction error: {e}")
                return None
        if name.endswith(". rtf"):
            try:
                import striprtf
                return striprtf.rtf_to_text(data. decode("latin-1", errors="ignore"))
            except Exception as e:
                logger.debug(f"RTF extraction error: {e}")
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
        "Summarize in <=10 lines.  Be clear, kid-friendly, concise.\n"
        "Sections:  Markdown overview, Content, Red Flags, Conclusion, Real-life tip.  No filler, no random additions.\n"
        f"Context: {context_note}\n\nContent:\n{excerpt}"
    )
    return await ai_call(prompt, max_retries=3, timeout=18.0)


def is_media_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        path = parsed.path. lower()
        for ext in IGNORED_EXTENSIONS: 
            if path.endswith(ext):
                return True
        media_domains = [
            'giphy.com', 'tenor.com', 'imgur.com', 'gyazo.com',
            'streamable.com', 'clippy. gg', 'cdn.discordapp.com', 'media.discordapp.net'
        ]
        domain = parsed.netloc.lower()
        return any(md in domain for md in media_domains)
    except Exception: 
        return False


def load_rules() -> str:
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError: 
        return "📒 Server Rules:\n1. Be respectful.\n2. Share educational content only.\n3. No spam."


# ---------------------------------------------------------------------------
# Intents and prefix
# ---------------------------------------------------------------------------
intents = discord. Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True


def get_prefix(bot, message):
    prefixes = ["! "]
    return commands.when_mentioned_or(*prefixes)(bot, message)


# ---------------------------------------------------------------------------
# Context menu callbacks (top-level)
# ---------------------------------------------------------------------------

@app_commands.context_menu(name="Summarize/Preview Document")
async def summarize_preview_ctx(interaction: discord. Interaction, message:  discord.Message):
    cog = interaction.client. get_cog("LinkManager")
    if not cog:
        await interaction.response.send_message("⚠️ Cog not ready.", ephemeral=True)
        return
    await cog. handle_summarize_preview_ctx(interaction, message)


@app_commands.context_menu(name="Analyze Link (AI)")
async def analyze_link_ctx(interaction: discord. Interaction, message:  discord.Message):
    cog = interaction.client.get_cog("LinkManager")
    if not cog:
        await interaction.response. send_message("⚠️ Cog not ready.", ephemeral=True)
        return
    await cog. handle_analyze_link_ctx(interaction, message)


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class MyBot(commands.Bot):
    async def setup_hook(self):
        await self.add_cog(LinkManagerCog(self))
        logger.info("✅ LinkManager cog added")

        try:
            if hasattr(storage, "prune_orphaned_pending"):
                pruned = await asyncio.to_thread(storage. prune_orphaned_pending)
                logger.info(f"🧹 Pruned orphaned pending links: {pruned}")
            elif hasattr(storage, "clear_orphaned_pending"):
                pruned = await asyncio. to_thread(storage.clear_orphaned_pending)
                logger.info(f"🧹 Pruned orphaned pending links: {pruned}")
        except Exception as e: 
            logger.warning(f"Startup prune failed: {e}")

        cmd_names = [c.qualified_name for c in self.tree.walk_commands()]
        logger.info(f"🔧 App commands loaded (pre-sync): {cmd_names}")

        self.tree.add_command(summarize_preview_ctx)
        self.tree.add_command(analyze_link_ctx)

        synced_commands = []
        try:
            global_synced = await self. tree.sync()
            synced_commands. extend(global_synced)
            logger. info(f"✅ Synced {len(global_synced)} commands globally:  {[c.name for c in global_synced]}")
            if not global_synced:
                logger. warning("⚠️ No global commands synced.  Check token scope or restart.")
        except Exception as e:
            logger.error(f"Global sync failed: {e}")

        test_guild_id = os.environ.get("TEST_GUILD_ID")
        if test_guild_id:
            try: 
                guild_id = int(test_guild_id)
                guild = discord. Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                guild_synced = await self. tree.sync(guild=guild)
                logger.info(f"✅ Synced {len(guild_synced)} commands to test guild {guild_id}:  {[c.name for c in guild_synced]}")
                if not guild_synced:
                    logger.warning(f"⚠️ No commands synced to test guild {guild_id}.")
            except Exception as e:
                logger.error(f"Test guild sync failed:  {e}")

        logger.info(f"✅ Total commands synced: {len(synced_commands)}")


bot = MyBot(command_prefix=get_prefix, intents=intents, help_command=None)
bot.remove_command("help")


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------

class CategoryModal(discord.ui. Modal, title="Save Summary to Category"):
    category = discord.ui.TextInput(label="Category name", required=True, max_length=60)

    def __init__(self, on_submit_cb:  Callable[[str], Awaitable[None]]):
        super().__init__()
        self.on_submit_cb = on_submit_cb

    async def on_submit(self, interaction: discord. Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.on_submit_cb(str(self.category))
        await safe_send(interaction. followup, content=f"✅ Saved to category **{self.category}**", ephemeral=True)


class SummaryActionView(discord.ui. View):
    def __init__(self, filename: str, summary:  str, requester: discord.User, cog):
        super().__init__(timeout=180)
        self.filename = filename
        self.summary = summary
        self.requester = requester
        self.cog = cog

    @discord.ui.button(label="Export (. txt)", style=discord.ButtonStyle.primary, emoji="📤")
    async def export_button(self, interaction:  discord.Interaction, button: discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        buf = io.BytesIO(self.summary.encode("utf-8", errors="replace"))
        buf.seek(0)
        await interaction.followup.send(
            content="📎 Exported summary:",
            file=discord.File(buf, filename=f"{os.path.splitext(self.filename)[0]}_summary.txt"),
            ephemeral=True
        )

    @discord.ui.button(label="Save to Category", style=discord.ButtonStyle.success, emoji="🗂️")
    async def category_button(self, interaction: discord. Interaction, button: discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)

        async def on_submit(cat_name: str):
            entry = {
                "url": f"(summary of {self.filename})",
                "timestamp": datetime.datetime. utcnow().isoformat(),
                "author": str(self.requester),
                "category": cat_name,
                "summary": self.summary[: 4000],
                "guild_id": interaction.guild.id if interaction. guild else None,
                "archived": False,
                "expires_at":  None,
            }
            await asyncio.to_thread(storage.add_saved_link, entry)
            await asyncio.to_thread(storage.add_link_to_category, cat_name, entry["url"])

        await interaction.response.send_modal(CategoryModal(on_submit_cb=on_submit))


class SummarizeView(discord.ui.View):
    def __init__(self, file_url: str, filename: str, author_id: int, context_note: str, cog):
        super().__init__(timeout=300)
        self.file_url = file_url
        self.filename = filename
        self.author_id = author_id
        self.context_note = context_note
        self. cog = cog
        self.message = None

    async def interaction_check(self, interaction: discord. Interaction) -> bool:
        if interaction.user. id != self.author_id:
            await safe_send(interaction. response, content=error_message("Only the uploader can request summarization. "), ephemeral=True)
            return False
        return True

    @discord. ui.button(label="Summarize", style=discord.ButtonStyle.green, emoji="📝")
    async def summarize_button(self, interaction: discord.Interaction, button: discord.ui. Button):
        if getattr(self, "_done", False):
            await ack_interaction(interaction, ephemeral=True)
            return
        self._done = True
        await ack_interaction(interaction, ephemeral=True)
        try:
            data = await download_bytes(self.file_url)
            if not data:
                await safe_send(interaction.followup, content=error_message("Failed to download the file."), ephemeral=True)
                return
            ext = os.path. splitext(self. filename. lower())[1]
            if ext in EXCEL_TYPES: 
                table_md = excel_preview_table(data, self.filename, max_rows=5)
                if table_md: 
                    await safe_send(interaction.channel, content=f"🧾 **Preview of {self.filename} (first rows):**\n```markdown\n{table_md}\n```")
            progress = await safe_send(interaction.followup, content=summarize_progress_message(self.filename), ephemeral=True)
            summary = await summarize_document_bytes(self.filename, data, context_note=self.context_note)
            result_msg = summarize_result_message(self.filename, summary[: 3500], interaction.user.mention)
            await safe_send(interaction.channel, content=result_msg)
            if progress and hasattr(progress, "edit"):
                try:
                    await progress.edit(content="✅ **Done** - Summary posted.")
                except Exception: 
                    pass
        except Exception as e:
            logger. error(f"Summarize button failed: {e}")
            await safe_send(interaction.followup, content=error_message("Summarization failed. Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child. disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord. ui.button(label="Cancel", style=discord. ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord. Interaction, button:  discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        for child in self.children:
            child. disabled = True
        try: 
            await interaction.message.edit(view=self)
        except Exception:
            pass
        try:
            if getattr(self, "message", None):
                await self.message.edit(view=self)
        except Exception:
            pass


class DisclaimerView(discord.ui.View):
    def __init__(self, links: list, author_id: int, original_message, cog):
        super().__init__(timeout=60)
        self.links = links
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.message = None

    async def interaction_check(self, interaction):
        if interaction. user.id != self.author_id:
            await safe_send(interaction.response, content=error_message("This is not for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Save links", style=discord. ButtonStyle.green, emoji="✅")
    async def yes_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            await self.message.delete()
        except Exception:
            pass
        links_data = [{"url": link} for link in self. links]
        selection_view = MultiLinkSelectView(links_data, self.author_id, self. original_message, self.cog)
        prompt_msg = await safe_send(interaction.channel, content=multi_link_message(len(self.links)), view=selection_view)
        if prompt_msg: 
            selection_view.message = prompt_msg

    @discord.ui.button(label="Ignore", style=discord. ButtonStyle.secondary, emoji="❌")
    async def no_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            await self. message.delete()
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
        if interaction. user.id != self.author_id:
            await safe_send(interaction.response, content=error_message("This button is not for you."), ephemeral=True)
            return False
        return True

    @discord.ui. button(label="Save now", style=discord. ButtonStyle.success, emoji="💾")
    async def save_now(self, interaction, button):
        if getattr(self, "_done", False):
            await ack_interaction(interaction, ephemeral=True)
            return
        self._done = True
        await ack_interaction(interaction, ephemeral=True)
        try:
            await asyncio.to_thread(storage.delete_pending_link_by_id, self. pending_db_id)
            if interaction.message. id in self.cog.pending_links:
                del self.cog. pending_links[interaction.message.id]
            gid = interaction.guild.id if interaction. guild else None
            if gid in self.cog. guild_pending_counts and self.cog. guild_pending_counts[gid] > 0:
                self.cog. guild_pending_counts[gid] -= 1
            self.cog.links_to_categorize[self.author_id] = {"link": self.link, "message": self.original_message}
            prefix = await self.cog._get_preferred_prefix(self.original_message) if self.original_message else "!"
            await safe_send(interaction.followup, content=f"✅ Link marked for saving!  Use `{prefix}category <name>` to finalize.", ephemeral=True)
        except Exception as e:
            logger.error(f"Save failed: {e}")
            await safe_send(interaction.followup, content=error_message("Failed to mark link for saving. Please try again."), ephemeral=True)
        finally:
            for child in self. children:
                child.disabled = True
            try:
                await interaction.message. edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Save later", style=discord. ButtonStyle.primary, emoji="🕒")
    async def save_later(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        await safe_send(interaction.followup, content="🕒 Saved for later review.  Use `/pendinglinks` to process.", ephemeral=True)

    @discord.ui.button(label="Shorten link", style=discord. ButtonStyle.secondary, emoji="🔗")
    async def shorten_btn(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        short = await shorten_link(self.link)
        if short:
            await safe_send(interaction. followup, content=f"📎 Shortened link:\n{short}", ephemeral=True)
        else:
            await safe_send(interaction.followup, content=error_message("Could not shorten link.  Try again later."), ephemeral=True)

    @discord.ui. button(label="Cancel", style=discord. ButtonStyle.danger, emoji="❌")
    async def cancel_btn(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            if self.original_message:
                try:
                    await self.original_message.delete()
                except Exception:
                    pass
            try:
                await asyncio.to_thread(storage.delete_pending_link_by_id, self. pending_db_id)
            except Exception as e:
                logger.error(f"Pending delete failed: {e}")
            if interaction.message.id in self.cog.pending_links:
                del self. cog.pending_links[interaction.message.id]
            gid = interaction.guild.id if interaction. guild else None
            if gid in self.cog.guild_pending_counts and self.cog. guild_pending_counts[gid] > 0:
                self.cog. guild_pending_counts[gid] -= 1
            try:
                await interaction.message.delete()
            except Exception:
                pass
            await safe_send(interaction.followup, content="❌ Prompt removed.", ephemeral=True)
        except Exception as e: 
            logger.error(f"Cancel failed:  {e}")
            await safe_send(interaction.followup, content=error_message("Could not cancel. "), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True


class MultiLinkSelectView(discord.ui.View):
    def __init__(self, links: list, author_id: int, original_message, cog):
        super().__init__(timeout=300)
        self.links = links
        self.author_id = author_id
        self.original_message = original_message
        self. cog = cog
        self.selected_links = []
        self.message = None
        options = []
        max_options = min(len(links), 25)
        for idx in range(max_options):
            url = links[idx]. get("url", "")
            label = f"Link {idx+1}"
            desc = url if len(url) <= 100 else url[:97] + "..."
            options. append(discord.SelectOption(label=label, value=str(idx), description=desc))
        if not options:
            options. append(discord.SelectOption(label="No valid links", value="0", description="Error"))
        select = discord.ui. Select(
            placeholder=f"Select links to save ({min(len(links),25)} available)",
            min_values=1,
            max_values=min(len(options), 25),
            options=options,
            custom_id="link_selector"
        )
        self.add_item(select)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await safe_send(interaction. response, content=error_message("Not your selection."), ephemeral=True)
            return False
        if interaction.data.get("custom_id") == "link_selector": 
            await ack_interaction(interaction, ephemeral=False)
            values = interaction.data. get("values", [])
            self.selected_links = [int(v) for v in values]
            if self.selected_links:
                confirm_view = ConfirmMultiLinkView(self.links, set(self.selected_links), self.author_id, self. original_message, self.cog)
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
    def __init__(self, links: list, selected_indices: set, author_id: int, original_message, cog):
        super().__init__(timeout=60)
        self.links = links
        self.selected_indices = selected_indices
        self.author_id = author_id
        self.original_message = original_message
        self. cog = cog
        self.message = None

    @discord.ui.button(label="Save selected", style=discord. ButtonStyle.green, emoji="💾")
    async def confirm_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        saved_count = 0
        for idx in self. selected_indices: 
            try:
                link = self.links[idx]["url"]
                pending_entry = {
                    "user_id": interaction.user.id,
                    "link": link,
                    "channel_id": interaction. channel.id,
                    "original_message_id":  self.original_message.id if self. original_message else 0,
                    "timestamp": datetime.datetime. utcnow().isoformat()
                }
                pending_id = await asyncio. to_thread(storage.add_pending_link, pending_entry)
                saved_count += 1
                self.cog.links_to_categorize[interaction.user.id] = {
                    "link": link,
                    "message": self.original_message,
                    "pending_db_id": pending_id
                }
                await safe_send(
                    interaction.channel,
                    content=(
                        f"{interaction.user.mention}, link {saved_count} saved to queue!\n"
                        f"Use `!category <name>` to save or `!cancel` to skip.\n"
                        f"`{link[: 100]}{'...' if len(link) > 100 else ''}`"
                    )
                )
            except Exception as e: 
                logger.error(f"Error saving link {idx}:  {e}")
                await safe_send(interaction.channel, content=error_message("Failed to save one of the links. Please try again. "))
        for child in self.children:
            child. disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception: 
            pass

    @discord.ui. button(label="Cancel", style=discord. ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception: 
            pass


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, link: str, author_id: int, original_message, pending_db_id:  str, bot_msg_id: int, cog):
        super().__init__(timeout=60)
        self.link = link
        self.author_id = author_id
        self. original_message = original_message
        self.pending_db_id = pending_db_id
        self.bot_msg_id = bot_msg_id
        self.cog = cog
        self. message = None

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            if self.original_message:
                try: 
                    await self.original_message. delete()
                except Exception:
                    pass
            try: 
                bot_msg = await interaction.channel.fetch_message(self.bot_msg_id)
                await bot_msg. delete()
            except Exception:
                pass
            try:
                await asyncio.to_thread(storage.delete_pending_link_by_id, self. pending_db_id)
            except Exception as e:
                logger.error(f"Pending delete failed: {e}")
            if self.bot_msg_id in self.cog. pending_links: 
                del self.cog.pending_links[self.bot_msg_id]
            gid = interaction.guild.id if interaction. guild else None
            if gid in self.cog.guild_pending_counts and self.cog. guild_pending_counts[gid] > 0:
                self.cog. guild_pending_counts[gid] -= 1
            await safe_send(interaction.followup, content="🗑️ Link deleted.", ephemeral=True)
        except Exception as e: 
            logger.error(f"Confirm delete failed: {e}")
            await safe_send(interaction. followup, content=error_message("Could not delete link.  Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception: 
                pass

    @discord.ui.button(label="Keep", style=discord. ButtonStyle.secondary, emoji="↩️")
    async def cancel_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        for child in self.children:
            child.disabled = True
        try: 
            await interaction.message.edit(view=self)
        except Exception: 
            pass


class ConfirmYesNoView(discord.ui.View):
    def __init__(self, author_id: int, on_confirm:  Callable[[], Awaitable[None]], prompt:  str = "Are you sure? ", timeout: int = 60):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.on_confirm = on_confirm
        self.prompt = prompt

    async def interaction_check(self, interaction:  discord.Interaction) -> bool:
        if interaction.user. id != self.author_id:
            await safe_send(interaction.response, content=error_message("Not for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, interaction:  discord.Interaction, button:  discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            await self.on_confirm()
            await safe_send(interaction.followup, content="✅ Done.", ephemeral=True)
        except Exception as e: 
            logger.error(f"ConfirmYesNoView error: {e}")
            await safe_send(interaction.followup, content=error_message("Failed to complete action. "), ephemeral=True)
        finally:
            for child in self. children:
                child.disabled = True
            try:
                await interaction.message. edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord. ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        for child in self.children:
            child. disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception: 
            pass


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class LinkManagerCog(commands. Cog, name="LinkManager"):
    def __init__(self, bot:  commands.Bot):
        self.bot = bot
        self. pending_links = {}
        self.pending_batches = {}
        self.pending_delete_confirmations = {}
        self.links_to_categorize = {}
        self.pending_category_deletion = {}
        self. pending_clear_all = {}
        self.processed_messages = set()
        self.event_cleanup = EventCleanup()
        self.rate_limiter = RateLimiter()
        self.pendinglinks_in_progress = set()
        self.cleanup_task = None
        self.guild_pending_cap = 200
        self.guild_pending_counts = {}
        self. archiver_task = None

    async def cog_load(self):
        self.archiver_task = asyncio.create_task(self._archive_expired_loop())

    async def cog_unload(self):
        if self.archiver_task:
            self.archiver_task.cancel()

    async def _archive_expired_loop(self):
        while True:
            try:
                await asyncio.sleep(3600)
                await self._archive_expired_links()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"archiver loop error: {e}")

    async def _archive_expired_links(self):
        links = storage.get_saved_links()
        changed = False
        now = datetime.datetime. utcnow()
        for l in links:
            if l. get("archived"):
                continue
            exp = l.get("expires_at")
            if exp: 
                try:
                    exp_dt = datetime.datetime. fromisoformat(exp)
                    if exp_dt < now:
                        l["archived"] = True
                        changed = True
                except Exception: 
                    continue
        if changed: 
            storage.clear_saved_links()
            for l in links:
                storage.add_saved_link(l)

    async def handle_summarize_preview_ctx(self, interaction: discord.Interaction, message: discord.Message):
        await ack_interaction(interaction, ephemeral=True)
        file_url, filename = None, None
        for att in message.attachments:
            fn = att.filename. lower()
            if fn.endswith(tuple(EXCEL_TYPES | HTML_TYPES | TEXTISH_TYPES | {".pdf"})):
                file_url, filename = att.url, att.filename
                break
        if not file_url: 
            for m in re.finditer(URL_REGEX, message.content or ""):
                url = m.group(0)
                if urlparse(url).path.lower().endswith(tuple(EXCEL_TYPES | HTML_TYPES | TEXTISH_TYPES | {".pdf"})):
                    file_url, filename = url, os.path.basename(urlparse(url).path)
                    break
        if not file_url: 
            await safe_send(interaction.followup, content="⚠️ No supported document found in that message.", ephemeral=True)
            return
        data = await download_bytes(file_url)
        if not data:
            await safe_send(interaction. followup, content="⚠️ Failed to download the file.", ephemeral=True)
            return
        preview_block = ""
        if os.path.splitext(filename. lower())[1] in EXCEL_TYPES:
            table_md = excel_preview_table(data, filename, max_rows=5)
            if table_md:
                preview_block = f"🧾 **Preview (first rows)**\n```markdown\n{table_md}\n```"
        summary = await summarize_document_bytes(filename, data, context_note=f"Requested by {interaction.user.display_name}")
        summary_clip = summary[:1500]
        embed = discord.Embed(
            title=f"Summary Preview:  {filename}",
            description=summary_clip,
            color=0x00FF9C
        )
        embed.set_footer(text="Use Export to download full summary.  Use Category to file it.")
        buttons = SummaryActionView(
            filename=filename,
            summary=summary,
            requester=interaction.user,
            cog=self
        )
        await safe_send(interaction.followup, embed=embed, content=preview_block or None, view=buttons)

    async def handle_analyze_link_ctx(self, interaction: discord. Interaction, message: discord.Message):
        await ack_interaction(interaction, ephemeral=True)
        link = None
        try:
            for m in re.finditer(URL_REGEX, message.content or ""):
                cand = m.group(0)
                if is_valid_url(cand) and not is_media_url(cand):
                    link = cand
                    break
        except re.error:
            pass
        if not link:
            await safe_send(interaction.followup, content="⚠️ No valid link found in that message.", ephemeral=True)
            return
        guidance = await get_ai_guidance(link)
        lines = guidance.splitlines()
        verdict_line = lines[0] if lines else "Keep/Skip"
        reason_line = lines[1] if len(lines) > 1 else "No reason provided."
        preview = await link_preview(link)
        embed = make_verdict_embed(link, verdict_line, reason_line, preview)
        await safe_send(interaction.followup, embed=embed, ephemeral=True)

    def prune_processed(self, max_size=50000):
        if len(self.processed_messages) > max_size: 
            self.processed_messages = set(list(self.processed_messages)[-max_size:])

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
                prefix = await maybe if asyncio.iscoroutine(maybe) else maybe
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
        gid = original_message.guild. id if original_message and original_message.guild else None
        per_guild_delay = guild_config.get_value(gid, "auto_delete_seconds", AUTO_DELETE_SECONDS_DEFAULT)
        delay = delay if delay is not None else per_guild_delay
        if not AUTO_DELETE_ENABLED:
            return
        await asyncio.sleep(delay)
        try:
            if bot_message and bot_message.id in self.pending_links:
                try:
                    await bot
