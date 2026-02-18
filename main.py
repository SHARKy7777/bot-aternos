import discord
from discord.ext import commands, tasks
import asyncio
from dotenv import load_dotenv
import os
from mcstatus import JavaServer

load_dotenv()

BOT_TOKEN    = os.getenv("BOT_TOKEN")
OWNER_ID     = 715572086898294907
SERVER_ADDRESS = "lmanagil.aternos.me"
ANNOUNCEMENT_CHANNEL_ID = 0
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
tree = bot.tree

previous_status = None
mc_server = None

def check_server_status():
    global mc_server
    try:
        if mc_server is None:
            mc_server = JavaServer.lookup(SERVER_ADDRESS)
        status = mc_server.status()
        return {
            "online": True,
            "players": status.players.online,
            "max_players": status.players.max,
            "version": status.version.name,
            "latency": round(status.latency, 1)
        }
    except Exception:
        return {"online": False}

@bot.event
async def on_ready():
    print(f"[Bot] {bot.user} connecté")
    print(f"[Serveur] Surveillance de {SERVER_ADDRESS}")
    synced = await tree.sync()
    print(f"[Bot] {len(synced)} slash commandes sync")
    server_monitor.start()

@tasks.loop(minutes=3)
async def server_monitor():
    global previous_status
    status = check_server_status()
    current_online = status["online"]
    if current_online:
        activity = discord.Game(name=f"🟢 Serveur en ligne • {status['players']}/{status['max_players']} joueurs")
    else:
        activity = discord.Game(name="🔴 Serveur hors ligne")
    await bot.change_presence(activity=activity)
    if previous_status is not None and previous_status != current_online:
        if ANNOUNCEMENT_CHANNEL_ID != 0:
            channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
            if channel:
                if current_online:
                    embed = discord.Embed(title="🟢 Serveur Minecraft en ligne !", description=f"Le serveur **{SERVER_ADDRESS}** est maintenant accessible.", color=discord.Color.green())
                    embed.add_field(name="Joueurs", value=f"{status['players']}/{status['max_players']}", inline=True)
                    embed.add_field(name="Version", value=status['version'], inline=True)
                    embed.add_field(name="Latence", value=f"{status['latency']}ms", inline=True)
                else:
                    embed = discord.Embed(title="🔴 Serveur Minecraft hors ligne", description=f"Le serveur **{SERVER_ADDRESS}** s'est arrêté.", color=discord.Color.red())
                await channel.send(embed=embed)
    previous_status = current_online

async def owner_check(ctx_or_interaction) -> bool:
    if isinstance(ctx_or_interaction, discord.Interaction):
        uid = ctx_or_interaction.user.id
        async def deny():
            await ctx_or_interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    else:
        uid = ctx_or_interaction.author.id
        async def deny():
            await ctx_or_interaction.send("❌ Accès refusé.")
    if uid != OWNER_ID:
        await deny()
        return False
    return True

@tree.command(name="status", description="Statut actuel du serveur Minecraft")
async def slash_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    status = check_server_status()
    if status["online"]:
        embed = discord.Embed(title=f"🎮 Serveur — {SERVER_ADDRESS}", color=discord.Color.green())
        embed.add_field(name="Statut", value="🟢 En ligne", inline=True)
        embed.add_field(name="Joueurs", value=f"{status['players']}/{status['max_players']}", inline=True)
        embed.add_field(name="Version", value=status['version'], inline=True)
        embed.add_field(name="Latence", value=f"{status['latency']}ms", inline=True)
    else:
        embed = discord.Embed(title=f"🎮 Serveur — {SERVER_ADDRESS}", description="🔴 Le serveur est hors ligne", color=discord.Color.red())
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="setchannel", description="Définir le salon pour les annonces (propriétaire uniquement)")
async def slash_setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await owner_check(interaction):
        return
    global ANNOUNCEMENT_CHANNEL_ID
    ANNOUNCEMENT_CHANNEL_ID = channel.id
    embed = discord.Embed(title="✅ Salon configuré", description=f"Les annonces de statut seront envoyées dans {channel.mention}", color=discord.Color.green())
    await interaction.response.send_message(embed=embed, ephemeral=True)
    test_embed = discord.Embed(title="🔔 Annonces configurées", description="Ce salon recevra les notifications de statut du serveur Minecraft.", color=discord.Color.blurple())
    await channel.send(embed=test_embed)

@tree.command(name="forcecheck", description="Vérifier le statut immédiatement (propriétaire uniquement)")
async def slash_forcecheck(interaction: discord.Interaction):
    if not await owner_check(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    status = check_server_status()
    if status["online"]:
        await interaction.followup.send(f"✅ Serveur en ligne • {status['players']}/{status['max_players']} joueurs", ephemeral=True)
    else:
        await interaction.followup.send("❌ Serveur hors ligne", ephemeral=True)

@tree.command(name="help", description="Liste des commandes")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Commandes du bot", color=discord.Color.blurple())
    embed.add_field(name="/status", value="Affiche le statut actuel du serveur", inline=False)
    embed.add_field(name="/setchannel", value="Définir le salon pour les annonces (propriétaire)", inline=False)
    embed.add_field(name="/forcecheck", value="Forcer une vérification immédiate (propriétaire)", inline=False)
    embed.set_footer(text=f"Surveillance de {SERVER_ADDRESS}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command(name="status")
async def prefix_status(ctx):
    status = check_server_status()
    if status["online"]:
        await ctx.send(f"🟢 **{SERVER_ADDRESS}** est en ligne • {status['players']}/{status['max_players']} joueurs")
    else:
        await ctx.send(f"🔴 **{SERVER_ADDRESS}** est hors ligne")

@bot.command(name="help")
async def prefix_help(ctx):
    await ctx.send("Utilise `/help` pour voir les commandes disponibles.")

bot.run(BOT_TOKEN)
