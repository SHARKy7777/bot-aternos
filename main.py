import discord
from discord.ext import commands, tasks
from discord import app_commands
from python_aternos import Client
from dotenv import load_dotenv
import os

load_dotenv()

# ============================================================
BOT_TOKEN    = os.getenv("BOT_TOKEN")
OWNER_ID     = 123456789012345678  # ← Remplace par ton vrai ID
ATERNOS_USER = os.getenv("ATERNOS_USER")
ATERNOS_PASS = os.getenv("ATERNOS_PASS")
SERVER_NAME  = "lmanagil"
PREFIX       = "!"
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
tree = bot.tree
aternos_server = None

def connect_aternos():
    global aternos_server
    try:
        client = Client.from_credentials(ATERNOS_USER, ATERNOS_PASS)
        servers = client.list_servers()
        for srv in servers:
            if SERVER_NAME.lower() in srv.address.lower():
                aternos_server = srv
                return True
        if servers:
            aternos_server = servers[0]
            return True
        return False
    except Exception as e:
        print(f"[Aternos] Erreur : {e}")
        return False

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

def get_status_embed():
    if aternos_server is None:
        return discord.Embed(title="⚠️ Non connecté", description="Vérifie ta config.", color=discord.Color.orange())
    try:
        aternos_server.fetch()
        status  = aternos_server.status
        address = aternos_server.address
        players = aternos_server.players_list or []
        max_p   = aternos_server.players_max
        colors  = {"online": discord.Color.green(), "offline": discord.Color.red(),
                   "starting": discord.Color.yellow(), "stopping": discord.Color.orange()}
        emojis  = {"online":"🟢","offline":"🔴","starting":"🟡","stopping":"🟠","loading":"🔵"}
        embed   = discord.Embed(title=f"🎮 Serveur — {SERVER_NAME}", color=colors.get(status, discord.Color.greyple()))
        embed.add_field(name="Statut",  value=f"{emojis.get(status,'⚪')} {status.capitalize()}", inline=True)
        embed.add_field(name="Adresse", value=f"`{address}`", inline=True)
        embed.add_field(name=f"Joueurs ({len(players)}/{max_p})", value=", ".join(players) if players else "Aucun", inline=False)
        embed.set_footer(text="Aternos Bot • Accès privé")
        return embed
    except Exception as e:
        return discord.Embed(title="❌ Erreur", description=str(e), color=discord.Color.red())

@bot.event
async def on_ready():
    print(f"[Bot] {bot.user} connecté")
    ok = connect_aternos()
    print(f"[Aternos] {'OK: ' + aternos_server.address if ok else 'ERREUR'}")
    synced = await tree.sync()
    print(f"[Bot] {len(synced)} slash commandes sync")
    status_loop.start()

@tasks.loop(minutes=2)
async def status_loop():
    if not aternos_server: return
    try:
        aternos_server.fetch()
        s = aternos_server.status
        e = {"online":"🟢","offline":"🔴","starting":"🟡"}.get(s,"⚪")
        await bot.change_presence(activity=discord.Game(name=f"{e} {s.capitalize()}"))
    except: pass

@tree.command(name="start", description="Démarre le serveur")
async def slash_start(interaction: discord.Interaction):
    if not await owner_check(interaction): return
    await interaction.response.defer(ephemeral=True)
    try:
        aternos_server.start()
        await interaction.followup.send(embed=discord.Embed(title="🚀 Démarrage en cours...", description="Attends 2-3 min.", color=discord.Color.yellow()), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`", ephemeral=True)

@tree.command(name="stop", description="Arrête le serveur")
async def slash_stop(interaction: discord.Interaction):
    if not await owner_check(interaction): return
    await interaction.response.defer(ephemeral=True)
    try:
        aternos_server.stop()
        await interaction.followup.send(embed=discord.Embed(title="🛑 Arrêt en cours...", description="1-2 min.", color=discord.Color.orange()), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`", ephemeral=True)

@tree.command(name="restart", description="Redémarre le serveur")
async def slash_restart(interaction: discord.Interaction):
    if not await owner_check(interaction): return
    await interaction.response.defer(ephemeral=True)
    try:
        aternos_server.restart()
        await interaction.followup.send(embed=discord.Embed(title="🔄 Redémarrage...", description="2-3 min.", color=discord.Color.blurple()), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`", ephemeral=True)

@tree.command(name="status", description="Statut du serveur")
async def slash_status(interaction: discord.Interaction):
    if not await owner_check(interaction): return
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=get_status_embed(), ephemeral=True)

@tree.command(name="players", description="Joueurs connectés")
async def slash_players(interaction: discord.Interaction):
    if not await owner_check(interaction): return
    await interaction.response.defer(ephemeral=True)
    try:
        aternos_server.fetch()
        p = aternos_server.players_list or []
        desc = "\n".join(f"• `{x}`" for x in p) if p else "Aucun joueur."
        await interaction.followup.send(embed=discord.Embed(title=f"👥 Joueurs ({len(p)}/{aternos_server.players_max})", description=desc, color=discord.Color.blue()), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`", ephemeral=True)

@tree.command(name="help", description="Liste des commandes")
async def slash_help(interaction: discord.Interaction):
    if not await owner_check(interaction): return
    embed = discord.Embed(title="📖 Commandes", color=discord.Color.dark_gold())
    for n, d in [("start","Démarre"),("stop","Arrête"),("restart","Redémarre"),("status","Statut"),("players","Joueurs"),("help","Aide")]:
        embed.add_field(name=f"`!{n}` / `/{n}`", value=d, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command(name="start")
async def p_start(ctx):
    if not await owner_check(ctx): return
    try:
        aternos_server.start()
        await ctx.send(embed=discord.Embed(title="🚀 Démarrage...", description="2-3 min.", color=discord.Color.yellow()))
    except Exception as e: await ctx.send(f"❌ `{e}`")

@bot.command(name="stop")
async def p_stop(ctx):
    if not await owner_check(ctx): return
    try:
        aternos_server.stop()
        await ctx.send(embed=discord.Embed(title="🛑 Arrêt...", description="1-2 min.", color=discord.Color.orange()))
    except Exception as e: await ctx.send(f"❌ `{e}`")

@bot.command(name="restart")
async def p_restart(ctx):
    if not await owner_check(ctx): return
    try:
        aternos_server.restart()
        await ctx.send(embed=discord.Embed(title="🔄 Redémarrage...", description="2-3 min.", color=discord.Color.blurple()))
    except Exception as e: await ctx.send(f"❌ `{e}`")

@bot.command(name="status")
async def p_status(ctx):
    if not await owner_check(ctx): return
    await ctx.send(embed=get_status_embed())

@bot.command(name="players")
async def p_players(ctx):
    if not await owner_check(ctx): return
    try:
        aternos_server.fetch()
        p = aternos_server.players_list or []
        desc = "\n".join(f"• `{x}`" for x in p) if p else "Aucun joueur."
        await ctx.send(embed=discord.Embed(title=f"👥 Joueurs ({len(p)}/{aternos_server.players_max})", description=desc, color=discord.Color.blue()))
    except Exception as e: await ctx.send(f"❌ `{e}`")

@bot.command(name="help")
async def p_help(ctx):
    if not await owner_check(ctx): return
    embed = discord.Embed(title="📖 Commandes", color=discord.Color.dark_gold())
    for n, d in [("start","Démarre"),("stop","Arrête"),("restart","Redémarre"),("status","Statut"),("players","Joueurs"),("help","Aide")]:
        embed.add_field(name=f"`!{n}` / `/{n}`", value=d, inline=False)
    await ctx.send(embed=embed)

bot.run(BOT_TOKEN)
```

---

### Étape 3 — Vérifie que ton repo GitHub contient exactement ces fichiers
```
ton-repo/
├── bot.py              ✅
├── requirements.txt    ✅
└── .gitignore          ✅
```

Et ton `requirements.txt` doit contenir :
```
discord.py==2.3.2
python-aternos==2.1.0
python-dotenv==1.0.0
