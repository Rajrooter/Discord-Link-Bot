#!/usr/bin/env python3
"""
Digital Labour - main.py
Features: embed UI, 4-button link actions, link shortening, multi-guild scoping,
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

URL_REGEX = r'(?:(?:https?://)|www\.)\S+'
IGNORED_EXTENSIONS = ['.gif', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.mp4', '.mov', '.avi']

COMMUNITY_LEARNING_URL = os.environ.get("COMMUNITY_LEARNING_URL", "https://share.google/yf57dJNzEyAVM0asz")

MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/html",
    "application/pdf",
    "application/rtf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "application/octet-stream",
}
EXCEL_TYPES = {".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".csv"}
HTML_TYPES = {".html", ".htm", ".xhtml", ".asp", ".aspx"}
TEXTISH_TYPES = {".txt", ".rtf", ".doc", ".docx", ".wps", ".csv"}

SECURITY_ALERT_CHANNEL_ID = int(os.environ.get("SECURITY_ALERT_CHANNEL_ID", "0") or 0)


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
        logger.error(f"Failed to send security alert: {e}")


def error_message(msg: str) -> str:
    return f"⚠️ **Error:** {msg}"


def ratelimit_message(wait_s: float) -> str:
    return f"⏳ **Slow down!** Please wait {wait_s:.1f} seconds before using this again."


def verdict_message(link: str, verdict: str, reason: str, author_mention: str = "") -> str:
    status = "✅" if "Keep" in verdict else "⚠️"
    mention_text = f"\n_{author_mention}_" if author_mention else ""
    return f"{status} **{verdict}**\n{reason}\n\n`{link[:100]}{'...' if len(link) > 100 else ''}`{mention_text}"


def multi_link_message(count: int) -> str:
    return f"📎 **{count} links detected!**\nSelect the links you want to save using the dropdown below."


def summarize_progress_message(filename: str) -> str:
    return f"📝 **Summarizing:** {filename}\nPlease wait..."


def summarize_result_message(filename: str, body: str, requester: str) -> str:
    return f"📝 **Summary:  {filename}**\n\n{body}\n\n_Summarized for {requester}_"


async def link_preview(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or "link"
        path = parsed.path[:60] + ("..." if len(parsed.path) > 60 else "")
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
    embed = discord.Embed(
        title=verdict_line,
        description=reason_line,
        color=0x00C853 if "Keep" in verdict_line else 0xFFA000
    )
    embed.add_field(name="Link", value=f"`{link}`", inline=False)
    if preview:
        embed.add_field(name="Preview", value=preview, inline=False)
    embed.set_footer(text="Choose: Save now • Save later • Shorten • Cancel")
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
[2;35m>_[0m [2;37mStatus:[0m [1;32m[ONLINE][0m [2;33m// Session:  ACTIVE[0m
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
[1;32m│ ◆[0m Document Summarization (.pdf/.docx/.txt/.csv/.xls[x])
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
[2;35m║[0m ⚡ TIP: Mention me + question for AI help      [2;35m║[0m
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
            "→ Summarize documents (.pdf/.docx/.txt/.csv/.xls[x])\n"
            "→ Mention me for AI help\n"
            "→ Burst protection queuing"
        ),
        inline=False
    )
    embed.set_footer(text="💡 Drop any link for AI analysis • Upload docs for instant summary")
    embed.timestamp = datetime.datetime.utcnow()
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


def filter_links_by_guild(links, guild_id: Optional[int]):
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
            l.get("url", ""),
            l.get("category", ""),
            l.get("author", ""),
            l.get("timestamp", ""),
            l.get("archived", False),
            l.get("expires_at", "")
        ])
    buf.seek(0)
    return buf.getvalue().encode("utf-8")


def export_links_pdf_placeholder():
    return b"PDF export not implemented; install reportlab to enable real PDF output."


# ---------------------------------------------------------------------------
# Extraction/summarization helpers
# ---------------------------------------------------------------------------

async def shorten_link(url: str) -> Optional[str]:
    try:
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=")
        api = f"http://tinyurl.com/api-create.php?url={safe_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api, timeout=8) as resp:
                if resp.status == 200:
                    short = (await resp.text()).strip()
                    if short.startswith("http"):
                        return short
    except Exception as e:
        logger.debug(f"shorten_link error: {e}")
    return None


def excel_preview_table(data: bytes, filename: str, max_rows: int = 5) -> Optional[str]:
    try:
        import pandas as pd
        ext = os.path.splitext(filename.lower())[1]
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(data))
        else:
            df = pd.read_excel(io.BytesIO(data), engine=None)
        if df.empty:
            return "*(No rows to display)*"
        return df.head(max_rows).to_markdown(index=False)
    except Exception as e:
        logger.debug(f"excel_preview_table error: {e}")
        return None


def extract_text_from_bytes(filename: str, data: bytes) -> Optional[str]:
    name = filename.lower()
    try:
        ext = os.path.splitext(name)[1]
        if ext in EXCEL_TYPES:
            try:
                import pandas as pd
                if ext == ".csv":
                    df = pd.read_csv(io.BytesIO(data))
                else:
                    df = pd.read_excel(io.BytesIO(data), engine=None)
                if df.empty:
                    return "(No rows)"
                return df.head(20).to_csv(index=False)
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
        if name.endswith(".pdf"):
            try:
                from PyPDF2 import PdfReader
                with io.BytesIO(data) as bio:
                    reader = PdfReader(bio)
                    pages = [p.extract_text() or "" for p in reader.pages]
                    return "\n".join(pages)
            except Exception as e:
                logger.debug(f"PDF extraction error: {e}")
                return None
        if name.endswith(".docx"):
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
                logger.debug(f"HTML extraction error: {e}")
                return None
        if name.endswith(".rtf"):
            try:
                import striprtf
                return striprtf.rtf_to_text(data.decode("latin-1", errors="ignore"))
            except Exception as e:
                logger.debug(f"RTF extraction error: {e}")
                return None
    except Exception as e:
        logger.debug(f"extract_text_from_bytes error: {e}")
    return None


async def summarize_document_bytes(filename: str, data: bytes, context_note: str = "") -> str:
    text = extract_text_from_bytes(filename, data)
    if not text:
        return "⚠️ Couldn't extract text. For PDF/DOCX ensure PyPDF2 and python-docx are installed or provide a .txt version."
    excerpt = text[:40000]
    prompt = (
        "Summarize in <=10 lines. Be clear, kid-friendly, concise.\n"
        "Sections: Markdown overview, Content, Red Flags, Conclusion, Real-life tip. No filler, no random additions.\n"
        f"Context: {context_note}\n\nContent:\n{excerpt}"
    )
    return await ai_call(prompt, max_retries=3, timeout=18.0)


def is_media_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
        for ext in IGNORED_EXTENSIONS:
            if path.endswith(ext):
                return True
        media_domains = [
            'giphy.com', 'tenor.com', 'imgur.com', 'gyazo.com',
            'streamable.com', 'clippy.gg', 'cdn.discordapp.com', 'media.discordapp.net'
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
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True

def get_prefix(bot, message):
    prefixes = ["!"]
    return commands.when_mentioned_or(*prefixes)(bot, message)


# ---------------------------------------------------------------------------
# Context menu callbacks (top-level)
# ---------------------------------------------------------------------------

@app_commands.context_menu(name="Summarize/Preview Document")
async def summarize_preview_ctx(interaction: discord.Interaction, message: discord.Message):
    cog = interaction.client.get_cog("LinkManager")
    if not cog:
        await interaction.response.send_message("⚠️ Cog not ready.", ephemeral=True)
        return
    await cog.handle_summarize_preview_ctx(interaction, message)


@app_commands.context_menu(name="Analyze Link (AI)")
async def analyze_link_ctx(interaction: discord.Interaction, message: discord.Message):
    cog = interaction.client.get_cog("LinkManager")
    if not cog:
        await interaction.response.send_message("⚠️ Cog not ready.", ephemeral=True)
        return
    await cog.handle_analyze_link_ctx(interaction, message)


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class MyBot(commands.Bot):
    async def setup_hook(self):
        await self.add_cog(LinkManagerCog(self))
        logger.info("✅ LinkManager cog added")

        try:
            if hasattr(storage, "prune_orphaned_pending"):
                pruned = await asyncio.to_thread(storage.prune_orphaned_pending)
                logger.info(f"🧹 Pruned orphaned pending links: {pruned}")
            elif hasattr(storage, "clear_orphaned_pending"):
                pruned = await asyncio.to_thread(storage.clear_orphaned_pending)
                logger.info(f"🧹 Pruned orphaned pending links: {pruned}")
        except Exception as e:
            logger.warning(f"Startup prune failed: {e}")

        cmd_names = [c.qualified_name for c in self.tree.walk_commands()]
        logger.info(f"🔧 App commands loaded (pre-sync): {cmd_names}")

        self.tree.add_command(summarize_preview_ctx)
        self.tree.add_command(analyze_link_ctx)

        synced_commands = []
        try:
            global_synced = await self.tree.sync()
            synced_commands.extend(global_synced)
            logger.info(f"✅ Synced {len(global_synced)} commands globally: {[c.name for c in global_synced]}")
            if not global_synced:
                logger.warning("⚠️ No global commands synced. Check token scope or restart.")
        except Exception as e:
            logger.error(f"Global sync failed: {e}")

        test_guild_id = os.environ.get("TEST_GUILD_ID")
        if test_guild_id:
            try:
                guild_id = int(test_guild_id)
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                guild_synced = await self.tree.sync(guild=guild)
                logger.info(f"✅ Synced {len(guild_synced)} commands to test guild {guild_id}: {[c.name for c in guild_synced]}")
                if not guild_synced:
                    logger.warning(f"⚠️ No commands synced to test guild {guild_id}.")
            except Exception as e:
                logger.error(f"Test guild sync failed: {e}")

        logger.info(f"✅ Total commands synced: {len(synced_commands)}")


bot = MyBot(command_prefix=get_prefix, intents=intents, help_command=None)
bot.remove_command("help")


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------

class CategoryModal(discord.ui.Modal, title="Save Summary to Category"):
    category = discord.ui.TextInput(label="Category name", required=True, max_length=60)

    def __init__(self, on_submit_cb: Callable[[str], Awaitable[None]]):
        super().__init__()
        self.on_submit_cb = on_submit_cb

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.on_submit_cb(str(self.category))
        await safe_send(interaction.followup, content=f"✅ Saved to category **{self.category}**", ephemeral=True)


class SummaryActionView(discord.ui.View):
    def __init__(self, filename: str, summary: str, requester: discord.User, cog):
        super().__init__(timeout=180)
        self.filename = filename
        self.summary = summary
        self.requester = requester
        self.cog = cog

    @discord.ui.button(label="Export (.txt)", style=discord.ButtonStyle.primary, emoji="📤")
    async def export_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        buf = io.BytesIO(self.summary.encode("utf-8", errors="replace"))
        buf.seek(0)
        await interaction.followup.send(
            content="📎 Exported summary:",
            file=discord.File(buf, filename=f"{os.path.splitext(self.filename)[0]}_summary.txt"),
            ephemeral=True
        )

    @discord.ui.button(label="Save to Category", style=discord.ButtonStyle.success, emoji="🗂️")
    async def category_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)

        async def on_submit(cat_name: str):
            entry = {
                "url": f"(summary of {self.filename})",
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "author": str(self.requester),
                "category": cat_name,
                "summary": self.summary[:4000],
                "guild_id": interaction.guild.id if interaction.guild else None,
                "archived": False,
                "expires_at": None,
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
        self.cog = cog
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await safe_send(interaction.response, content=error_message("Only the uploader can request summarization."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Summarize", style=discord.ButtonStyle.green, emoji="📝")
    async def summarize_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            ext = os.path.splitext(self.filename.lower())[1]
            if ext in EXCEL_TYPES:
                table_md = excel_preview_table(data, self.filename, max_rows=5)
                if table_md:
                    await safe_send(interaction.channel, content=f"🧾 **Preview of {self.filename} (first rows):**\n```markdown\n{table_md}\n```")
            progress = await safe_send(interaction.followup, content=summarize_progress_message(self.filename), ephemeral=True)
            summary = await summarize_document_bytes(self.filename, data, context_note=self.context_note)
            result_msg = summarize_result_message(self.filename, summary[:3500], interaction.user.mention)
            await safe_send(interaction.channel, content=result_msg)
            if progress and hasattr(progress, "edit"):
                try:
                    await progress.edit(content="✅ **Done** - Summary posted.")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Summarize button failed: {e}")
            await safe_send(interaction.followup, content=error_message("Summarization failed. Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        for child in self.children:
            child.disabled = True
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
        if interaction.user.id != self.author_id:
            await safe_send(interaction.response, content=error_message("This is not for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Save links", style=discord.ButtonStyle.green, emoji="✅")
    async def yes_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            await self.message.delete()
        except Exception:
            pass
        links_data = [{"url": link} for link in self.links]
        selection_view = MultiLinkSelectView(links_data, self.author_id, self.original_message, self.cog)
        prompt_msg = await safe_send(interaction.channel, content=multi_link_message(len(self.links)), view=selection_view)
        if prompt_msg:
            selection_view.message = prompt_msg

    @discord.ui.button(label="Ignore", style=discord.ButtonStyle.secondary, emoji="❌")
    async def no_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            await self.message.delete()
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
        if interaction.user.id != self.author_id:
            await safe_send(interaction.response, content=error_message("This button is not for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Save now", style=discord.ButtonStyle.success, emoji="💾")
    async def save_now(self, interaction, button):
        if getattr(self, "_done", False):
            await ack_interaction(interaction, ephemeral=True)
            return
        self._done = True
        await ack_interaction(interaction, ephemeral=True)
        try:
            await asyncio.to_thread(storage.delete_pending_link_by_id, self.pending_db_id)
            if interaction.message.id in self.cog.pending_links:
                del self.cog.pending_links[interaction.message.id]
            gid = interaction.guild.id if interaction.guild else None
            if gid in self.cog.guild_pending_counts and self.cog.guild_pending_counts[gid] > 0:
                self.cog.guild_pending_counts[gid] -= 1
            self.cog.links_to_categorize[self.author_id] = {"link": self.link, "message": self.original_message}
            prefix = await self.cog._get_preferred_prefix(self.original_message) if self.original_message else "!"
            await safe_send(interaction.followup, content=f"✅ Link marked for saving! Use `{prefix}category <name>` to finalize.", ephemeral=True)
        except Exception as e:
            logger.error(f"Save failed: {e}")
            await safe_send(interaction.followup, content=error_message("Failed to mark link for saving. Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Save later", style=discord.ButtonStyle.primary, emoji="🕒")
    async def save_later(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        await safe_send(interaction.followup, content="🕒 Saved for later review. Use `/pendinglinks` to process.", ephemeral=True)

    @discord.ui.button(label="Shorten link", style=discord.ButtonStyle.secondary, emoji="🔗")
    async def shorten_btn(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        short = await shorten_link(self.link)
        if short:
            await safe_send(interaction.followup, content=f"📎 Shortened link:\n{short}", ephemeral=True)
        else:
            await safe_send(interaction.followup, content=error_message("Could not shorten link. Try again later."), ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_btn(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            if self.original_message:
                try:
                    await self.original_message.delete()
                except Exception:
                    pass
            try:
                await asyncio.to_thread(storage.delete_pending_link_by_id, self.pending_db_id)
            except Exception as e:
                logger.error(f"Pending delete failed: {e}")
            if interaction.message.id in self.cog.pending_links:
                del self.cog.pending_links[interaction.message.id]
            gid = interaction.guild.id if interaction.guild else None
            if gid in self.cog.guild_pending_counts and self.cog.guild_pending_counts[gid] > 0:
                self.cog.guild_pending_counts[gid] -= 1
            try:
                await interaction.message.delete()
            except Exception:
                pass
            await safe_send(interaction.followup, content="❌ Prompt removed.", ephemeral=True)
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            await safe_send(interaction.followup, content=error_message("Could not cancel."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True


class MultiLinkSelectView(discord.ui.View):
    def __init__(self, links: list, author_id: int, original_message, cog):
        super().__init__(timeout=300)
        self.links = links
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.selected_links = []
        self.message = None
        options = []
        max_options = min(len(links), 25)
        for idx in range(max_options):
            url = links[idx].get("url", "")
            label = f"Link {idx+1}"
            desc = url if len(url) <= 100 else url[:97] + "..."
            options.append(discord.SelectOption(label=label, value=str(idx), description=desc))
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
        if interaction.user.id != self.author_id:
            await safe_send(interaction.response, content=error_message("Not your selection."), ephemeral=True)
            return False
        if interaction.data.get("custom_id") == "link_selector":
            await ack_interaction(interaction, ephemeral=False)
            values = interaction.data.get("values", [])
            self.selected_links = [int(v) for v in values]
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
    def __init__(self, links: list, selected_indices: set, author_id: int, original_message, cog):
        super().__init__(timeout=60)
        self.links = links
        self.selected_indices = selected_indices
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.message = None

    @discord.ui.button(label="Save selected", style=discord.ButtonStyle.green, emoji="💾")
    async def confirm_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
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
                pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
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
                        f"`{link[:100]}{'...' if len(link) > 100 else ''}`"
                    )
                )
            except Exception as e:
                logger.error(f"Error saving link {idx}: {e}")
                await safe_send(interaction.channel, content=error_message("Failed to save one of the links. Please try again."))
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
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

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
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
            gid = interaction.guild.id if interaction.guild else None
            if gid in self.cog.guild_pending_counts and self.cog.guild_pending_counts[gid] > 0:
                self.cog.guild_pending_counts[gid] -= 1
            await safe_send(interaction.followup, content="🗑️ Link deleted.", ephemeral=True)
        except Exception as e:
            logger.error(f"Confirm delete failed: {e}")
            await safe_send(interaction.followup, content=error_message("Could not delete link. Please try again."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Keep", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def cancel_button(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass


class ConfirmYesNoView(discord.ui.View):
    def __init__(self, author_id: int, on_confirm: Callable[[], Awaitable[None]], prompt: str = "Are you sure?", timeout: int = 60):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.on_confirm = on_confirm
        self.prompt = prompt

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await safe_send(interaction.response, content=error_message("Not for you."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        try:
            await self.on_confirm()
            await safe_send(interaction.followup, content="✅ Done.", ephemeral=True)
        except Exception as e:
            logger.error(f"ConfirmYesNoView error: {e}")
            await safe_send(interaction.followup, content=error_message("Failed to complete action."), ephemeral=True)
        finally:
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ack_interaction(interaction, ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class LinkManagerCog(commands.Cog, name="LinkManager"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_links = {}
        self.pending_batches = {}
        self.pending_delete_confirmations = {}
        self.links_to_categorize = {}
        self.pending_category_deletion = {}
        self.pending_clear_all = {}
        self.processed_messages = set()
        self.event_cleanup = EventCleanup()
        self.rate_limiter = RateLimiter()
        self.pendinglinks_in_progress = set()
        self.cleanup_task = None
        self.guild_pending_cap = 200
        self.guild_pending_counts = {}
        self.archiver_task = None

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
        now = datetime.datetime.utcnow()
        for l in links:
            if l.get("archived"):
                continue
            exp = l.get("expires_at")
            if exp:
                try:
                    exp_dt = datetime.datetime.fromisoformat(exp)
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
            fn = att.filename.lower()
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
            await safe_send(interaction.followup, content="⚠️ Failed to download the file.", ephemeral=True)
            return
        preview_block = ""
        if os.path.splitext(filename.lower())[1] in EXCEL_TYPES:
            table_md = excel_preview_table(data, filename, max_rows=5)
            if table_md:
                preview_block = f"🧾 **Preview (first rows)**\n```markdown\n{table_md}\n```"
        summary = await summarize_document_bytes(filename, data, context_note=f"Requested by {interaction.user.display_name}")
        summary_clip = summary[:1500]
        embed = discord.Embed(
            title=f"Summary Preview: {filename}",
            description=summary_clip,
            color=0x00FF9C
        )
        embed.set_footer(text="Use Export to download full summary. Use Category to file it.")
        buttons = SummaryActionView(
            filename=filename,
            summary=summary,
            requester=interaction.user,
            cog=self
        )
        await safe_send(interaction.followup, embed=embed, content=preview_block or None, view=buttons)

    async def handle_analyze_link_ctx(self, interaction: discord.Interaction, message: discord.Message):
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
                if gid in self.guild_pending_counts and self.guild_pending_counts[gid] > 0:
                    self.guild_pending_counts[gid] -= 1
        except Exception as e:
            logger.debug(f"_delete_if_no_response error: {e}")

    async def _handle_mention_query(self, message: discord.Message) -> bool:
        user_id = message.author.id
        if self.rate_limiter.is_limited(user_id, "ai_mention", cooldown=8.0):
            remaining = self.rate_limiter.get_remaining(user_id, "ai_mention", cooldown=8.0)
            await safe_send(message.channel, content=ratelimit_message(remaining))
            return True

        content = (message.content or "").strip()
        mention_forms = (f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>")
        for m in mention_forms:
            content = content.replace(m, "")
        text = content.strip().lower()

        if re.search(r"\bwhat(?:'s| is)? the server rules\b", text) or ("server rules" in text and "what" in text):
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
                                    rules_text = m.content
                                    break
                    except Exception:
                        rules_text = None
            if not rules_text:
                rules_text = load_rules()
            response = f"📒 **Server Rules**\n\n{rules_text[:1800]}\n\n_Mention me with 'improve rules' to get AI suggestions._"
            await safe_send(message.channel, content=response)
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
            preview = "\n".join(ai_response.splitlines()[:8])
            await safe_send(message.channel, content=f"🧠 **AI:  Improvements**\n\n{preview[:1500]}")
            for chunk in (ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if any(k in text for k in ("career", "job", "placement", "interview", "resume", "cv", "jobs")):
            extra_ctx = f"User question: {content.strip()}\nWebsite: {COMMUNITY_LEARNING_URL}\nAudience: rural students"
            await message.channel.trigger_typing()
            ai_response = await ai_server_audit(message.guild, topic="career guidance for students", extra_context=extra_ctx)
            preview = "\n".join(ai_response.splitlines()[:6])
            await safe_send(message.channel, content=f"🎯 **AI: Career Guidance**\n\n{preview[:1500]}")
            for chunk in (ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if "how to learn" in text and "discord" in text or re.search(r"\bhow to use discord\b", text) or "learn using discord" in text:
            teacher_prompt = (
                "You are a patient teacher. Explain, in numbered short steps, how students can use Discord to learn: "
                "join channels, read pinned messages, use reactions, use slash commands, ask for help. Add 3 safety tips."
            )
            ai_response = await ai_call(teacher_prompt, max_retries=2, timeout=12.0)
            await safe_send(message.channel, content=f"📘 **Learning Discord (simple)**\n\n{ai_response[:1500]}")
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
            await safe_send(message.channel, content=f"🖼️ **Avatar suggestions**\n\n{ai_response[:1500]}")
            for chunk in (ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if "what more channels" in text or "channels to create" in text or "suggest channels" in text:
            suggestions = await ai_channel_suggestions(message.guild, focus="study, career, low-resource teaching")
            await safe_send(message.channel, content=f"📂 **Channel suggestions**\n\n{suggestions[:1500]}")
            for chunk in (suggestions[i:i+1900] for i in range(0, len(suggestions), 1900)):
                await safe_send(message.channel, content=chunk)
            self.rate_limiter.register(user_id, "ai_mention")
            return True

        if "prefix" in text or "command prefix" in text:
            prefix = await self._get_preferred_prefix(message)
            await safe_send(message.channel, content=f"👋 My active command prefix is `{prefix}` — you can also use slash (/) commands.")
            return True

        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        logger.debug(f"on_message: guild={getattr(message.guild, 'id', None)} channel={getattr(message.channel, 'id', None)} author={message.author} content={message.content!r}")
        if message.author == self.bot.user or message.id in self.processed_messages:
            return
        self.processed_messages.add(message.id)
        self.prune_processed()

        await self.bot.process_commands(message)

        try:
            urls = [m.group(0) for m in re.finditer(URL_REGEX, message.content or "")]
            logger.debug(f"on_message urls={urls}")
        except re.error:
            urls = []

        try:
            if self.bot.user in message.mentions:
                handled = await self._handle_mention_query(message)
                if handled:
                    return
                prefix = await self._get_preferred_prefix(message)
                welcome = (
                    f"👋 **Welcome to Digital Labour**\n\n"
                    f"I help save links, summarize docs, and guide students.\n"
                    f"Prefix: `{prefix}` or use slash commands.\n"
                    f"Try: drop a link or type `/help`."
                )
                await safe_send(message.channel, content=welcome)
                return
        except Exception:
            logger.debug("mention handler error", exc_info=True)

        try:
            file_candidates = []
            for att in message.attachments:
                fn = att.filename.lower()
                if fn.endswith(tuple(EXCEL_TYPES | HTML_TYPES | TEXTISH_TYPES | {".pdf"})):
                    file_candidates.append((att.url, att.filename))
            for m in re.finditer(URL_REGEX, message.content or ""):
                url = m.group(0)
                if urlparse(url).path.lower().endswith(tuple(EXCEL_TYPES | HTML_TYPES | TEXTISH_TYPES | {".pdf"})):
                    file_candidates.append((url, os.path.basename(urlparse(url).path)))
            if file_candidates:
                for url, filename in file_candidates:
                    view = SummarizeView(
                        file_url=url,
                        filename=filename,
                        author_id=message.author.id,
                        context_note=f"Uploaded in #{message.channel.name} by {message.author.display_name}",
                        cog=self
                    )
                    prompt_msg = await safe_send(
                        message.channel,
                        content=f"📝 **Document detected**\n\n{message.author.mention}, click to summarize **{filename}**.",
                        view=view
                    )
                    if prompt_msg:
                        view.message = prompt_msg
        except Exception:
            logger.debug("file summarize trigger error", exc_info=True)

        if urls:
            non_media_links = [link for link in urls if not is_media_url(link) and is_valid_url(link)]
            if len(non_media_links) > 1:
                if len(non_media_links) > 25:
                    await safe_send(
                        message.channel,
                        content=f"📎 **Many links detected!**\n\nFound {len(non_media_links)} links. Processing in batches. Use `!pendinglinks` to review."
                    )
                    dropdown_links = non_media_links[:25]
                    remaining = non_media_links[25:]
                    for link in remaining:
                        try:
                            gid = message.guild.id if message.guild else None
                            count = self.guild_pending_counts.get(gid, 0) + 1
                            self.guild_pending_counts[gid] = count
                            if count > self.guild_pending_cap:
                                await security_alert(self.bot, f"Pending queue cap exceeded in guild {gid}.")
                                await safe_send(message.channel, content="⚠️ Too many pending links right now. Please try again later.")
                                continue
                            pending_entry = {
                                "user_id": message.author.id,
                                "link": link,
                                "channel_id": message.channel.id,
                                "original_message_id": message.id,
                                "timestamp": datetime.datetime.utcnow().isoformat()
                            }
                            pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                            self.pending_batches.setdefault(message.author.id, []).append(
                                {"link": link, "original_message": message, "timestamp": time.time(), "pending_db_id": pending_id}
                            )
                        except Exception as e:
                            logger.error(f"Failed to queue link (batch overflow): {e}")
                            await safe_send(message.channel, content=error_message("Failed to queue one of the links. Please try again."))
                else:
                    dropdown_links = non_media_links
                disclaimer_view = DisclaimerView(dropdown_links, message.author.id, message, self)
                disclaimer_msg = await safe_send(message.channel, content=multi_link_message(len(non_media_links)), view=disclaimer_view)
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
                per_guild_threshold = guild_config.get_value(gid, "batch_threshold", BATCH_THRESHOLD_DEFAULT)
                if event_count > per_guild_threshold:
                    try:
                        count = self.guild_pending_counts.get(gid, 0) + 1
                        self.guild_pending_counts[gid] = count
                        if count > self.guild_pending_cap:
                            await security_alert(self.bot, f"Pending queue cap exceeded in guild {gid}.")
                            await safe_send(message.channel, content="⚠️ Too many pending links right now. Please try again later.")
                            continue
                        pending_entry = {
                            "user_id": message.author.id,
                            "link": link,
                            "channel_id": message.channel.id,
                            "original_message_id": message.id,
                            "timestamp": datetime.datetime.utcnow().isoformat()
                        }
                        pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                        self.pending_batches.setdefault(message.author.id, []).append(
                            {"link": link, "original_message": message, "timestamp": now, "pending_db_id": pending_id}
                        )
                        try:
                            await message.add_reaction("🗂️")
                        except Exception:
                            pass
                        continue
                    except Exception as e:
                        logger.error(f"Failed to queue link (burst): {e}")
                        await safe_send(message.channel, content=error_message("Failed to queue this link. Please try again."))
                        continue
                try:
                    count = self.guild_pending_counts.get(gid, 0) + 1
                    self.guild_pending_counts[gid] = count
                    if count > self.guild_pending_cap:
                        await security_alert(self.bot, f"Pending queue cap exceeded in guild {gid}.")
                        await safe_send(message.channel, content="⚠️ Too many pending links right now. Please try again later.")
                        continue
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
                    preview = await link_preview(link)
                    embed = make_verdict_embed(link, verdict_line, reason_line, preview)
                    view = LinkActionView(link, message.author.id, message, pending_id, self, ai_verdict=guidance)
                    ask_msg = await safe_send(message.channel, embed=embed, view=view)
                    if pending_id:
                        try:
                            await asyncio.to_thread(storage.update_pending_with_bot_msg_id, pending_id, getattr(ask_msg, "id", None))
                        except Exception as e:
                            logger.error(f"Failed to update pending with bot msg id: {e}")
                    self.pending_links[getattr(ask_msg, "id", None)] = {
                        "link": link,
                        "author_id": message.author.id,
                        "original_message": message,
                        "pending_db_id": pending_id
                    }
                    try:
                        asyncio.create_task(self._delete_if_no_response(ask_msg, message, pending_id))
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Failed to process link: {e}")
                    await safe_send(message.channel, content=error_message("Failed to handle this link. Please try again."))

    # ----------------- Commands -----------------

    @commands.hybrid_command(name="export", description="Export links (csv|pdf) optionally by category")
    async def export_links(self, ctx: commands.Context, format: str, category: Optional[str] = None):
        fmt = format.lower()
        if fmt not in ("csv", "pdf"):
            await safe_send(ctx, content="Format must be csv or pdf.")
            return
        links = storage.get_saved_links()
        links = filter_links_by_guild(links, ctx.guild.id if ctx.guild else None)
        links = [l for l in links if not l.get("archived")]
        if category:
            links = [l for l in links if l.get("category", "").lower() == category.lower()]
        if not links:
            await safe_send(ctx, content="No links to export for this scope.")
            return
        if fmt == "csv":
            data = export_links_csv(links)
            file = discord.File(io.BytesIO(data), filename="links.csv")
        else:
            data = export_links_pdf_placeholder()
            file = discord.File(io.BytesIO(data), filename="links.pdf")
        await safe_send(ctx, content="Here is your export:", ephemeral=True, file=file)

    @commands.hybrid_command(name="setexpiry", description="Set expiry (days from now) for a link number")
    async def set_expiry(self, ctx: commands.Context, link_number: int, days: int):
        if days <= 0:
            await safe_send(ctx, content="Days must be > 0")
            return
        all_links = storage.get_saved_links()
        scoped = filter_links_by_guild(all_links, ctx.guild.id if ctx.guild else None)
        if link_number < 1 or link_number > len(scoped):
            await safe_send(ctx, content=f"Invalid number. Use 1-{len(scoped)}")
            return
        target = scoped[link_number - 1]
        expiry = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat()
        target["expires_at"] = expiry

        merged = []
        for l in all_links:
            if l.get("url") == target.get("url") and l.get("timestamp") == target.get("timestamp"):
                merged.append(target)
            else:
                merged.append(l)
        storage.clear_saved_links()
        for l in merged:
            storage.add_saved_link(l)
        await safe_send(ctx, content=f"Expiry set to {expiry}")

    @commands.hybrid_command(name="help", description="Display full command reference with cyberpunk UI")
    async def show_help(self, ctx: commands.Context, compact: bool = False):
        embed = make_compact_help_embed() if compact else make_cyberpunk_help_embed()
        await safe_send(ctx, embed=embed)

    @commands.hybrid_command(name="cmdinfo", description="Get detailed info about a specific command")
    async def command_info(self, ctx: commands.Context, command_name: str):
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
                "usage": "/analyze <url>",
                "example": "`/analyze https://github.com/awesome-repo`",
                "color": 0xFFFF00
            },
        }
        cmd = cmd_details.get(command_name.lower())
        if not cmd:
            await safe_send(ctx, content=error_message(f"Command '{command_name}' not found. Use `/help` for full list."))
            return
        header = f"""```ansi
[1;36m>_ COMMAND:[0m [1;33m{command_name.upper()}[0m
```"""
        embed = discord.Embed(
            title="",
            description=header + f"\n**{cmd.get('desc', 'No description')}**",
            color=cmd.get("color", 0x00D9FF)
        )
        if "usage" in cmd:
            embed.add_field(name="📝 Usage", value=f"```\n{cmd['usage']}\n```", inline=False)
        if "example" in cmd:
            embed.add_field(name="💡 Example", value=cmd["example"], inline=False)
        embed.set_footer(text="[SYSTEM] Use /help for full command list")
        embed.timestamp = datetime.datetime.utcnow()
        await safe_send(ctx, embed=embed)

    @commands.hybrid_command(name="pendinglinks", description="Review your pending links captured during bursts")
    async def pendinglinks(self, ctx: commands.Context):
        user_id = ctx.author.id
        if self.rate_limiter.is_limited(user_id, "pendinglinks", cooldown=5.0):
            remaining = self.rate_limiter.get_remaining(user_id, "pendinglinks", cooldown=5.0)
            await safe_send(ctx, content=ratelimit_message(remaining))
            return
        if user_id in self.pendinglinks_in_progress:
            await safe_send(ctx, content=f"{ctx.author.mention}, you have a pending review in progress.")
            return
        self.pendinglinks_in_progress.add(user_id)
        try:
            try:
                pending_from_db = await asyncio.to_thread(storage.get_pending_links_for_user, user_id)
            except Exception as e:
                logger.error(f"pendinglinks fetch failed: {e}")
                await safe_send(ctx, content=error_message("Could not load pending links right now. Please try again."))
                return
            batch = self.pending_batches.get(user_id, [])
            if not pending_from_db and not batch:
                await safe_send(ctx, content=f"{ctx.author.mention}, you have no pending links.")
                return
            for db_entry in pending_from_db:
                link = db_entry.get("link")
                pending_id = db_entry.get("_id")
                orig_msg_id = db_entry.get("original_message_id")
                orig_msg = None
                try:
                    orig_msg = await ctx.channel.fetch_message(orig_msg_id)
                except Exception:
                    pass
                guidance = await get_ai_guidance(link)
                lines = guidance.splitlines()
                verdict_line = lines[0] if lines else "Keep/Skip"
                reason_line = lines[1] if len(lines) > 1 else "No reason provided."
                preview = await link_preview(link)
                embed = make_verdict_embed(link, verdict_line, reason_line, preview)
                view = LinkActionView(link, ctx.author.id, orig_msg, pending_id, self, ai_verdict=guidance)
                ask_msg = await safe_send(ctx, embed=embed, view=view)
                if pending_id:
                    try:
                        await asyncio.to_thread(storage.update_pending_with_bot_msg_id, pending_id, getattr(ask_msg, "id", None))
                    except Exception as e:
                        logger.error(f"Failed to update pending with bot msg id: {e}")
                self.pending_links[getattr(ask_msg, "id", None)] = {
                    "link": link,
                    "author_id": ctx.author.id,
                    "original_message": orig_msg,
                    "pending_db_id": pending_id
                }
                try:
                    asyncio.create_task(self._delete_if_no_response(ask_msg, orig_msg, pending_id))
                except Exception:
                    pass
            for entry in batch:
                link = entry["link"]
                orig_msg = entry.get("original_message")
                pending_id = entry.get("pending_db_id")
                guidance = await get_ai_guidance(link)
                lines = guidance.splitlines()
                verdict_line = lines[0] if lines else "Keep/Skip"
                reason_line = lines[1] if len(lines) > 1 else "No reason provided."
                preview = await link_preview(link)
                embed = make_verdict_embed(link, verdict_line, reason_line, preview)
                view = LinkActionView(link, ctx.author.id, orig_msg, pending_id, self, ai_verdict=guidance)
                ask_msg = await safe_send(ctx, embed=embed, view=view)
                if pending_id:
                    try:
                        await asyncio.to_thread(storage.update_pending_with_bot_msg_id, pending_id, getattr(ask_msg, "id", None))
                    except Exception as e:
                        logger.error(f"Failed to update pending with bot msg id: {e}")
                self.pending_links[getattr(ask_msg, "id", None)] = {
                    "link": link,
                    "author_id": ctx.author.id,
                    "original_message": orig_msg,
                    "pending_db_id": pending_id
                }
                try:
                    asyncio.create_task(self._delete_if_no_response(ask_msg, orig_msg, pending_id))
                except Exception:
                    pass
            if user_id in self.pending_batches:
                del self.pending_batches[user_id]
        finally:
            self.pendinglinks_in_progress.discard(user_id)

    @commands.hybrid_command(name="category", description="Assign a category to a saved link (creates if missing)")
    async def assign_category(self, ctx: commands.Context, *, category_name: str):
        if ctx.author.id not in self.links_to_categorize:
            await safe_send(ctx, content=f"No pending link to categorize, {ctx.author.mention}")
            return
        link_data = self.links_to_categorize[ctx.author.id]
        link = link_data["link"]
        message = link_data["message"]
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            link_entry = {
                "url": link,
                "timestamp": timestamp,
                "author": str(message.author) if (message and message.author) else "Unknown",
                "category": category_name,
                "guild_id": ctx.guild.id if ctx.guild else None,
                "archived": False,
                "expires_at": None,
            }
            await asyncio.to_thread(storage.add_saved_link, link_entry)
            await asyncio.to_thread(storage.add_link_to_category, category_name, link)
            await safe_send(ctx, content=f"✅ Saved to **{category_name}**. You can pick this name again next time. ({ctx.author.mention})")
            del self.links_to_categorize[ctx.author.id]
        except Exception as e:
            logger.error(f"assign_category failed: {e}")
            await safe_send(ctx, content=error_message("Failed to save the link. Please try again."))

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
        links = filter_links_by_guild(links, ctx.guild.id if ctx.guild else None)
        if not links:
            await safe_send(ctx, content="No links saved yet!")
            return
        if category:
            filtered = [l for l in links if l.get("category", "").lower() == category.lower()]
            if not filtered:
                await safe_send(ctx, content=f"No links found in category '{category}'")
                return
            links = filtered
            title = f"Links in '{category}':"
        else:
            title = "All saved links:"
        response = f"**{title}**\n\n"
        for i, link in enumerate(links, 1):
            response += f"{i}. **{link.get('category','Uncategorized')}** - {link['url']}\n   *(by {link.get('author','Unknown')}, {link.get('timestamp','')})*\n"
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
            all_links = storage.get_saved_links()
            scoped = filter_links_by_guild(all_links, ctx.guild.id if ctx.guild else None)
            if not scoped:
                await safe_send(ctx, content="No links to delete!")
                return
            if link_number < 1 or link_number > len(scoped):
                await safe_send(ctx, content=f"Invalid number! Use 1-{len(scoped)}.")
                return
            removed = scoped[link_number - 1]

            new_all = []
            for l in all_links:
                if l.get("url") == removed.get("url") and l.get("timestamp") == removed.get("timestamp"):
                    continue
                new_all.append(l)
            storage.clear_saved_links()
            for l in new_all:
                storage.add_saved_link(l)

            cats = storage.get_categories()
            cat_name = removed.get("category")
            if cat_name in cats and removed.get("url") in cats[cat_name]:
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
            await safe_send(ctx, content=error_message("Failed to delete the link. Please try again."))

    @commands.hybrid_command(name="deletecategory", description="Delete a category and its links")
    async def delete_category(self, ctx: commands.Context, *, category_name: str):
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
            await safe_send(ctx, content=error_message("Failed to attach confirmation buttons. Please try again."))

    @commands.hybrid_command(name="clearlinks", description="Clear all links (Admin)")
    @commands.has_permissions(administrator=True)
    async def clear_links(self, ctx: commands.Context):
        async def do_clear():
            storage.clear_categories()
            storage.clear_saved_links()
        view = ConfirmYesNoView(author_id=ctx.author.id, on_confirm=do_clear, prompt="Delete ALL links and categories?")
        msg = await safe_send(ctx, content="⚠️ Delete ALL links and categories?", view=view)
        if not msg:
            await safe_send(ctx, content=error_message("Failed to attach confirmation buttons. Please try again."))

    @commands.hybrid_command(name="setconfig", description="(Admin) Set per-guild config: auto_delete_seconds, batch_threshold")
    @commands.has_permissions(manage_guild=True)
    async def set_config(self, ctx: commands.Context, auto_delete_seconds: Optional[int] = None, batch_threshold: Optional[int] = None):
        gid = ctx.guild.id if ctx.guild else None
        cfg = guild_config.load(gid) if gid else {}
        if auto_delete_seconds is not None and auto_delete_seconds > 0:
            cfg["auto_delete_seconds"] = auto_delete_seconds
        if batch_threshold is not None and batch_threshold > 0:
            cfg["batch_threshold"] = batch_threshold
        guild_config.save(gid, cfg)
        await safe_send(ctx, content=f"Config updated: {cfg}")

    @commands.hybrid_command(name="showconfig", description="Show current per-guild config")
    async def show_config(self, ctx: commands.Context):
        gid = ctx.guild.id if ctx.guild else None
        cfg = guild_config.load(gid) if gid else {}
        await safe_send(ctx, content=f"Config: {cfg or 'defaults'}")

    @commands.hybrid_command(name="searchlinks", description="Search saved links")
    async def search_links(self, ctx: commands.Context, *, search_term: str):
        links = storage.get_saved_links()
        links = filter_links_by_guild(links, ctx.guild.id if ctx.guild else None)
        results = [l for l in links if search_term.lower() in l.get("url", "").lower() or search_term.lower() in l.get("category", "").lower()]
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
            remaining = self.rate_limiter.get_remaining(ctx.author.id, "analyze", cooldown=10.0)
            await safe_send(ctx, content=ratelimit_message(remaining))
            return
        if not is_valid_url(url):
            await safe_send(ctx, content=f"{ctx.author.mention}, invalid URL.")
            return
        async with ctx.typing():
            guidance = await get_ai_guidance(url)
            lines = guidance.splitlines()
            verdict_line = lines[0] if lines else "Keep/Skip"
            reason_line = lines[1] if len(lines) > 1 else "No reason provided."
            preview = await link_preview(url)
            embed = make_verdict_embed(url, verdict_line, reason_line, preview)
            await safe_send(ctx, embed=embed)

    @commands.hybrid_command(name="stats", description="Show link stats")
    async def show_stats(self, ctx: commands.Context):
        links = storage.get_saved_links()
        links = filter_links_by_guild(links, ctx.guild.id if ctx.guild else None)
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
                domain = urlparse(l["url"]).netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                domains[domain] = domains.get(domain, 0) + 1
            except Exception:
                pass
            author = l.get("author", "Unknown")
            authors[author] = authors.get(author, 0) + 1
        top_cats = "\n".join([f"• {k}: {v}" for k, v in sorted(categories.items(), key=lambda x: -x[1])[:5]]) or "None"
        top_domains = "\n".join([f"• {k}: {v}" for k, v in sorted(domains.items(), key=lambda x: -x[1])[:5]]) or "None"
        top_authors = "\n".join([f"• {k}: {v}" for k, v in sorted(authors.items(), key=lambda x: -x[1])[:5]]) or "None"
        stats_msg = (
            f"**📊 Link Stats**\n\nTotal links: **{total}**\n\n"
            f"**Top Categories:**\n{top_cats}\n\n"
            f"**Top Domains:**\n{top_domains}\n\n"
            f"**Top Contributors:**\n{top_authors}"
        )
        await safe_send(ctx, content=stats_msg)

    @commands.hybrid_command(name="recent", description="Show 5 most recent links")
    async def show_recent(self, ctx: commands.Context):
        links = storage.get_saved_links()
        links = filter_links_by_guild(links, ctx.guild.id if ctx.guild else None)
        if not links:
            await safe_send(ctx, content="No links saved yet!")
            return
        recent = links[-5:][::-1]
        response = "**🕒 Recently Saved:**\n\n"
        for i, l in enumerate(recent, 1):
            response += f"{i}. **[{l.get('category','Uncategorized')}]** {l['url']}\n   *by {l.get('author','Unknown')} at {l.get('timestamp','')}*\n"
        await safe_send(ctx, content=response)

    @commands.hybrid_command(name="audit_server", description="(Admin) Run an AI audit for a topic")
    @commands.has_permissions(manage_guild=True)
    async def audit_server(self, ctx: commands.Context, *, topic: str = "full server"):
        await ctx.defer()
        guild = ctx.guild
        if not guild:
            await safe_send(ctx, content="This must be used in a server.")
            return
        ai_resp = await ai_server_audit(guild, topic=topic, extra_context=f"Requested by {ctx.author.display_name}. Site: {COMMUNITY_LEARNING_URL}")
        preview = "\n".join(ai_resp.splitlines()[:8])
        await safe_send(ctx, content=f"**AI Audit: {topic}**\n\n{preview[:1500]}")
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
>_ Session: {SESSION_ID[:8]}
>_ AI:  {'ENABLED ✅' if AI_ENABLED else 'DISABLED ⚠️'}
>_ Guilds: {len(bot.guilds)}
╚═══════════════════════════════════════════════╝
"""
    logger.info(ready_banner)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await safe_send(ctx, content="Missing argument! Check `!help`.")
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
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
