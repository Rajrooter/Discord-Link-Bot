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

# Groq AI Configuration (using direct HTTP calls instead of SDK)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

if GROQ_API_KEY:
    AI_ENABLED = True
    print("✅ Groq AI enabled (FREE) - Using direct API")
else:
    AI_ENABLED = False
    print("⚠️ AI disabled - Add GROQ_API_KEY to enable")

async def get_ai_guidance(url: str) -> str:
    """Get AI guidance on whether a link is vital for study purposes.
    
    Uses Groq's API directly via HTTP calls (avoiding SDK issues).
    """
    
    if not AI_ENABLED or not GROQ_API_KEY:
        return "📝 **Manual Review Needed** - AI analysis unavailable. Add GROQ_API_KEY to enable free AI analysis."
    
    try:
        system_prompt = (
            "You are an educational assistant and security specialist. "
            "Evaluate if a URL is vital for study purposes. Also check if the link looks like spam, phishing, or unsafe. "
            "Provide a short verdict (Safe / Suspect / Unsafe), a concise reason, and a suggestion whether to save the link for study."
        )
        user_prompt = f"Should I save this link for my studies? Is it safe? URL: {url}"

        # Direct HTTP call to Groq API
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                else:
                    error_text = await response.text()
                    print(f"Groq API Error: {response.status} - {error_text}")
                    return "⚠️ AI analysis temporarily unavailable - please review manually."
                    
    except asyncio.TimeoutError:
        print("AI timeout - request took too long")
        return "⚠️ AI analysis timed out - please review manually."
    except Exception as e:
        print(f"AI Error: {e}")
        return "⚠️ AI analysis failed - please review manually."
    
async def get_ai_guidance(url: str) -> str:
    """Get AI guidance on whether a link is vital for study purposes.
    
    Uses Groq's FREE API with Llama 3.3 70B model.
    """
    
    if not AI_ENABLED or ai_client is None:
        return "📝 **Manual Review Needed** - AI analysis unavailable. Add GROQ_API_KEY to enable free AI analysis."
    
    try:
        system_prompt = (
            "You are an educational assistant and security specialist. "
            "Evaluate if a URL is vital for study purposes. Also check if the link looks like spam, phishing, or unsafe. "
            "Provide a short verdict (Safe / Suspect / Unsafe), a concise reason, and a suggestion whether to save the link for study."
        )
        user_prompt = f"Should I save this link for my studies? Is it safe? URL: {url}"

        # Groq API call (FREE - 30 requests/min)
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model="llama-3.3-70b-versatile",  # Fast and intelligent
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=500,
            temperature=0.7
        )

        return response.choices[0].message.content
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
            description="Hello! I'm here to help you manage your links and guide you with command 💖.",
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
            value="Type `!help [command]` to see more details about a specific magic trick! ✨",
            inline=False
        )
        
        if AI_ENABLED:
            embed.add_field(
                name="🤖 AI Status",
                value="✅ **Groq AI Enabled** - Free link analysis powered by Llama 3.3",
                inline=False
            )
        else:
            embed.add_field(
                name="🤖 AI Status",
                value="⚠️ **AI Disabled** - Get free AI by adding GROQ_API_KEY (visit console.groq.com)",
                inline=False
            )
            
        embed.set_footer(text="Digital Labour • Powered by Groq AI (Free)")

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
    '.gif', '.png', '.jpg', '.jpeg', '.webp', '.bmp'
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

# Load data from files
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
            "📒server-rules➡ 1.Please read and acknowledge these rules to ensure our community remains a great place for everyone.\n"
            "2. Welcome to Labour To ensure our server remains a pro..."
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

        # Send welcome DM with onboarding instructions
        try:
            embed = discord.Embed(
                title="Welcome to the Labour!",
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

            # Send rules
            rules = load_rules()
            rules_embed = discord.Embed(
                title="Server Rules",
                description=rules,
                color=discord.Color.red()
            )
            await member.send(embed=rules_embed)

        except discord.Forbidden:
            # Can't send DM, notify in a designated channel
            for channel in member.guild.channels:
                if channel.name == "general" or channel.name == "welcome":
                    await channel.send(
                        f"{member.mention}, welcome! Please enable DMs to complete onboarding, "
                        f"or use `!startonboarding` in this channel."
                    )
                    break

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'{self.bot.user} has connected to Discord!')
        print(f'Labour is ready to rock {self.bot.user}!')
        # Ensure required roles exist
        await self.ensure_roles_exist()

    @commands.Cog.listener()
    async def on_message(self, message):
        # Then check for links and onboarding
        if message.author == self.bot.user or message.id in self.processed_messages:
            return

        # Mark this message as processed
        self.processed_messages.add(message.id)

        # Process commands AFTER ensuring it's not a bot message and hasn't been processed
        await self.bot.process_commands(message)

        # Clean up old processed messages
        if len(self.processed_messages) > 1000:
            self.processed_messages = set(list(self.processed_messages)[-1000:])

        # Check for onboarding text responses FIRST**
        onboarding_data = load_onboarding_data()
        user_id = str(message.author.id)

        if user_id in onboarding_data:
            user_data = onboarding_data[user_id]

            if user_data["state"] == "college":
                # Save college and ask for referral
                user_data["data"]["college"] = message.content
                user_data["state"] = "referral"

                embed = discord.Embed(
                    title="Onboarding - Referral",
                    description="Who referred you to this server? (Type a name or 'None' if no referral)",
                    color=discord.Color.green()
                )

                msg = await message.channel.send(embed=embed)
                user_data["message_id"] = msg.id
                onboarding_data[user_id] = user_data
                save_onboarding_data(onboarding_data)

                # Delete the user's message and our previous message
                try:
                    await message.delete()
                    old_msg = await message.channel.fetch_message(user_data["message_id"])
                    await old_msg.delete()
                except:
                    pass
                return  # **IMPORTANT: Return after handling onboarding**

            elif user_data["state"] == "referral":
                # Save referral and confirm
                user_data["data"]["referral"] = message.content
                user_data["state"] = "confirm"

                # Create summary embed
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

                # Delete the user's message
                try:
                    await message.delete()
                except:
                    pass
                return  # **IMPORTANT: Return after handling onboarding**

        # Now check for links (only if not in onboarding)
        try:
            urls = [m.group(0) for m in re.finditer(URL_REGEX, message.content)]
        except re.error as e:
            print(f"Regex error while finding URLs: {e}")
            urls = []

        print(f"DEBUG: Found URLs: {urls}")  # Debug

        if urls:
            # Filter out media URLs to reduce noise
            non_media_links = [link for link in urls if not is_media_url(link)]

            print(f"DEBUG: Non-media links: {non_media_links}")  # Debug

            # Ask before saving non-media links
            for link in non_media_links:
                # Get AI guidance (await the async function)
                guidance = await get_ai_guidance(link)
                
                # Send a message asking if the user wants to save the link with AI advice
                ask_msg = await message.channel.send(
                    f"**AI Guidance:** {guidance}\n\n"
                    f"Save this link, {message.author.mention}?\n{link}\n"
                    f"React with ✅ to save or ❌ to ignore."
                )

                # Add reactions for user to choose
                await ask_msg.add_reaction('✅')
                await ask_msg.add_reaction('❌')

                # Store message info for later reference
                self.pending_links[ask_msg.id] = {
                    "link": link,
                    "author_id": message.author.id,
                    "original_message": message
                }

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        # Ignore reactions from the bot itself
        if user == self.bot.user:
            return

        # Check if this is a reaction to one of our "ask to save" messages
        if reaction.message.id in self.pending_links:
            link_data = self.pending_links[reaction.message.id]

            # Only the original author can decide to save the link
            if user.id != link_data["author_id"]:
                return

            # Check which reaction was added
            if str(reaction.emoji) == '✅':
                # User wants to save the link
                await reaction.message.channel.send(
                    f"{user.mention}, what category would you like to assign to this link?\n"
                    f"Type `!category [category_name]` to assign a category, or `!cancel` to cancel."
                )

                # Store the link for category assignment
                self.links_to_categorize[user.id] = {
                    "link": link_data["link"],
                    "message": link_data["original_message"]
                }

            elif str(reaction.emoji) == '❌':
                # User doesn't want to save the link
                await reaction.message.channel.send(f"Nahi save hai, {user.mention}.")

            # Remove the pending link
            del self.pending_links[reaction.message.id]

        # Check if this is a reaction to a category deletion confirmation
        elif reaction.message.id in self.pending_category_deletion:
            deletion_data = self.pending_category_deletion[reaction.message.id]

            # Only the original author can confirm
            if user.id != deletion_data["author_id"]:
                return

            if str(reaction.emoji) == '✅':
                # User confirmed deletion
                category_name = deletion_data["category"]
                categories = load_categories()
                links = load_links()

                # Remove all links in this category
                links = [link for link in links if link["category"] != category_name]
                save_links(links)

                # Remove the category
                if category_name in categories:
                    del categories[category_name]
                    save_categories(categories)

                await reaction.message.channel.send(f"Category '{category_name}' and all its links have been deleted.")

            elif str(reaction.emoji) == '❌':
                # User cancelled deletion
                await reaction.message.channel.send("Category deletion cancelled.")

            # Remove the pending deletion
            del self.pending_category_deletion[reaction.message.id]

        # Check if this is a reaction to a clear all confirmation
        elif reaction.message.id in self.pending_clear_all:
            clear_data = self.pending_clear_all[reaction.message.id]

            # Only the original author can confirm
            if user.id != clear_data["author_id"]:
                return

            if str(reaction.emoji) == '✅':
                # User confirmed clearing all links
                links_count = len(load_links())
                categories_count = len(load_categories())
                save_links([])
                save_categories({})
                await reaction.message.channel.send(
                    f"Sare kaand mita diye gaye hai {user.mention}. "
                    f"Deleted {links_count} links and {categories_count} categories."
                )

            elif str(reaction.emoji) == '❌':
                # User cancelled clearing
                await reaction.message.channel.send("Clear operation cancelled.")

            # Remove the pending clear
            del self.pending_clear_all[reaction.message.id]

    @commands.command(name='category', help=':- Assign a category to a ✅  link')
    async def assign_category(self, ctx, *, category_name):
        # Check if the user has a link waiting for categorization
        if ctx.author.id in self.links_to_categorize:
            link_data = self.links_to_categorize[ctx.author.id]
            link = link_data["link"]
            message = link_data["message"]

            # Load existing links and categories
            links = load_links()
            categories = load_categories()

            # Create the link entry
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            link_entry = {
                "url": link,
                "timestamp": timestamp,
                "author": str(message.author),
                "category": category_name
            }

            # Add to links list
            links.append(link_entry)
            save_links(links)

            # Update categories
            if category_name not in categories:
                categories[category_name] = []
            categories[category_name].append(link)
            save_categories(categories)

            # Send confirmation
            await ctx.send(f"Lo hogaya ji 🫦 '{category_name}', {ctx.author.mention}!")

            # Remove from pending categorization
            del self.links_to_categorize[ctx.author.id]
        else:
            await ctx.send(f"Ji koi link baki nahi hai save ko liye, {ctx.author.mention}")

    @commands.command(name='cancel', help=':- Cancel saving a ❌  pending link')
    async def cancel_save(self, ctx):
        if ctx.author.id in self.links_to_categorize:
            del self.links_to_categorize[ctx.author.id]
            await ctx.send(f"Jaa cancel ho gaya, {ctx.author.mention}, ab toh link gaya")
        else:
            await ctx.send(f"Ji category assign sahi karo, {ctx.author.mention}.")

    @commands.command(name='getlinks', help=':- Retrieve all saved links or filter by category')
    async def get_links(self, ctx, category=None):
        links = load_links()

        if not links:
            await ctx.send("Hat bullakar 😑")
            return

        # Filter by category if specified
        if category:
            filtered_links = [link for link in links if link["category"].lower() == category.lower()]
            if not filtered_links:
                await ctx.send(f"Kuch nahi mila iss name ka  '{category}'!")
                return
            links = filtered_links
            title = f"Sare links '{category}':"
        else:
            title = "All saved links:"

        # Format the response
        response = f"**{title}**\n\n"
        for i, link in enumerate(links, 1):
            response += f"{i}. **{link['category']}** - {link['url']} (by {link['author']}, {link['timestamp']})\n"

            # Split if response is too long
            if len(response) > 1500:
                await ctx.send(response)
                response = ""

        if response:
            await ctx.send(response)

    @commands.command(name='categories', help=':- List all categories')
    async def list_categories(self, ctx):
        categories = load_categories()

        if not categories:
            await ctx.send("Aise koi gallery nahi bani hai")
            return

        response = "**Categories:**\n"
        for category, links in categories.items():
            response += f"- {category} ({len(links)} links)\n"

        await ctx.send(response)

    @commands.command(name='deletelink', help=':- Delete a link by its number (use @getlinks to see numbers)')
    async def delete_link(self, ctx, link_number: int):
        links = load_links()

        if not links:
            await ctx.send("Koi link save nahi hai ji 🤣")
            return

        if link_number < 1 or link_number > len(links):
            await ctx.send(f"Invalid link number! Please use a number between 1 and {len(links)}.")
            return

        # Get the link to delete
        link_to_delete = links[link_number - 1]

        # Remove from links list
        del links[link_number - 1]
        save_links(links)

        # Remove from categories
        categories = load_categories()
        if link_to_delete["category"] in categories:
            if link_to_delete["url"] in categories[link_to_delete["category"]]:
                categories[link_to_delete["category"]].remove(link_to_delete["url"])
                # Remove category if empty
                if not categories[link_to_delete["category"]]:
                    del categories[link_to_delete["category"]]
            save_categories(categories)

        await ctx.send(f"Link {link_number} mit gaya {ctx.author.mention} ji")

    @commands.command(name='deletecategory', help=':- Delete a category and all its links')
    async def delete_category(self, ctx, *, category_name):
        categories = load_categories()
        links = load_links()

        if category_name not in categories:
            await ctx.send(f"Category '{category_name}' doesn't exist!")
            return

        # Confirm deletion
        confirm_msg = await ctx.send(
            f"Are you sure you want to delete category '{category_name}' and all its {len(categories[category_name])} links?\n"
            f"React with ✅ to confirm or ❌ to cancel."
        )
        await confirm_msg.add_reaction('✅')
        await confirm_msg.add_reaction('❌')

        # Store category for confirmation
        self.pending_category_deletion[confirm_msg.id] = {
            "category": category_name,
            "author_id": ctx.author.id
        }

    @commands.command(name='clearlinks', help=':- Clear all saved links and categories (Creators only)')
    @commands.has_permissions(administrator=True)
    async def clear_links(self, ctx):
        # Confirm deletion
        confirm_msg = await ctx.send(
            "Are you sure you want to delete ALL links and categories? This action cannot be undone.\n"
            "React with ✅ to confirm or ❌ to cancel."
        )
        await confirm_msg.add_reaction('✅')
        await confirm_msg.add_reaction('❌')

        # Store confirmation info
        self.pending_clear_all[confirm_msg.id] = {
            "author_id": ctx.author.id
        }

    @commands.command(name='searchlinks', help=':- Search for links containing specific text')
    async def search_links(self, ctx, *, search_term):
        links = load_links()

        results = [link for link in links if search_term.lower() in link["url"].lower() or 
                   search_term.lower() in link["category"].lower()]

        if not results:
            await ctx.send(f"Aap bare bullakar ho ji 🤣 '{search_term}'")
            return

        response = f"**Search results for '{search_term}':**\n\n"
        for i, link in enumerate(results, 1):
            response += f"{i}. **{link['category']}** - {link['url']} (by {link['author']}, {link['timestamp']})\n"

            if len(response) > 1500:
                await ctx.send(response)
                response = ""

        if response:
            await ctx.send(response)


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        # Handle onboarding reactions properly
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        onboarding_data = load_onboarding_data()
        user_id = str(payload.user_id)

        if user_id not in onboarding_data:
            return

        user_data = onboarding_data[user_id]

        # Check if this is a reaction to our onboarding message
        if payload.message_id != user_data["message_id"]:
            return

        # Get the channel and message
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        # Remove the user's reaction so they can choose again if needed
        try:
            await message.remove_reaction(payload.emoji, member)
        except:
            pass

    @commands.command(name='analyze', help=':- Get AI guidance on a specific link')
    async def analyze_link(self, ctx, url):
        async with ctx.typing():
            guidance = await get_ai_guidance(url)
            embed = discord.Embed(
                title="AI Study Guidance",
                description=guidance,
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Analyzed URL: {url}")
            await ctx.send(embed=embed)

    @commands.command(name='stats', help=':- Show link statistics and analytics')
    async def show_stats(self, ctx):
        links = load_links()
        if not links:
            await ctx.send("Koi data nahi hai statistics dikhane ke liye! 📉")
            return

        total_links = len(links)
        categories = {}
        domains = {}
        authors = {}

        for link in links:
            # Category stats
            cat = link.get("category", "Uncategorized")
            categories[cat] = categories.get(cat, 0) + 1
            
            # Domain stats
            try:
                domain = urlparse(link["url"]).netloc.lower()
                if domain.startswith('www.'):
                    domain = domain[4:]
                domains[domain] = domains.get(domain, 0) + 1
            except:
                pass
                
            # Author stats
            author = link.get("author", "Unknown")
            authors[author] = authors.get(author, 0) + 1

        # Sort stats
        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
        top_domains = sorted(domains.items(), key=lambda x: x[1], reverse=True)[:5]
        top_authors = sorted(authors.items(), key=lambda x: x[1], reverse=True)[:5]

        embed = discord.Embed(
            title="📊 Link Management Statistics",
            description=f"Total links saved: **{total_links}**",
            color=discord.Color.gold()
        )

        cat_text = "\n".join([f"• {cat}: {count}" for cat, count in top_categories])
        embed.add_field(name="Top Categories", value=cat_text or "None", inline=False)

        dom_text = "\n".join([f"• {dom}: {count}" for dom, count in top_domains])
        embed.add_field(name="Top Domains", value=dom_text or "None", inline=False)

        auth_text = "\n".join([f"• {auth}: {count}" for auth, count in top_authors])
        embed.add_field(name="Top Contributors", value=auth_text or "None", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name='recent', help=':- Show 5 most recently saved links')
    async def show_recent(self, ctx):
        links = load_links()
        if not links:
            await ctx.send("Abhi tak koi link save nahi hua hai! 🕒")
            return

        recent_links = links[-5:]
        recent_links.reverse()

        response = "**🕒 Recently Saved Links:**\n\n"
        for i, link in enumerate(recent_links, 1):
            response += f"{i}. **[{link['category']}]** {link['url']}\n   *by {link['author']} at {link['timestamp']}*\n"

        await ctx.send(response)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Bhai sahi command daal. Please check the command syntax from !help or @BotName help")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument type. Please provide a valid number for the link.")
    else:
        print(f"Error: {error}")

async def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable not set!")
    async with bot:
        await bot.add_cog(LinkManager(bot))
        await bot.start(token)

if __name__ == "__main__":
    print("Starting bot ✅")
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set!")
        print("Please create a .env file with your token: DISCORD_TOKEN=your_token_here")
    else:
        import asyncio
        asyncio.run(main())
