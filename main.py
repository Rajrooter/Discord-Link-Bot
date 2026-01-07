# (full file contents below)
import datetime
import json
import os
import re
import time
from collections import deque
from urllib.parse import urlparse
import asyncio
import aiohttp

import discord
from discord.ext import commands
from dotenv import load_dotenv

import storage
from utils import logger, is_valid_url, RateLimiter, EventCleanup

# Load environment variables
load_dotenv()

# NEW Google GenAI SDK (replaces google.generativeai)
from google import genai

# ============================================
# FIXED GOOGLE GEMINI CONFIGURATION - NEW SDK
# ============================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    AI_ENABLED = True
    logger.info("✅ Google Gemini AI enabled (gemini-2.0-flash-exp)")
else:
    ai_client = None
    AI_ENABLED = False
    logger.warning("⚠️ AI disabled - Add GEMINI_API_KEY to enable")

# Auto-delete configuration: enable and seconds (default 5)
AUTO_DELETE_ENABLED = os.environ.get("AUTO_DELETE_ENABLED", "1") == "1"
try:
    AUTO_DELETE_SECONDS = int(os.environ.get("AUTO_DELETE_AFTER", "5"))
except ValueError:
    AUTO_DELETE_SECONDS = 5

# Burst batching configuration
BATCH_WINDOW_SECONDS = 3   # window length to observe link burst
BATCH_THRESHOLD = 5        # if more than this many links arrive in window, enable batching

# Confirmation timeout for accidental ❌ press
CONFIRM_TIMEOUT = 4  # seconds before the "are you sure?" message vanishes

async def get_ai_guidance(url: str, max_retries: int = 3) -> str:
    """Get AI guidance on whether a link is vital for study purposes."""

    if not AI_ENABLED or ai_client is None:
        return "📝 **Manual Review Needed** - AI analysis unavailable."

    prompt = f"""Evaluate this URL for study purposes and safety in exactly 2 lines:

URL: {url}

Format your response as:
Line 1: Keep or Skip (single word)
Line 2: One short sentence explaining why keep/skip and mention safety (Safe/Suspect/Unsafe)

Example response:
Keep
High-value educational resource for machine learning, Safe."""

    for attempt in range(max_retries):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    ai_client.models.generate_content,
                    model='gemini-2.0-flash-exp',
                    contents=prompt
                ),
                timeout=10.0
            )

            if hasattr(response, "text"):
                return response.text
            return str(response)
        except asyncio.TimeoutError:
            if attempt == max_retries - 1:
                logger.error(f"AI analysis timeout for {url}")
                return "⚠️ AI analysis timeout - please review manually."
            await asyncio.sleep(1 * (attempt + 1))
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"AI Error after {max_retries} attempts for {url}: {e}")
                return "⚠️ AI analysis failed - please review manually."
            await asyncio.sleep(1 * (attempt + 1))

def is_suspicious_link(url):
    """Simple check for common phishing/spam patterns before AI processing"""
    phishing_keywords = ['login-', 'verify-', 'secure-', 'update-account', 'banking-']
    url_lower = url.lower()
    for kw in phishing_keywords:
        if kw in url_lower:
            return True
    return False

# Custom Help Command for a more "adorable" UI/UX
class AdorableHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__()

    async def send_bot_help(self, mapping):
        embed = discord.Embed(
            title="✨ Labour Bot Command Center ✨",
            description="Hello! I'm here to help you manage your links and guide you with commands 💖",
            color=discord.Color.from_rgb(255, 182, 193)  # Soft Pink
        )

        for cog, commands_ in mapping.items():
            filtered = await self.filter_commands(commands_, sort=True)
            command_signatures = [f"`!{c.name}`" for c in filtered]
            if command_signatures:
                cog_name = getattr(cog, "qualified_name", "Other")
                if cog_name == "LinkManager":
                    cog_name = "🔗 Link Management"

                embed.add_field(
                    name=cog_name,
                    value=" ".join(command_signatures),
                    inline=False
                )

        embed.add_field(
            name="💡 Quick Tip",
            value="Type `!help [command]` to see more details! ✨",
            inline=False
        )
        
        if AI_ENABLED:
            embed.add_field(
                name="🤖 AI Status",
                value="✅ **Google Gemini AI Enabled** ",
                inline=False
            )
        else:
            embed.add_field(
                name="🤖 AI Status",
                value="⚠️ **AI Disabled** - Get free AI by adding GEMINI_API_KEY",
                inline=False
            )
            
        embed.set_footer(text="Digital Labour ❤️ Made by RAJ ARYAN")

        channel = self.get_destination()
        await channel.send(embed=embed)

    async def send_command_help(self, command):
        embed = discord.Embed(
            title=f"✨ Command: !{command.name}",
            description=command.help or "No description provided.",
            color=discord.Color.from_rgb(173, 216, 230)  # Light Blue
        )
        alias = ", ".join(command.aliases)
        if alias:
            embed.add_field(name="Aliases", value=f"`{alias}`", inline=True)

        embed.add_field(name="Usage", value=f"`!{command.name} {command.signature}`", inline=False)

        channel = self.get_destination()
        await channel.send(embed=embed)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

# Function to handle both ! and @mentions as prefixes
def get_prefix(bot, message):
    prefixes = ['!']
    return commands.when_mentioned_or(*prefixes)(bot, message)

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=AdorableHelp())

# Files to store data
LINKS_FILE = "saved_links.json"
CATEGORIES_FILE = "categories.json"
ONBOARDING_FILE = "onboarding_data.json"
RULES_FILE = "server_rules.txt"

# Improved URL regex pattern (matches http(s) and www.)
URL_REGEX = r'(?:https?://|www\.)\S+'

# File extensions to ignore
IGNORED_EXTENSIONS = [
    '.gif', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.mp4', '.mov', '.avi'
]

def is_media_url(url):
    """Check if a URL points to a media file that should be ignored"""
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()

        for ext in IGNORED_EXTENSIONS:
            if path.endswith(ext):
                return True

        media_domains = [
            'giphy.com', 'tenor.com', 'imgur.com', 'gyazo.com',
            'streamable.com', 'clippy.gg', 'cdn.discordapp.com',
            'media.discordapp.net'
        ]

        domain = parsed.netloc.lower()
        return any(media_domain in domain for media_domain in media_domains)
    except:
        return False

# Load/Save functions (now use storage adapter)
def load_links():
    return storage.get_saved_links()

def save_links(links):
    # For compatibility, clear and re-add all links
    storage.clear_saved_links()
    for link in links:
        storage.add_saved_link(link)

def load_categories():
    return storage.get_categories()

def save_categories(categories):
    # For compatibility, clear and rebuild
    storage.clear_categories()
    for cat_name, links in categories.items():
        for link in links:
            storage.add_link_to_category(cat_name, link)

def load_onboarding_data():
    return storage.load_onboarding_data()

def save_onboarding_data(data):
    storage.save_onboarding_data(data)

def load_rules():
    try:
        with open(RULES_FILE, "r") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "📒 Server Rules:\n"
            "1. Please read and acknowledge these rules to ensure our community remains a great place for everyone.\n"
            "2. Welcome to Labour - Be respectful and helpful.\n"
            "3. Share educational content only.\n"
            "4. No spam or inappropriate links."
        )

def save_rules(rules):
    with open(RULES_FILE, "w") as f:
        f.write(rules)


# Discord UI Button Views
class DisclaimerView(discord.ui.View):
    """View for asking if user wants to save any links from their message"""

    def __init__(self, links: list, author_id: int, original_message, cog):
        super().__init__(timeout=60)
        self.links = links
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.message = None

    async def on_timeout(self):
        try:
            if self.message:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
        except Exception as e:
            logger.debug(f"Disclaimer view timeout error: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This button is not for you!", 
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Yes, I want to save links", style=discord.ButtonStyle.green, emoji="✅")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """User wants to proceed with link saving"""
        await interaction.response.defer()
        
        # Delete the disclaimer message
        try:
            await self.message.delete()
        except Exception as e:
            logger.debug(f"Error deleting disclaimer message: {e}")
        
        # Now show the multiple link selection dropdown
        links_data = [{"url": link} for link in self.links]
        
        embed = discord.Embed(
            title="📎 Multiple Links Detected",
            description=f"Found **{len(self.links)}** links in your message.\n\n"
                       f"Select which ones you'd like to review from the dropdown below:",
            color=discord.Color.blue()
        )
        
        selection_view = MultiLinkSelectView(links_data, self.author_id, self.original_message, self.cog)
        prompt_msg = await interaction.channel.send(embed=embed, view=selection_view)
        selection_view.message = prompt_msg

    @discord.ui.button(label="No, ignore these links", style=discord.ButtonStyle.red, emoji="❌")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """User doesn't want to save any links"""
        await interaction.response.send_message(
            "👍 Got it! Links will be ignored.",
            ephemeral=True
        )
        
        # Delete the disclaimer message (but keep the original message)
        try:
            await self.message.delete()
        except Exception as e:
            logger.debug(f"Error deleting disclaimer message: {e}")


class LinkActionView(discord.ui.View):
    """View with Save/Ignore buttons for link management"""

    def __init__(self, link: str, author_id: int, original_message, pending_db_id: str, cog):
        super().__init__(timeout=300)
        self.link = link
        self.author_id = author_id
        self.original_message = original_message
        self.pending_db_id = pending_db_id
        self.cog = cog
        self.message = None

    async def on_timeout(self):
        try:
            if self.message:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
        except Exception as e:
            logger.debug(f"View timeout cleanup error: {e}")
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the original author to interact"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This button is not for you!", 
                ephemeral=True
            )
            return False
        return True
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.green, emoji="✅")
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle Save button click"""
        # Remove from DB
        await asyncio.to_thread(storage.delete_pending_link_by_id, self.pending_db_id)
        
        # Remove from in-memory pending_links
        if interaction.message.id in self.cog.pending_links:
            del self.cog.pending_links[interaction.message.id]
        
        # Add to links_to_categorize
        self.cog.links_to_categorize[self.author_id] = {
            "link": self.link,
            "message": self.original_message
        }
        
        # Send ephemeral instruction
        await interaction.response.send_message(
            f"✅ Link marked for saving! Use `!category <name>` to finalize.",
            ephemeral=True
        )
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
    
    @discord.ui.button(label="Ignore", style=discord.ButtonStyle.red, emoji="❌")
    async def ignore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle Ignore button click - show confirmation"""
        # Create confirmation view
        confirm_view = ConfirmDeleteView(
            self.link,
            self.author_id,
            self.original_message,
            self.pending_db_id,
            interaction.message.id,
            self.cog
        )
        
        await interaction.response.send_message(
            "⚠️ Are you sure you want to delete this link?",
            view=confirm_view,
            ephemeral=True
        )


class MultiLinkSelectView(discord.ui.View):
    """View for selecting multiple links with a dropdown"""

    def __init__(self, links: list, author_id: int, original_message, cog):
        super().__init__(timeout=300)
        self.links = links
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.selected_links = []
        self.message = None

        # CRITICAL FIX: Limit to 25 options (Discord's hard limit)
        max_options = min(len(links), 25)
        
        options = []
        for idx in range(max_options):  # Only process first 25 links
            try:
                link_info = links[idx]
                url = link_info.get("url", "")
                
                if not url:
                    logger.warning(f"Link info missing URL: {link_info}")
                    continue
                
                label = f"Link {idx + 1}"
                
                # Truncate description to fit Discord limits (100 chars max)
                description = url
                if len(description) > 100:
                    description = description[:97] + "..."
                
                options.append(discord.SelectOption(
                    label=label,
                    value=str(idx),
                    description=description
                ))
            except Exception as e:
                logger.error(f"Error creating option for link {idx}: {e}")
                continue
        
        # Ensure we have at least 1 option
        if not options:
            logger.error("No valid options created for MultiLinkSelectView")
            # Add a dummy option to prevent crash
            options.append(discord.SelectOption(
                label="No valid links",
                value="0",
                description="Error processing links"
            ))
        
        # Add warning if we had to truncate
        if len(links) > 25:
            logger.info(f"Truncated {len(links)} links to 25 for dropdown menu")

        self.add_item(discord.ui.Select(
            placeholder=f"Select links to save ({min(len(links), 25)} available)",
            min_values=1,
            max_values=min(len(options), 25),
            options=options,
            custom_id="link_selector"
        ))

    async def on_timeout(self):
        try:
            if self.message:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
        except Exception as e:
            logger.debug(f"Multi-link view timeout error: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You are not the author, fool😎", ephemeral=True)
            return False

        if interaction.data.get("custom_id") == "link_selector":
            values = interaction.data.get("values", [])
            self.selected_links = [int(v) for v in values]

            await interaction.response.defer()

            if self.selected_links:
                confirm_view = ConfirmMultiLinkView(
                    self.links, 
                    set(self.selected_links), 
                    self.author_id, 
                    self.original_message, 
                    self.cog
                )
                confirm_msg = await interaction.channel.send(
                    f"✅ **{len(self.selected_links)} link(s) selected**\n\nConfirm to save these links?",
                    view=confirm_view
                )
                confirm_view.message = confirm_msg

                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)

            return False

        return True


class ConfirmMultiLinkView(discord.ui.View):
    """Confirmation view for saving selected links"""

    def __init__(self, links: list, selected_indices: set, author_id: int, original_message, cog):
        super().__init__(timeout=60)
        self.links = links
        self.selected_indices = selected_indices
        self.author_id = author_id
        self.original_message = original_message
        self.cog = cog
        self.message = None

    async def on_timeout(self):
        try:
            if self.message:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
        except Exception as e:
            logger.debug(f"Confirm multi-link view timeout error: {e}")

    @discord.ui.button(label="Save All Selected", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        saved_count = 0
        for idx in self.selected_indices:
            try:
                link_info = self.links[idx]
                link = link_info["url"]

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

                await interaction.channel.send(
                    f"{interaction.user.mention}, link {saved_count} saved to queue!\n"
                    f"Use `!category <name>` to save or `!cancel` to skip.\n"
                    f"`{link[:100]}{'...' if len(link) > 100 else ''}`"
                )
            except Exception as e:
                logger.error(f"Error saving link {idx}: {e}")

        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


class ConfirmDeleteView(discord.ui.View):
    """Confirmation view for deleting a link"""

    def __init__(self, link: str, author_id: int, original_message, pending_db_id: str, bot_msg_id: int, cog):
        super().__init__(timeout=60)
        self.link = link
        self.author_id = author_id
        self.original_message = original_message
        self.pending_db_id = pending_db_id
        self.bot_msg_id = bot_msg_id
        self.cog = cog
        self.message = None

    async def on_timeout(self):
        try:
            if self.message:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
        except Exception as e:
            logger.debug(f"Confirm view timeout cleanup error: {e}")
    
    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm deletion"""
        # Delete original user message
        try:
            if self.original_message:
                await self.original_message.delete()
        except Exception as e:
            print(f"Error deleting original message: {e}")
        
        # Delete bot prompt message
        try:
            bot_msg = await interaction.channel.fetch_message(self.bot_msg_id)
            await bot_msg.delete()
        except Exception as e:
            print(f"Error deleting bot message: {e}")
        
        # Remove from DB
        await asyncio.to_thread(storage.delete_pending_link_by_id, self.pending_db_id)
        
        # Remove from in-memory pending_links
        if self.bot_msg_id in self.cog.pending_links:
            del self.cog.pending_links[self.bot_msg_id]
        
        # Acknowledge
        await interaction.response.send_message(
            "🗑️ Link deleted successfully.",
            ephemeral=True
        )
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel deletion"""
        await interaction.response.send_message(
            "Deletion cancelled.",
            ephemeral=True
        )
        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)


class LinkManager(commands.Cog):
    """Handles link saving and management functionality"""

    def __init__(self, bot):
        logger.info(f"LinkManager.__init__ called. PID={os.getpid()}")
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

    async def ensure_roles_exist(self):
        """Ensure all required roles for onboarding exist"""
        guild = None
        for g in self.bot.guilds:
            guild = g
            break

        if not guild:
            return

        required_roles = [
            "Male", "Female", "Other",
            "Data Science", "IT", "Other Department",
            "1st Year", "2nd Year", "3rd Year", "4th Year", "Graduate"
        ]

        for role_name in required_roles:
            if not discord.utils.get(guild.roles, name=role_name):
                try:
                    await guild.create_role(name=role_name)
                    print(f"Created role: {role_name}")
                except discord.Forbidden:
                    print(f"Missing permissions to create role: {role_name}") 
                except Exception as e:
                    print(f"Error creating role {role_name}: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Handle new member joins with onboarding process"""
        try:
            embed = discord.Embed(
                title="Welcome to Labour!",
                description="Please complete the onboarding process to access all channels.",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Step 1: Read the Rules",
                value="Please read our server rules carefully.",
                inline=False
            )
            embed.add_field(
                name="Step 2: Complete Onboarding",
                value="Use `!startonboarding` in the server to begin.",
                inline=False
            )

            await member.send(embed=embed)

            rules = load_rules()
            rules_embed = discord.Embed(
                title="Server Rules",
                description=rules,
                color=discord.Color.red()
            )
            await member.send(embed=rules_embed)

        except discord.Forbidden:
            for channel in member.guild.channels:
                if channel.name in ["general", "welcome"]:
                    await channel.send(
                        f"{member.mention}, welcome! Please enable DMs to complete onboarding, "
                        f"or use `!startonboarding` in this channel."
                    )
                    break

    async def cleanup_old_channel_events(self):
        """Periodically clean up old channel event tracking"""
        while True:
            try:
                await asyncio.sleep(3600)
                self.event_cleanup.cleanup_memory()
                logger.info("Cleaned up old channel events")
            except Exception as e:
                logger.error(f"Event cleanup error: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Bot ready: {self.bot.user} PID={os.getpid()}")

        try:
            storage_backend = storage.get_storage()
            if isinstance(storage_backend, storage.MongoDBStorage):
                logger.info("✅ MongoDB storage validated")
            else:
                logger.warning("⚠️ Using JSON file storage - MongoDB not available")
        except Exception as e:
            logger.error(f"Storage initialization failed: {e}")

        await self.ensure_roles_exist()

        if not self.cleanup_task or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self.cleanup_old_channel_events())
            logger.info("Started event cleanup task")

    async def _delete_if_no_response(self, bot_message, original_message, pending_db_id, delay=AUTO_DELETE_SECONDS):
        """Delete only the bot prompt if user didn't respond within delay."""
        if not AUTO_DELETE_ENABLED:
            return
        await asyncio.sleep(delay)
        try:
            if bot_message and bot_message.id in self.pending_links:
                try:
                    await bot_message.delete()
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    logger.warning("Bot lacks permissions to delete its own message.")
                except Exception as e:
                    logger.warning(f"Error deleting bot message: {e}")

                try:
                    if bot_message.id in self.pending_links:
                        del self.pending_links[bot_message.id]
                except Exception:
                    pass

                try:
                    await asyncio.to_thread(storage.delete_pending_link_by_id, pending_db_id)
                except Exception as e:
                    logger.warning(f"Error deleting pending link from DB: {e}")
        except Exception as e:
            logger.warning(f"Auto-delete check error: {e}")

    async def _auto_remove_confirmation(self, confirm_msg, delay=CONFIRM_TIMEOUT):
        """Auto remove the temporary confirmation message and its pending entry."""
        await asyncio.sleep(delay)
        try:
            await confirm_msg.delete()
        except Exception:
            pass
        try:
            if confirm_msg.id in self.pending_delete_confirmations:
                del self.pending_delete_confirmations[confirm_msg.id]
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.id in self.processed_messages:
            return

        self.processed_messages.add(message.id)
        await self.bot.process_commands(message)

        if len(self.processed_messages) > 1000:
            self.processed_messages = set(list(self.processed_messages)[-1000:])

        # Check for onboarding responses
        onboarding_data = load_onboarding_data()
        user_id = str(message.author.id)

        if user_id in onboarding_data:
            user_data = onboarding_data[user_id]

            if user_data["state"] == "college":
                user_data["data"]["college"] = message.content
                user_data["state"] = "referral"

                embed = discord.Embed(
                    title="Onboarding - Referral",
                    description="Who referred you to this server? (Type a name or 'None')",
                    color=discord.Color.green()
                )

                msg = await message.channel.send(embed=embed)
                user_data["message_id"] = msg.id
                onboarding_data[user_id] = user_data
                save_onboarding_data(onboarding_data)

                try:
                    await message.delete()
                except:
                    pass
                return

            elif user_data["state"] == "referral":
                user_data["data"]["referral"] = message.content
                user_data["state"] = "confirm"

                embed = discord.Embed(
                    title="Please Confirm Your Information",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Gender", value=user_data["data"]["gender"], inline=True)
                embed.add_field(name="Department", value=user_data["data"]["department"], inline=True)
                embed.add_field(name="Year", value=user_data["data"]["year"], inline=True)
                embed.add_field(name="College", value=user_data["data"]["college"], inline=True)
                embed.add_field(name="Referral", value=user_data["data"]["referral"], inline=True)
                embed.set_footer(text="React with ✅ to confirm or ❌ to start over")

                msg = await message.channel.send(embed=embed)
                await msg.add_reaction('✅')
                await msg.add_reaction('❌')

                user_data["message_id"] = msg.id
                onboarding_data[user_id] = user_data
                save_onboarding_data(onboarding_data)

                try:
                    await message.delete()
                except:
                    pass
                return

        # Check for links
        try:
            urls = [m.group(0) for m in re.finditer(URL_REGEX, message.content)]
        except re.error as e:
            print(f"Regex error: {e}")
            urls = []

        if urls:
            non_media_links = [link for link in urls if not is_media_url(link) and is_valid_url(link)]

            if len(non_media_links) > 1:
                # SAFETY CHECK: If too many links, batch them instead
                if len(non_media_links) > 25:
                    await message.channel.send(
                        f"📎 **{len(non_media_links)} links detected** - that's a lot!\n\n"
                        f"Processing links in batches. Use `!pendinglinks` to review them all.\n"
                        f"_Showing first 25 in dropdown..._"
                    )
                    # Only show first 25 in dropdown, rest go to pending
                    dropdown_links = non_media_links[:25]
                    remaining_links = non_media_links[25:]
                    
                    # Add remaining to pending batch
                    for link in remaining_links:
                        pending_entry = {
                            "user_id": message.author.id,
                            "link": link,
                            "channel_id": message.channel.id,
                            "original_message_id": message.id,
                            "timestamp": datetime.datetime.utcnow().isoformat()
                        }
                        pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                        
                        self.pending_batches.setdefault(message.author.id, []).append({
                            "link": link,
                            "original_message": message,
                            "timestamp": time.time(),
                            "pending_db_id": pending_id
                        })
                else:
                    dropdown_links = non_media_links
                
                # FIRST: Show disclaimer asking if user wants to save any links
                disclaimer_embed = discord.Embed(
                    title="💡 Multiple Links Detected",
                    description=f"I found **{len(non_media_links)}** links in your message.\n\n"
                               f"**Do you want to save any of these links?**",
                    color=discord.Color.gold()
                )
                disclaimer_embed.set_footer(text="Choose an option below")
                
                disclaimer_view = DisclaimerView(dropdown_links, message.author.id, message, self)
                disclaimer_msg = await message.channel.send(embed=disclaimer_embed, view=disclaimer_view)
                disclaimer_view.message = disclaimer_msg
                
                logger.info(f"Multiple links detected: {len(non_media_links)} links from {message.author}")
                return

            for link in non_media_links:
                ch_id = message.channel.id
                now = time.time()

                self.event_cleanup.add_event(ch_id, now)
                self.event_cleanup.cleanup_old_events(ch_id, BATCH_WINDOW_SECONDS)
                event_count = self.event_cleanup.get_event_count(ch_id, BATCH_WINDOW_SECONDS)

                if event_count > BATCH_THRESHOLD:
                    # Save to DB immediately
                    pending_entry = {
                        "user_id": message.author.id,
                        "link": link,
                        "channel_id": message.channel.id,
                        "original_message_id": message.id,
                        "timestamp": datetime.datetime.utcnow().isoformat()
                    }
                    pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                    
                    self.pending_batches.setdefault(message.author.id, []).append({
                        "link": link,
                        "original_message": message,
                        "timestamp": now,
                        "pending_db_id": pending_id
                    })
                    # Optionally: silent ack or small ephemeral reaction to mark stored
                    try:
                        await message.add_reaction("🗂️")
                    except Exception:
                        pass
                    continue

                # Normal behavior: Save to DB immediately, create AI prompt with buttons
                pending_entry = {
                    "user_id": message.author.id,
                    "link": link,
                    "channel_id": message.channel.id,
                    "original_message_id": message.id,
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
                pending_id = await asyncio.to_thread(storage.add_pending_link, pending_entry)
                
                # Get AI guidance
                guidance = await get_ai_guidance(link)
                
                # Create button view
                view = LinkActionView(link, message.author.id, message, pending_id, self)
                
                ask_msg = await message.channel.send(
                    f"🤖 **AI Analysis:**\n{guidance}\n\n"
                    f"📎 Save this link, {message.author.mention}?\n`{link}`",
                    view=view
                )
                
                # Update DB with bot message ID
                if pending_id:
                    await asyncio.to_thread(storage.update_pending_with_bot_msg_id, pending_id, ask_msg.id)

                # Store pending link keyed by the bot message id
                self.pending_links[ask_msg.id] = {
                    "link": link,
                    "author_id": message.author.id,
                    "original_message": message,
                    "pending_db_id": pending_id
                }

                # Schedule deletion of the original user message and prompt if no response
                try:
                    asyncio.create_task(self._delete_if_no_response(ask_msg, message, pending_id, delay=AUTO_DELETE_SECONDS))
                except Exception as e:
                    print(f"Failed to schedule auto-delete check: {e}")

    @commands.command(name='pendinglinks', help='Review your pending links captured during bursts')
    async def pendinglinks_command(self, ctx):
        user_id = ctx.author.id

        if self.rate_limiter.is_limited(user_id, 'pendinglinks', cooldown=5.0):
            remaining = self.rate_limiter.get_remaining(user_id, 'pendinglinks', cooldown=5.0)
            await ctx.send(f"{ctx.author.mention}, please wait {remaining:.1f}s before using this command again.", delete_after=5)
            return

        if user_id in self.pendinglinks_in_progress:
            await ctx.send(f"{ctx.author.mention}, you already have a pending links review in progress.")
            return

        self.pendinglinks_in_progress.add(user_id)
        
        try:
            # Fetch from DB
            pending_from_db = await asyncio.to_thread(storage.get_pending_links_for_user, user_id)
            
            # Also check in-memory batch
            batch = self.pending_batches.get(user_id, [])
            
            if not pending_from_db and not batch:
                await ctx.send(f"{ctx.author.mention}, you have no pending links.")
                return

            # Process DB pending links
            for db_entry in pending_from_db:
                link = db_entry.get("link")
                pending_id = db_entry.get("_id")
                orig_msg_id = db_entry.get("original_message_id")
                
                # Try to fetch original message
                orig_msg = None
                try:
                    orig_msg = await ctx.channel.fetch_message(orig_msg_id)
                except:
                    pass
                
                guidance = await get_ai_guidance(link)
                
                # Create button view
                view = LinkActionView(link, ctx.author.id, orig_msg, pending_id, self)
                
                ask_msg = await ctx.send(
                    f"🤖 **AI Analysis:**\n{guidance}\n\n"
                    f"📎 Save this pending link, {ctx.author.mention}?\n`{link}`",
                    view=view
                )
                
                # Update DB with bot message ID
                if pending_id:
                    await asyncio.to_thread(storage.update_pending_with_bot_msg_id, pending_id, ask_msg.id)

                self.pending_links[ask_msg.id] = {
                    "link": link,
                    "author_id": ctx.author.id,
                    "original_message": orig_msg,
                    "pending_db_id": pending_id
                }

                try:
                    asyncio.create_task(self._delete_if_no_response(ask_msg, orig_msg, pending_id, delay=AUTO_DELETE_SECONDS))
                except Exception as e:
                    print(f"Failed to schedule auto-delete for pendinglink prompt: {e}")
            
            # Process in-memory batch
            for entry in batch:
                link = entry["link"]
                orig_msg = entry.get("original_message")
                pending_id = entry.get("pending_db_id")
                
                guidance = await get_ai_guidance(link)
                
                view = LinkActionView(link, ctx.author.id, orig_msg, pending_id, self)
                
                ask_msg = await ctx.send(
                    f"🤖 **AI Analysis:**\n{guidance}\n\n"
                    f"📎 Save this pending link, {ctx.author.mention}?\n`{link}`",
                    view=view
                )
                
                # Update DB with bot message ID
                if pending_id:
                    await asyncio.to_thread(storage.update_pending_with_bot_msg_id, pending_id, ask_msg.id)

                self.pending_links[ask_msg.id] = {
                    "link": link,
                    "author_id": ctx.author.id,
                    "original_message": orig_msg,
                    "pending_db_id": pending_id
                }

                try:
                    asyncio.create_task(self._delete_if_no_response(ask_msg, orig_msg, pending_id, delay=AUTO_DELETE_SECONDS))
                except Exception as e:
                    print(f"Failed to schedule auto-delete for pendinglink prompt: {e}")

            # Clear the user's batch once prompts are created
            try:
                if user_id in self.pending_batches:
                    del self.pending_batches[user_id]
            except KeyError:
                pass
        
        finally:
            # Remove from in-progress
            self.pendinglinks_in_progress.discard(user_id)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user == self.bot.user:
            return

        # Handle confirmation replies
        if reaction.message.id in self.pending_delete_confirmations:
            confirm_data = self.pending_delete_confirmations[reaction.message.id]
            if user.id != confirm_data["author_id"]:
                return

            if str(reaction.emoji) == '✅':
                bot_msg_id = confirm_data["bot_msg_id"]
                link_data = self.pending_links.get(bot_msg_id)
                if link_data:
                    try:
                        orig = link_data.get("original_message")
                        if orig:
                            await orig.delete()
                    except:
                        pass

                    try:
                        bot_prompt = await reaction.message.channel.fetch_message(bot_msg_id)
                        await bot_prompt.delete()
                    except:
                        pass

                    try:
                        if bot_msg_id in self.pending_links:
                            del self.pending_links[bot_msg_id]
                    except:
                        pass

                try:
                    if reaction.message.id in self.pending_delete_confirmations:
                        del self.pending_delete_confirmations[reaction.message.id]
                except:
                    pass
                try:
                    await reaction.message.delete()
                except:
                    pass
                return

            elif str(reaction.emoji) == '❌':
                try:
                    if reaction.message.id in self.pending_delete_confirmations:
                        del self.pending_delete_confirmations[reaction.message.id]
                except:
                    pass
                try:
                    await reaction.message.delete()
                except:
                    pass
                return

        # Handle normal pending link prompts
        if reaction.message.id in self.pending_links:
            link_data = self.pending_links[reaction.message.id]

            if user.id != link_data["author_id"]:
                return

            if str(reaction.emoji) == '✅':
                await reaction.message.channel.send(
                    f"{user.mention}, what category for this link?\n"
                    f"Type `!category [category_name]` or `!cancel` to skip."
                )

                self.links_to_categorize[user.id] = {
                    "link": link_data["link"],
                    "message": link_data["original_message"]
                }

                try:
                    del self.pending_links[reaction.message.id]
                except KeyError:
                    pass

            elif str(reaction.emoji) == '❌':
                confirm_msg = await reaction.message.channel.send(
                    f"{user.mention}, are you sure you want to remove this link? "
                    f"React ✅ to confirm deletion or ❌ to cancel."
                )
                await confirm_msg.add_reaction('✅')
                await confirm_msg.add_reaction('❌')

                self.pending_delete_confirmations[confirm_msg.id] = {
                    "bot_msg_id": reaction.message.id,
                    "author_id": user.id
                }

                try:
                    asyncio.create_task(self._auto_remove_confirmation(confirm_msg, delay=CONFIRM_TIMEOUT))
                except Exception as e:
                    print(f"Failed to schedule confirmation auto-remove: {e}")

                return

        elif reaction.message.id in self.pending_category_deletion:
            deletion_data = self.pending_category_deletion[reaction.message.id]

            if user.id != deletion_data["author_id"]:
                return

            if str(reaction.emoji) == '✅':
                category_name = deletion_data["category"]
                categories = load_categories()
                links = load_links()

                links = [link for link in links if link["category"] != category_name]
                save_links(links)

                if category_name in categories:
                    del categories[category_name]
                    save_categories(categories)

                await reaction.message.channel.send(f"Category '{category_name}' deleted.")

            elif str(reaction.emoji) == '❌':
                await reaction.message.channel.send("Deletion cancelled.")

            del self.pending_category_deletion[reaction.message.id]

        elif reaction.message.id in self.pending_clear_all:
            clear_data = self.pending_clear_all[reaction.message.id]

            if user.id != clear_data["author_id"]:
                return

            if str(reaction.emoji) == '✅':
                links_count = len(load_links())
                categories_count = len(load_categories())
                save_links([])
                save_categories({})
                await reaction.message.channel.send(
                    f"All cleared, {user.mention}! "
                    f"Deleted {links_count} links and {categories_count} categories."
                )

            elif str(reaction.emoji) == '❌':
                await reaction.message.channel.send("Clear cancelled.")

            del self.pending_clear_all[reaction.message.id]

    @commands.command(name='category', help='Assign a category to a saved link')
    async def assign_category(self, ctx, *, category_name):
        if ctx.author.id in self.links_to_categorize:
            link_data = self.links_to_categorize[ctx.author.id]
            link = link_data["link"]
            message = link_data["message"]

            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            link_entry = {
                "url": link,
                "timestamp": timestamp,
                "author": str(message.author) if (message and message.author) else "Unknown",
                "category": category_name
            }

            await asyncio.to_thread(storage.add_saved_link, link_entry)
            await asyncio.to_thread(storage.add_link_to_category, category_name, link)

            await ctx.send(f"✅ Link saved to '{category_name}', {ctx.author.mention}!")

            del self.links_to_categorize[ctx.author.id]
        else:
            await ctx.send(f"No pending link to categorize, {ctx.author.mention}")

    @commands.command(name='cancel', help='Cancel saving a pending link')
    async def cancel_save(self, ctx):
        if ctx.author.id in self.links_to_categorize:
            del self.links_to_categorize[ctx.author.id]
            await ctx.send(f"Link save cancelled, {ctx.author.mention}")
        else:
            await ctx.send(f"No pending link, {ctx.author.mention}")

    @commands.command(name='getlinks', help='Retrieve all saved links or filter by category')
    async def get_links(self, ctx, category=None):
        links = load_links()

        if not links:
            await ctx.send("No links saved yet!")
            return

        if category:
            filtered_links = [link for link in links if link["category"].lower() == category.lower()]
            if not filtered_links:
                await ctx.send(f"No links found in category '{category}'!")
                return
            links = filtered_links
            title = f"Links in '{category}':"
        else:
            title = "All saved links:"

        response = f"**{title}**\n\n"
        for i, link in enumerate(links, 1):
            response += f"{i}. **{link['category']}** - {link['url']}\n   *(by {link['author']}, {link['timestamp']})*\n"

            if len(response) > 1500:
                await ctx.send(response)
                response = ""

        if response:
            await ctx.send(response)

    @commands.command(name='categories', help='List all categories')
    async def list_categories(self, ctx):
        categories = load_categories()

        if not categories:
            await ctx.send("No categories created yet!")
            return

        response = "**📂 Categories:**\n"
        for category, links in categories.items():
            response += f"• {category} ({len(links)} links)\n"

        await ctx.send(response)

    @commands.command(name='deletelink', help='Delete a link by its number')
    async def delete_link(self, ctx, link_number: int):
        links = load_links()

        if not links:
            await ctx.send("No links to delete!")
            return

        if link_number < 1 or link_number > len(links):
            await ctx.send(f"Invalid number! Use 1-{len(links)}.")
            return

        link_to_delete = links[link_number - 1]
        del links[link_number - 1]
        save_links(links)

        categories = load_categories()
        if link_to_delete["category"] in categories:
            if link_to_delete["url"] in categories[link_to_delete["category"]]:
                categories[link_to_delete["category"]].remove(link_to_delete["url"])
                if not categories[link_to_delete["category"]]:
                    del categories[link_to_delete["category"]]
            save_categories(categories)

        await ctx.send(f"✅ Link {link_number} deleted!")

    @commands.command(name='deletecategory', help='Delete a category and all its links')
    async def delete_category(self, ctx, *, category_name):
        categories = load_categories()

        if category_name not in categories:
            await ctx.send(f"Category '{category_name}' doesn't exist!")
            return

        confirm_msg = await ctx.send(
            f"Delete '{category_name}' and its {len(categories[category_name])} links?\n"
            f"React with ✅ to confirm or ❌ to cancel."
        )
        await confirm_msg.add_reaction('✅')
        await confirm_msg.add_reaction('❌')

        self.pending_category_deletion[confirm_msg.id] = {
            "category": category_name,
            "author_id": ctx.author.id
        }

    @commands.command(name='clearlinks', help='Clear all links (Admin only)')
    @commands.has_permissions(administrator=True)
    async def clear_links(self, ctx):
        confirm_msg = await ctx.send(
            "⚠️ Delete ALL links and categories? This cannot be undone.\n"
            "React with ✅ to confirm or ❌ to cancel."
        )
        await confirm_msg.add_reaction('✅')
        await confirm_msg.add_reaction('❌')

        self.pending_clear_all[confirm_msg.id] = {
            "author_id": ctx.author.id
        }

    @commands.command(name='searchlinks', help='Search for links')
    async def search_links(self, ctx, *, search_term):
        links = load_links()

        results = [link for link in links if search_term.lower() in link["url"].lower() or 
                   search_term.lower() in link["category"].lower()]

        if not results:
            await ctx.send(f"No results for '{search_term}'")
            return

        response = f"**🔍 Search results for '{search_term}':**\n\n"
        for i, link in enumerate(results, 1):
            response += f"{i}. **{link['category']}** - {link['url']}\n"

            if len(response) > 1500:
                await ctx.send(response)
                response = ""

        if response:
            await ctx.send(response)

    @commands.command(name='analyze', help='Get AI guidance on a specific link')
    async def analyze_link(self, ctx, url):
        if self.rate_limiter.is_limited(ctx.author.id, 'analyze', cooldown=10.0):
            remaining = self.rate_limiter.get_remaining(ctx.author.id, 'analyze', cooldown=10.0)
            await ctx.send(f"{ctx.author.mention}, please wait {remaining:.1f}s.", delete_after=5)
            return

        if not is_valid_url(url):
            await ctx.send(f"{ctx.author.mention}, invalid URL.", delete_after=5)
            return

        async with ctx.typing():
            guidance = await get_ai_guidance(url)
            embed = discord.Embed(
                title="🤖 AI Study Guidance",
                description=guidance,
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"URL: {url}")
            await ctx.send(embed=embed)

    @commands.command(name='stats', help='Show link statistics')
    async def show_stats(self, ctx):
        links = load_links()
        if not links:
            await ctx.send("No data for statistics!")
            return

        total_links = len(links)
        categories = {}
        domains = {}
        authors = {}

        for link in links:
            cat = link.get("category", "Uncategorized")
            categories[cat] = categories.get(cat, 0) + 1
            
            try:
                domain = urlparse(link["url"]).netloc.lower()
                if domain.startswith('www.'):
                    domain = domain[4:]
                domains[domain] = domains.get(domain, 0) + 1
            except:
                pass
                
            author = link.get("author", "Unknown")
            authors[author] = authors.get(author, 0) + 1

        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
        top_domains = sorted(domains.items(), key=lambda x: x[1], reverse=True)[:5]
        top_authors = sorted(authors.items(), key=lambda x: x[1], reverse=True)[:5]

        embed = discord.Embed(
            title="📊 Link Statistics",
            description=f"Total links: **{total_links}**",
            color=discord.Color.gold()
        )

        cat_text = "\n".join([f"• {cat}: {count}" for cat, count in top_categories])
        embed.add_field(name="Top Categories", value=cat_text or "None", inline=False)

        dom_text = "\n".join([f"• {dom}: {count}" for dom, count in top_domains])
        embed.add_field(name="Top Domains", value=dom_text or "None", inline=False)

        auth_text = "\n".join([f"• {auth}: {count}" for auth, count in top_authors])
        embed.add_field(name="Top Contributors", value=auth_text or "None", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name='recent', help='Show 5 most recent links')
    async def show_recent(self, ctx):
        links = load_links()
        if not links:
            await ctx.send("No links saved yet!")
            return

        recent_links = links[-5:]
        recent_links.reverse()

        response = "**🕒 Recently Saved:**\n\n"
        for i, link in enumerate(recent_links, 1):
            response += f"{i}. **[{link['category']}]** {link['url']}\n   *by {link['author']} at {link['timestamp']}*\n"

        await ctx.send(response)


# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Missing argument! Check `!help` for command syntax.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument type.")
    else:
        logger.error(f"Command error: {error}", exc_info=True)


async def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise ValueError("DISCORD_TOKEN not set!")
    logger.info(f"Starting bot. PID={os.getpid()}")
    async with bot:
        if bot.get_cog("LinkManager") is None:
            await bot.add_cog(LinkManager(bot))
            logger.info(f"LinkManager cog added")
        await bot.start(token)


if __name__ == "__main__":
    logger.info("🚀 Starting Labour Bot...")
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        logger.error("❌ DISCORD_TOKEN not set!")
        print("Create .env file with: DISCORD_TOKEN=your_token_here")
    else:
        asyncio.run(main())
