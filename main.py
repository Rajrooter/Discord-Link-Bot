import datetime
import json
import os
import re
from urllib.parse import urlparse
import asyncio
import aiohttp

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# NEW Google GenAI SDK (replaces google.generativeai)
from google import genai

# ============================================
# FIXED GOOGLE GEMINI CONFIGURATION - NEW SDK
# ============================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    # NEW: Initialize the client with API key
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    AI_ENABLED = True
    print("✅ Google Gemini AI enabled (gemini-2.0-flash-exp) - NEW SDK")
else:
    ai_client = None
    AI_ENABLED = False
    print("⚠️ AI disabled - Add GEMINI_API_KEY to enable")

async def get_ai_guidance(url: str) -> str:
    """Get AI guidance on whether a link is vital for study purposes."""
    
    if not AI_ENABLED or ai_client is None:
        return "📝 **Manual Review Needed** - AI analysis unavailable."
    
    try:
        prompt = f"""You are an educational assistant and security specialist.
Evaluate if this URL is vital for study purposes and if it's safe.

URL: {url}

Provide:
1. Verdict: Safe / Suspect / Unsafe
2. Brief reason (1-2 sentences)
3. Study Value: High / Medium / Low
4. Recommendation: Save or Skip

Keep response under 100 words."""

        # NEW SDK: Use generate_content with the new API
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model='gemini-2.0-flash-exp',
            contents=prompt
        )

        return response.text
    except Exception as e:
        print(f"AI Error: {e}")
        return "⚠️ AI analysis failed - please review manually."

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
                value="✅ **Google Gemini AI Enabled** - Free link analysis powered by Gemini 2.0",
                inline=False
            )
        else:
            embed.add_field(
                name="🤖 AI Status",
                value="⚠️ **AI Disabled** - Get free AI by adding GEMINI_API_KEY",
                inline=False
            )
            
        embed.set_footer(text="Digital Labour • Powered by Google Gemini (Free)")

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

# Load/Save functions
def load_links():
    try:
        with open(LINKS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_links(links):
    with open(LINKS_FILE, "w") as f:
        json.dump(links, f, indent=4)

def load_categories():
    try:
        with open(CATEGORIES_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_categories(categories):
    with open(CATEGORIES_FILE, "w") as f:
        json.dump(categories, f, indent=4)

def load_onboarding_data():
    try:
        with open(ONBOARDING_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_onboarding_data(data):
    with open(ONBOARDING_FILE, "w") as f:
        json.dump(data, f, indent=4)

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

class LinkManager(commands.Cog):
    """Handles link saving and management functionality"""

    def __init__(self, bot):
        self.bot = bot
        self.pending_links = {}
        self.links_to_categorize = {}
        self.pending_category_deletion = {}
        self.pending_clear_all = {}
        self.processed_messages = set()

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

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'✅ {self.bot.user} has connected to Discord!')
        print(f'🤖 Labour Bot is ready!')
        await self.ensure_roles_exist()

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
            non_media_links = [link for link in urls if not is_media_url(link)]

            for link in non_media_links:
                # Get AI guidance
                guidance = await get_ai_guidance(link)
                
                ask_msg = await message.channel.send(
                    f"🤖 **AI Analysis:**\n{guidance}\n\n"
                    f"📎 Save this link, {message.author.mention}?\n`{link}`\n"
                    f"React with ✅ to save or ❌ to ignore."
                )

                await ask_msg.add_reaction('✅')
                await ask_msg.add_reaction('❌')

                self.pending_links[ask_msg.id] = {
                    "link": link,
                    "author_id": message.author.id,
                    "original_message": message
                }

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user == self.bot.user:
            return

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

            elif str(reaction.emoji) == '❌':
                await reaction.message.channel.send(f"Link ignored, {user.mention}.")

            del self.pending_links[reaction.message.id]

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

            links = load_links()
            categories = load_categories()

            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            link_entry = {
                "url": link,
                "timestamp": timestamp,
                "author": str(message.author),
                "category": category_name
            }

            links.append(link_entry)
            save_links(links)

            if category_name not in categories:
                categories[category_name] = []
            categories[category_name].append(link)
            save_categories(categories)

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
        await ctx.send("Invalid argument type. Please provide a valid value.")
    else:
        print(f"Error: {error}")

async def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise ValueError("DISCORD_TOKEN not set!")
    async with bot:
        await bot.add_cog(LinkManager(bot))
        await bot.start(token)

if __name__ == "__main__":
    print("🚀 Starting Labour Bot...")
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN not set!")
        print("Create .env file with: DISCORD_TOKEN=your_token_here")
    else:
        import asyncio
        asyncio.run(main())
