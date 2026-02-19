import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
from mcstatus import JavaServer
from datetime import datetime, timedelta
import json
import re

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 715572086898294907
SERVER_ADDRESS = "lmanagil.aternos.me"
ANNOUNCEMENT_CHANNEL_ID = 0
LOGS_CHANNEL_ID = 0
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
clans = {}
clan_members = {}
missions = {}
achievements_data = {}
current_session_players = {}

DATA_FILE = "/tmp/server_data.json"

def load_data():
    global player_data, clans, clan_members, missions, achievements_data
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            player_data = data.get("players", {})
            clans = data.get("clans", {})
            clan_members = data.get("clan_members", {})
            missions = data.get("missions", {})
            achievements_data = data.get("achievements", {})
    except:
        player_data = {}
        clans = {}
        clan_members = {}
        missions = {}
        achievements_data = {}

def save_data():
    try:
        data = {
            "players": player_data,
            "clans": clans,
            "clan_members": clan_members,
            "missions": missions,
            "achievements": achievements_data
        }
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Erreur] Sauvegarde: {e}")

def init_player(player_name):
    if player_name not in player_data:
        player_data[player_name] = {
            "total_minutes": 0,
            "sessions": 0,
            "kills": 0,
            "deaths": 0,
            "zombie_kills": 0,
            "distance": 0,
            "last_seen": None,
            "first_seen": datetime.now().isoformat(),
            "achievements": []
        }

def parse_minecraft_logs(log_content):
    events = []
    
    # Patterns pour extraire les événements
    patterns = {
        "join": r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+joined the game",
        "leave": r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+left the game",
        "pvp_kill": r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+was (?:slain|killed) by (\w+)",
        "zombie_death": r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+was (?:slain|killed) by (?:Zombie|zombie)",
        "fall_death": r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+(?:fell|died)",
    }
    
    for line in log_content.split('\n'):
        # Connexions
        match = re.search(patterns["join"], line)
        if match:
            events.append({"type": "join", "time": match.group(1), "player": match.group(2)})
            continue
        
        # Déconnexions
        match = re.search(patterns["leave"], line)
        if match:
            events.append({"type": "leave", "time": match.group(1), "player": match.group(2)})
            continue
        
        # Kills PvP
        match = re.search(patterns["pvp_kill"], line)
        if match:
            events.append({
                "type": "pvp_kill",
                "time": match.group(1),
                "victim": match.group(2),
                "killer": match.group(3)
            })
            continue
        
        # Mort par zombie
        match = re.search(patterns["zombie_death"], line)
        if match:
            events.append({"type": "zombie_death", "time": match.group(1), "player": match.group(2)})
            continue
        
        # Mort par chute/autre
        match = re.search(patterns["fall_death"], line)
        if match:
            events.append({"type": "other_death", "time": match.group(1), "player": match.group(2)})
    
    return events

def process_events(events):
    summary = {
        "joins": [],
        "kills": [],
        "deaths": [],
        "zombie_deaths": []
    }
    
    for event in events:
        if event["type"] == "join":
            summary["joins"].append(event["player"])
        
        elif event["type"] == "pvp_kill":
            killer = event["killer"]
            victim = event["victim"]
            
            init_player(killer)
            init_player(victim)
            
            player_data[killer]["kills"] += 1
            player_data[victim]["deaths"] += 1
            
            summary["kills"].append(f"{killer} → {victim}")
            
            # Achievement: Premier sang
            if player_data[killer]["kills"] == 1:
                check_achievement(killer, "first_blood")
        
        elif event["type"] in ["zombie_death", "other_death"]:
            player = event["player"]
            init_player(player)
            player_data[player]["deaths"] += 1
            summary["deaths"].append(player)
    
    save_data()
    return summary

def check_achievement(player, achievement_id):
    achievements = {
        "first_blood": {"name": "🩸 Premier Sang", "desc": "Premier kill PvP", "points": 50},
        "survivor_10h": {"name": "🏆 Survivant", "desc": "10h de jeu", "points": 100},
        "zombie_hunter": {"name": "🧟 Chasseur de Zombies", "desc": "100 zombies tués", "points": 200},
        "pvp_master": {"name": "⚔️ Maître PvP", "desc": "50 kills PvP", "points": 300},
    }
    
    if achievement_id not in achievements:
        return False
    
    if player not in player_data:
        return False
    
    if achievement_id in player_data[player].get("achievements", []):
        return False
    
    # Vérifier conditions
    ach = achievements[achievement_id]
    earned = False
    
    if achievement_id == "first_blood" and player_data[player]["kills"] >= 1:
        earned = True
    elif achievement_id == "survivor_10h" and player_data[player]["total_minutes"] >= 600:
        earned = True
    elif achievement_id == "zombie_hunter" and player_data[player]["zombie_kills"] >= 100:
        earned = True
    elif achievement_id == "pvp_master" and player_data[player]["kills"] >= 50:
        earned = True
    
    if earned:
        if "achievements" not in player_data[player]:
            player_data[player]["achievements"] = []
        player_data[player]["achievements"].append(achievement_id)
        
        # Ajouter points au clan si le joueur en a un
        if player in clan_members:
            clan_name = clan_members[player]
            if clan_name in clans:
                clans[clan_name]["points"] += ach["points"]
        
        save_data()
        return ach
    
    return False

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
    init_player(player_name)
    player_data[player_name]["total_minutes"] += minutes
    player_data[player_name]["sessions"] += 1
    player_data[player_name]["last_seen"] = datetime.now().isoformat()
    
    # Check achievements
    if player_data[player_name]["total_minutes"] >= 600:
        check_achievement(player_name, "survivor_10h")
    
    save_data()

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
                    reason="Rôle automatique"
                )
            except:
                return
        
        for member in guild.members:
            if member.nick == player_name or member.name == player_name or member.display_name == player_name:
                if role not in member.roles:
                    try:
                        await member.add_roles(role)
                    except:
                        pass
                break

@bot.event
async def on_ready():
    print(f"[Bot] {bot.user} connecté")
    load_data()
    synced = await tree.sync()
    print(f"[Bot] {len(synced)} commandes sync")
    server_monitor.start()

@tasks.loop(minutes=3)
async def server_monitor():
    global previous_status, current_session_players
    
    status = check_server_status()
    current_online = status["online"]
    
    if current_online:
        activity = discord.Game(name=f"🟢 {status['players']}/{status['max_players']} joueurs")
        
        for player in status["player_list"]:
            if player not in current_session_players:
                current_session_players[player] = datetime.now()
                
                # Log connexion
                if LOGS_CHANNEL_ID != 0:
                    channel = bot.get_channel(LOGS_CHANNEL_ID)
                    if channel:
                        await channel.send(f"🟢 **{player}** s'est connecté")
        
        players_to_remove = []
        for player in current_session_players:
            if player not in status["player_list"]:
                session_duration = (datetime.now() - current_session_players[player]).total_seconds() / 60
                update_playtime(player, session_duration)
                players_to_remove.append(player)
                
                # Log déconnexion
                if LOGS_CHANNEL_ID != 0:
                    channel = bot.get_channel(LOGS_CHANNEL_ID)
                    if channel:
                        await channel.send(f"🔴 **{player}** s'est déconnecté")
                
                for guild in bot.guilds:
                    await check_and_give_role(guild, player)
        
        for player in players_to_remove:
            del current_session_players[player]
    else:
        activity = discord.Game(name="🔴 Hors ligne")
        
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
                        title="🟢 Serveur en ligne !",
                        description=f"@everyone **{SERVER_ADDRESS}** est accessible !",
                        color=discord.Color.green()
                    )
                    await channel.send("@everyone", embed=embed)
                else:
                    embed = discord.Embed(
                        title="🔴 Serveur hors ligne",
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

@tree.command(name="uploadlogs", description="Uploader les logs du serveur (proprio)")
async def slash_uploadlogs(interaction: discord.Interaction, fichier: discord.Attachment):
    if not await owner_check(interaction):
        return
    
    await interaction.response.defer()
    
    if not fichier.filename.endswith('.log') and not fichier.filename.endswith('.txt'):
        await interaction.followup.send("❌ Le fichier doit être un .log ou .txt")
        return
    
    try:
        log_content = await fichier.read()
        log_text = log_content.decode('utf-8', errors='ignore')
        
        events = parse_minecraft_logs(log_text)
        summary = process_events(events)
        
        embed = discord.Embed(title="📊 Logs analysés", color=discord.Color.blue())
        embed.add_field(name="Connexions", value=str(len(summary["joins"])), inline=True)
        embed.add_field(name="Kills PvP", value=str(len(summary["kills"])), inline=True)
        embed.add_field(name="Morts", value=str(len(summary["deaths"])), inline=True)
        
        if summary["kills"]:
            kills_text = "\n".join(summary["kills"][:10])
            embed.add_field(name="🔪 Kills récents", value=kills_text, inline=False)
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {e}")

@tree.command(name="pvpleaderboard", description="Classement PvP")
async def slash_pvpleaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    
    pvp_players = [(name, data) for name, data in player_data.items() if data.get("kills", 0) > 0]
    pvp_players.sort(key=lambda x: x[1]["kills"], reverse=True)
    
    if not pvp_players:
        await interaction.followup.send("❌ Aucune donnée PvP disponible")
        return
    
    embed = discord.Embed(title="⚔️ Classement PvP", color=discord.Color.red())
    
    for i, (player, data) in enumerate(pvp_players[:10]):
        kills = data.get("kills", 0)
        deaths = data.get("deaths", 0)
        ratio = kills / deaths if deaths > 0 else kills
        
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        embed.add_field(
            name=f"{medal} {player}",
            value=f"💀 {kills} kills • ☠️ {deaths} morts • 📊 Ratio: {ratio:.2f}",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@tree.command(name="stats", description="Voir les stats d'un joueur")
async def slash_stats(interaction: discord.Interaction, joueur: str):
    await interaction.response.defer()
    
    if joueur not in player_data:
        await interaction.followup.send(f"❌ Aucune donnée pour **{joueur}**")
        return
    
    data = player_data[joueur]
    hours = data["total_minutes"] / 60
    ratio = data["kills"] / data["deaths"] if data["deaths"] > 0 else data["kills"]
    
    embed = discord.Embed(title=f"📊 Statistiques de {joueur}", color=discord.Color.blue())
    embed.add_field(name="⏱️ Temps de jeu", value=f"{hours:.1f}h", inline=True)
    embed.add_field(name="🎮 Sessions", value=str(data["sessions"]), inline=True)
    embed.add_field(name="⚔️ Kills", value=str(data["kills"]), inline=True)
    embed.add_field(name="☠️ Morts", value=str(data["deaths"]), inline=True)
    embed.add_field(name="📊 Ratio K/D", value=f"{ratio:.2f}", inline=True)
    embed.add_field(name="🧟 Zombies tués", value=str(data.get("zombie_kills", 0)), inline=True)
    
    if data.get("achievements"):
        embed.add_field(name="🏆 Achievements", value=str(len(data["achievements"])), inline=True)
    
    await interaction.followup.send(embed=embed)

@tree.command(name="createclan", description="Créer un clan")
async def slash_createclan(interaction: discord.Interaction, nom: str):
    await interaction.response.defer()
    
    player_name = interaction.user.display_name
    
    if player_name in clan_members:
        await interaction.followup.send("❌ Tu es déjà dans un clan")
        return
    
    if nom in clans:
        await interaction.followup.send("❌ Ce nom de clan existe déjà")
        return
    
    clans[nom] = {
        "leader": player_name,
        "created": datetime.now().isoformat(),
        "points": 0
    }
    clan_members[player_name] = nom
    save_data()
    
    embed = discord.Embed(
        title=f"🛡️ Clan créé : {nom}",
        description=f"Chef: {player_name}",
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=embed)

@tree.command(name="joinclan", description="Rejoindre un clan")
async def slash_joinclan(interaction: discord.Interaction, nom: str):
    await interaction.response.defer()
    
    player_name = interaction.user.display_name
    
    if player_name in clan_members:
        await interaction.followup.send("❌ Tu es déjà dans un clan")
        return
    
    if nom not in clans:
        await interaction.followup.send("❌ Ce clan n'existe pas")
        return
    
    clan_members[player_name] = nom
    save_data()
    
    await interaction.followup.send(f"✅ Tu as rejoint le clan **{nom}** !")

@tree.command(name="clanleaderboard", description="Classement des clans")
async def slash_clanleaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not clans:
        await interaction.followup.send("❌ Aucun clan créé")
        return
    
    sorted_clans = sorted(clans.items(), key=lambda x: x[1]["points"], reverse=True)
    
    embed = discord.Embed(title="🛡️ Classement des Clans", color=discord.Color.gold())
    
    for i, (name, data) in enumerate(sorted_clans[:10]):
        members = [p for p, c in clan_members.items() if c == name]
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        embed.add_field(
            name=f"{medal} {name}",
            value=f"👑 Chef: {data['leader']} • 👥 {len(members)} membres • ⭐ {data['points']} points",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@tree.command(name="setlogschannel", description="Salon des logs (proprio)")
async def slash_setlogschannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await owner_check(interaction):
        return
    
    global LOGS_CHANNEL_ID
    LOGS_CHANNEL_ID = channel.id
    
    await interaction.response.send_message(f"✅ Logs envoyés dans {channel.mention}", ephemeral=True)
    await channel.send("📋 Ce salon recevra les logs du serveur.")

@tree.command(name="setchannel", description="Salon des annonces (proprio)")
async def slash_setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await owner_check(interaction):
        return
    
    global ANNOUNCEMENT_CHANNEL_ID
    ANNOUNCEMENT_CHANNEL_ID = channel.id
    
    await interaction.response.send_message(f"✅ Annonces dans {channel.mention}", ephemeral=True)
    await channel.send("🔔 Annonces configurées.")

@tree.command(name="status", description="Statut du serveur")
async def slash_status(interaction: discord.Interaction):
    await interaction.response.defer()
    status = check_server_status()
    
    if status["online"]:
        embed = discord.Embed(title=f"🎮 {SERVER_ADDRESS}", color=discord.Color.green())
        embed.add_field(name="Statut", value="🟢 En ligne", inline=True)
        embed.add_field(name="Joueurs", value=f"{status['players']}/{status['max_players']}", inline=True)
        
        if status["player_list"]:
            embed.add_field(name="En ligne", value=", ".join(status["player_list"]), inline=False)
    else:
        embed = discord.Embed(title=f"🎮 {SERVER_ADDRESS}", description="🔴 Hors ligne", color=discord.Color.red())
    
    await interaction.followup.send(embed=embed)

@tree.command(name="help", description="Liste des commandes")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Commandes", color=discord.Color.blurple())
    embed.add_field(name="/status", value="Statut du serveur", inline=False)
    embed.add_field(name="/stats <joueur>", value="Stats d'un joueur", inline=False)
    embed.add_field(name="/pvpleaderboard", value="Classement PvP", inline=False)
    embed.add_field(name="/createclan <nom>", value="Créer un clan", inline=False)
    embed.add_field(name="/joinclan <nom>", value="Rejoindre un clan", inline=False)
    embed.add_field(name="/clanleaderboard", value="Classement des clans", inline=False)
    embed.add_field(name="/uploadlogs", value="Analyser logs (proprio)", inline=False)
    await interaction.response.send_message(embed=embed)

bot.run(BOT_TOKEN)
