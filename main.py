import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
from mcstatus import JavaServer
from datetime import datetime, timedelta
import json

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 715572086898294907
SERVER_ADDRESS = "lmanagil.aternos.me"
ANNOUNCEMENT_CHANNEL_ID = 0
ACTIVE_ROLE_NAME = "Joueur Actif"
HOURS_FOR_ACTIVE_ROLE = 10
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
tree = bot.tree

previous_status = None
mc_server = None
player_data = {}
current_session_players = {}

DATA_FILE = "/tmp/player_data.json"

def load_player_data():
    global player_data
    try:
        with open(DATA_FILE, 'r') as f:
            player_data = json.load(f)
    except:
        player_data = {}

def save_player_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(player_data, f, indent=2)
    except Exception as e:
        print(f"[Erreur] Sauvegarde données: {e}")

def check_server_status():
    global mc_server
    try:
        if mc_server is None:
            mc_server = JavaServer.lookup(SERVER_ADDRESS)
        status = mc_server.status()
        query = mc_server.query()
        return {
            "online": True,
            "players": status.players.online,
            "max_players": status.players.max,
            "version": status.version.name,
            "latency": round(status.latency, 1),
            "player_list": query.players.names if query.players.names else []
        }
    except Exception:
        return {"online": False, "player_list": []}

def update_playtime(player_name, minutes):
    if player_name not in player_data:
        player_data[player_name] = {
            "total_minutes": 0,
            "sessions": 0,
            "last_seen": None,
            "first_seen": datetime.now().isoformat()
        }
    player_data[player_name]["total_minutes"] += minutes
    player_data[player_name]["sessions"] += 1
    player_data[player_name]["last_seen"] = datetime.now().isoformat()
    save_player_data()

async def check_and_give_role(guild, player_name):
    if player_name not in player_data:
        return
    
    total_hours = player_data[player_name]["total_minutes"] / 60
    
    if total_hours >= HOURS_FOR_ACTIVE_ROLE:
        role = discord.utils.get(guild.roles, name=ACTIVE_ROLE_NAME)
        
        if not role:
            try:
                role = await guild.create_role(
                    name=ACTIVE_ROLE_NAME,
                    color=discord.Color.gold(),
                    reason="Rôle automatique pour joueurs actifs"
                )
                print(f"[Rôle] Créé: {ACTIVE_ROLE_NAME}")
            except:
                return
        
        for member in guild.members:
            if member.nick == player_name or member.name == player_name or member.display_name == player_name:
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Atteint {HOURS_FOR_ACTIVE_ROLE}h de jeu")
                        print(f"[Rôle] Attribué à {member.name}")
                    except:
                        pass
                break

@bot.event
async def on_ready():
    print(f"[Bot] {bot.user} connecté")
    print(f"[Serveur] Surveillance de {SERVER_ADDRESS}")
    load_player_data()
    synced = await tree.sync()
    print(f"[Bot] {len(synced)} slash commandes sync")
    server_monitor.start()

@tasks.loop(minutes=3)
async def server_monitor():
    global previous_status, current_session_players
    
    status = check_server_status()
    current_online = status["online"]
    
    if current_online:
        activity = discord.Game(name=f"🟢 En ligne • {status['players']}/{status['max_players']} joueurs")
        
        for player in status["player_list"]:
            if player not in current_session_players:
                current_session_players[player] = datetime.now()
        
        players_to_remove = []
        for player in current_session_players:
            if player not in status["player_list"]:
                session_duration = (datetime.now() - current_session_players[player]).total_seconds() / 60
                update_playtime(player, session_duration)
                players_to_remove.append(player)
                
                for guild in bot.guilds:
                    await check_and_give_role(guild, player)
        
        for player in players_to_remove:
            del current_session_players[player]
    else:
        activity = discord.Game(name="🔴 Serveur hors ligne")
        
        for player, join_time in current_session_players.items():
            session_duration = (datetime.now() - join_time).total_seconds() / 60
            update_playtime(player, session_duration)
        current_session_players.clear()
    
    await bot.change_presence(activity=activity)
    
    if previous_status is not None and previous_status != current_online:
        if ANNOUNCEMENT_CHANNEL_ID != 0:
            channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
            if channel:
                if current_online:
                    embed = discord.Embed(
                        title="🟢 Serveur Minecraft en ligne !",
                        description=f"@everyone Le serveur **{SERVER_ADDRESS}** est maintenant accessible !",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Joueurs", value=f"{status['players']}/{status['max_players']}", inline=True)
                    embed.add_field(name="Version", value=status['version'], inline=True)
                    embed.add_field(name="Latence", value=f"{status['latency']}ms", inline=True)
                    await channel.send("@everyone", embed=embed)
                else:
                    embed = discord.Embed(
                        title="🔴 Serveur Minecraft hors ligne",
                        description=f"Le serveur **{SERVER_ADDRESS}** s'est arrêté.",
                        color=discord.Color.red()
                    )
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
    await interaction.response.defer()
    status = check_server_status()
    
    if status["online"]:
        embed = discord.Embed(title=f"🎮 Serveur — {SERVER_ADDRESS}", color=discord.Color.green())
        embed.add_field(name="Statut", value="🟢 En ligne", inline=True)
        embed.add_field(name="Joueurs", value=f"{status['players']}/{status['max_players']}", inline=True)
        embed.add_field(name="Version", value=status['version'], inline=True)
        embed.add_field(name="Latence", value=f"{status['latency']}ms", inline=True)
        
        if status["player_list"]:
            players_str = ", ".join(status["player_list"])
            embed.add_field(name="En ligne maintenant", value=players_str, inline=False)
    else:
        embed = discord.Embed(title=f"🎮 Serveur — {SERVER_ADDRESS}", description="🔴 Le serveur est hors ligne", color=discord.Color.red())
    
    await interaction.followup.send(embed=embed)

@tree.command(name="playtime", description="Voir le temps de jeu d'un joueur")
async def slash_playtime(interaction: discord.Interaction, joueur: str):
    await interaction.response.defer()
    
    if joueur not in player_data:
        await interaction.followup.send(f"❌ Aucune donnée pour le joueur **{joueur}**")
        return
    
    data = player_data[joueur]
    total_hours = data["total_minutes"] / 60
    
    embed = discord.Embed(title=f"📊 Statistiques de {joueur}", color=discord.Color.blue())
    embed.add_field(name="⏱️ Temps de jeu total", value=f"{total_hours:.1f} heures", inline=True)
    embed.add_field(name="🎮 Sessions", value=str(data["sessions"]), inline=True)
    
    if data["last_seen"]:
        last_seen = datetime.fromisoformat(data["last_seen"])
        embed.add_field(name="👀 Dernière connexion", value=last_seen.strftime("%d/%m/%Y %H:%M"), inline=False)
    
    await interaction.followup.send(embed=embed)

@tree.command(name="leaderboard", description="Classement des joueurs les plus actifs")
async def slash_leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not player_data:
        await interaction.followup.send("❌ Aucune donnée disponible")
        return
    
    sorted_players = sorted(player_data.items(), key=lambda x: x[1]["total_minutes"], reverse=True)[:10]
    
    embed = discord.Embed(title="🏆 Top 10 Joueurs les Plus Actifs", color=discord.Color.gold())
    
    medals = ["🥇", "🥈", "🥉"]
    for i, (player, data) in enumerate(sorted_players):
        medal = medals[i] if i < 3 else f"{i+1}."
        hours = data["total_minutes"] / 60
        embed.add_field(
            name=f"{medal} {player}",
            value=f"⏱️ {hours:.1f}h • 🎮 {data['sessions']} sessions",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@tree.command(name="setchannel", description="Définir le salon pour les annonces")
async def slash_setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await owner_check(interaction):
        return
    
    global ANNOUNCEMENT_CHANNEL_ID
    ANNOUNCEMENT_CHANNEL_ID = channel.id
    
    embed = discord.Embed(title="✅ Salon configuré", description=f"Les annonces seront envoyées dans {channel.mention}", color=discord.Color.green())
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    test_embed = discord.Embed(title="🔔 Annonces configurées", description="Ce salon recevra les notifications du serveur.", color=discord.Color.blurple())
    await channel.send(test_embed)

@tree.command(name="forcecheck", description="Vérifier le statut immédiatement")
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
    embed.add_field(name="/status", value="Statut actuel du serveur", inline=False)
    embed.add_field(name="/playtime <joueur>", value="Temps de jeu d'un joueur", inline=False)
    embed.add_field(name="/leaderboard", value="Top 10 des joueurs actifs", inline=False)
    embed.add_field(name="/setchannel", value="Configurer le salon d'annonces (proprio)", inline=False)
    embed.add_field(name="/forcecheck", value="Vérification immédiate (proprio)", inline=False)
    embed.set_footer(text=f"Surveillance de {SERVER_ADDRESS} • Rôle actif après {HOURS_FOR_ACTIVE_ROLE}h")
    await interaction.response.send_message(embed=embed)

bot.run(BOT_TOKEN)
