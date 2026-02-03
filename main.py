#!/usr/bin/env python3
"""
Link Manager - main.py
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
import json
from typing import Optional, List, Dict, Callable, Awaitable
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread, Lock

import storage
from utils import logger, is_valid_url, RateLimiter, EventCleanup

# Optional imports for document processing
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import docx
except ImportError:
    docx = None

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    import striprtf
except ImportError:
    striprtf = None

try:
    import pandas as pd
except ImportError:
    pd = None

SESSION_ID = str(uuid.uuid4())
load_dotenv()

AUTO_DELETE_ENABLED = os.environ.get("AUTO_DELETE_ENABLED", "1") == "1"
try:
    AUTO_DELETE_SECONDS_DEFAULT = int(os.environ.get("AUTO_DELETE_AFTER", "5"))
except ValueError:
    AUTO_DELETE_SECONDS_DEFAULT = 5

BATCH_WINDOW_SECONDS = 3
BATCH_THRESHOLD_DEFAULT = 5
CONFIRM_TIMEOUT = 4

RULES_FILE = "server_rules.txt"

URL_REGEX = r'(?:https?://)\S+'
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

try:
    SECURITY_ALERT_CHANNEL_ID = int(os.environ.get("SECURITY_ALERT_CHANNEL_ID", "0") or 0)
except ValueError:
    SECURITY_ALERT_CHANNEL_ID = 0
    logger.warning("SECURITY_ALERT_CHANNEL_ID must be an integer; defaulting to 0.")


class GuildConfig:
    def __init__(self):
        self.configs = {}
        self.path = "guild_configs.json"
        self._lock = Lock()
        self.load_all()

    def load_all(self):
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.configs = json.load(f)
            except FileNotFoundError:
                self.configs = {}
            except Exception as e:
                logger.error(f"Failed to load guild configs: {e}")
                self.configs = {}

    def save_all(self):
        with self._lock:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.configs, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error(f"Failed to save guild configs: {e}")

    def load(self, gid):
        return self.configs.get(str(gid), {})

    def save(self, gid, cfg):
        self.configs[str(gid)] = cfg
        self.save_all()

    def get_value(self, gid, key, default):
        cfg = self.load(gid)
        return cfg.get(key, default)


guild_config = GuildConfig()


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


async def download_bytes(url: str) -> Optional[bytes]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    content_type = resp.headers.get('Content-Type', '')
                    if (not content_type) or any(ct in content_type for ct in ALLOWED_CONTENT_TYPES):
                        data = await resp.read()
                        if len(data) <= MAX_DOWNLOAD_BYTES:
                            return data
    except Exception as e:
        logger.debug(f"download_bytes error: {e}")
    return None


def get_link_verdict() -> tuple[str, str]:
    return ("Review manually", "Automated analysis is disabled. Please review this link yourself.")


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
╔═══════════════════════════════════════════════╗
║  🤖 LINK MANAGER BOT v3.0                     ║
╚═══════════════════════════════════════════════╝
>_[0m [1;37mLINK MANAGER v3.0[0m [2;33m// NEURAL LINK MANAGER[0m
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
[1;35m┌─[0m [1;37mANALYSIS_MODULES[0m [1;35m────────────────────────────┐[0m
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
[1;32m│ ◆[0m Safety Check (manual)
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
[2;35m║[0m ⚡ Drop a link → Review → Save/Ignore         [2;35m║[0m
[2;35m║[0m ⚡ Upload document → Click summarize button   [2;35m║[0m
[2;36m╚═══════════════════════════════════════════════╝[0m
[2;33m>_[0m Powered by Link Manager
```""",
        inline=False,
    )
    embed.set_footer(text="[SYSTEM] Neural Link Established • Use /cmdinfo <command> for details")
    embed.timestamp = datetime.datetime.utcnow()
    return embed


def make_compact_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚡ LINK MANAGER // COMMAND INDEX",
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
        value="`/searchlinks` • `/stats` • `/recent`",
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
            "→ Auto-detect links\n"
            "→ Summarize documents (.pdf/.docx/.txt/.csv/.xls[x])\n"
            "→ Burst protection queuing"
        ),
        inline=False
    )
    embed.set_footer(text="💡 Drop any link to review • Upload docs for instant summary")
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
    if pd is None:
        return None
    try:
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
            if pd is None:
                return None
            try:
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
            if PdfReader is None:
                return None
            try:
                with io.BytesIO(data) as bio:
                    reader = PdfReader(bio)
                    pages = [p.extract_text() or "" for p in reader.pages]
                    return "\n".join(pages)
            except Exception as e:
                logger.debug(f"PDF extraction error: {e}")
                return None
        if name.endswith(".docx"):
            if docx is None:
                return None
            try:
                with io.BytesIO(data) as bio:
                    doc = docx.Document(bio)
                    return "\n".join(p.text for p in doc.paragraphs)
            except Exception as e:
                logger.debug(f"DOCX extraction error: {e}")
                return None
        if name.endswith((".html", ".htm", ".xhtml", ".asp", ".aspx")):
            if BeautifulSoup is None:
                return None
            try:
                soup = BeautifulSoup(data, "html.parser")
                return soup.get_text(" ", strip=True)
            except Exception as e:
                logger.debug(f"HTML extraction error: {e}")
                return None
        if name.endswith(".rtf"):
            if striprtf is None:
                return None
            try:
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
        return "⚠️ Couldn't extract text. Ensure required libraries are installed (PyPDF2, python-docx, beautifulsoup4, pandas, striprtf) or provide a .txt version."
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = "\n".join(lines[:10]) if lines else text[:1500]
    return f"Summary (excerpt):\n{summary}"


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
# UI Components
# ---------------------------------------------------------------------------

def ack_interaction(interaction, ephemeral=False):
    if ephemeral:
        return interaction.response.defer(ephemeral=True)
    else:
        return interaction.response.defer()


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


class MultiLinkSelectView(discord.ui.View):
    def __init__(self, links_data, author_id, original_message, cog):
        super().__init__(timeout=300)
        self.links_data = links_data
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.message = None

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Save All", style=discord.ButtonStyle.green, emoji="💾")
    async def save_all(self, interaction, button):
        await ack_interaction(interaction, ephemeral=True)
        # Placeholder: Implement saving logic here
        await safe_send(interaction.followup, content="✅ All links saved (placeholder).", ephemeral=True)


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


class LinkManagerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_links = {}
        self.guild_pending_counts = {}
        self.links_to_categorize = {}

    async def _get_preferred_prefix(self, message):
        return "!"

    async def handle_summarize_preview_ctx(self, interaction, message):
        # Placeholder: Implement summarization logic here
        await interaction.response.send_message("📝 Summarization not implemented yet.", ephemeral=True)


# ---------------------------------------------------------------------------
# Events & startup
# ---------------------------------------------------------------------------
app = Flask('')
@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get("PORT", "8080"))
    logger.info(f"Keep-alive server starting on port {port}")
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()

@bot.event
async def on_ready():
    ready_banner = f"""
╔═══════════════════════════════════════════════╗
║  🤖 LINK MANAGER BOT ONLINE                    ║
╚═══════════════════════════════════════════════╝
>_[0m [1;37mLINK MANAGER v3.0[0m [2;33m// NEURAL LINK MANAGER[0m
[2;35m>_[0m [2;37mStatus:[0m [1;32m[ONLINE][0m [2;33m// Session:  ACTIVE[0m
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
    logger.info("Starting Link Manager Bot...")
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        keep_alive()
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
