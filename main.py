import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
from mcstatus import JavaServer
from datetime import datetime
import json
import re

load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN")
OWNER_ID   = 715572086898294907
SERVER_ADDRESS = "lmanagil.aternos.me"
SERVER_DISPLAY_NAME = "Serveur Minecraft"  # ← Nom affiché dans /status

# ══════════════════════════════════════════════
#  CONFIG (modifiable avec /setconfig)
# ══════════════════════════════════════════════
CONFIG = {
    "ANNOUNCEMENT_CHANNEL_ID": 0,
    "LOGS_CHANNEL_ID":         0,
    "ACTIVE_ROLE_NAME":        "Joueur Actif",
    "HOURS_FOR_ACTIVE_ROLE":   10,
    "POINTS_INTERCLAN_KILL":   10,
    "POINTS_INTERCLAN_DEATH":  5,
    "POINTS_PER_HOUR":         1,
    "MAX_CLAN_NAME_LENGTH":    20,
    "MAX_BOUNTY_POINTS":       1000,
}

DATA_DIR  = "./data"
DATA_FILE = "./data/server_data.json"
os.makedirs(DATA_DIR, exist_ok=True)

PREFIX = "!"
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot  = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
tree = bot.tree

previous_status      = None
mc_server            = None
player_data          = {}
clans                = {}
clan_members         = {}
missions             = {}
achievements_data    = {}
current_session_players = {}

# ══════════════════════════════════════════════
#  SYSTÈME DE BOUNTY (PRIMES)
# ══════════════════════════════════════════════
bounties = {}

# ══════════════════════════════════════════════
#  SAUVEGARDE / CHARGEMENT
# ══════════════════════════════════════════════

def load_data():
    global player_data, clans, clan_members, missions, achievements_data, bounties
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
        player_data       = data.get("players", {})
        clans             = data.get("clans", {})
        clan_members      = data.get("clan_members", {})
        missions          = data.get("missions", {})
        achievements_data = data.get("achievements", {})
        bounties          = data.get("bounties", {})
        saved_config = data.get("config", {})
        for k, v in saved_config.items():
            if k in CONFIG:
                CONFIG[k] = v
        print(f"[Data] Chargé : {len(player_data)} joueurs, {len(clans)} clans, {len(bounties)} primes actives")
    except FileNotFoundError:
        print("[Data] Nouveau fichier, démarrage vide")
        player_data = {}; clans = {}; clan_members = {}
        missions = {}; achievements_data = {}; bounties = {}
    except Exception as e:
        print(f"[Erreur] Chargement : {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump({
                "players":      player_data,
                "clans":        clans,
                "clan_members": clan_members,
                "missions":     missions,
                "achievements": achievements_data,
                "bounties":     bounties,
                "config":       CONFIG,
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Erreur] Sauvegarde : {e}")

# ══════════════════════════════════════════════
#  GESTION JOUEURS
# ══════════════════════════════════════════════

def init_player(name):
    if name not in player_data:
        player_data[name] = {
            "total_minutes": 0, "sessions": 0,
            "kills": 0, "deaths": 0,
            "zombie_kills": 0, "clan_kills": 0,
            "last_seen": None,
            "first_seen": datetime.now().isoformat(),
            "achievements": [],
            "rivals": {}
        }

def update_playtime(name, minutes):
    init_player(name)
    player_data[name]["total_minutes"] += minutes
    player_data[name]["sessions"]      += 1
    player_data[name]["last_seen"]      = datetime.now().isoformat()
    if name in clan_members:
        cn = clan_members[name]
        if cn in clans:
            pts = int(minutes / 60) * CONFIG["POINTS_PER_HOUR"]
            if pts > 0:
                clans[cn]["points"] += pts
    if player_data[name]["total_minutes"] >= CONFIG["HOURS_FOR_ACTIVE_ROLE"] * 60:
        check_achievement(name, "survivor_10h")
    save_data()

def record_rivalry(killer, victim):
    player_data[killer].setdefault("rivals", {})
    player_data[killer]["rivals"].setdefault(victim, {"kills": 0, "deaths": 0})
    player_data[killer]["rivals"][victim]["kills"] += 1

    player_data[victim].setdefault("rivals", {})
    player_data[victim]["rivals"].setdefault(killer, {"kills": 0, "deaths": 0})
    player_data[victim]["rivals"][killer]["deaths"] += 1

# ══════════════════════════════════════════════
#  ACHIEVEMENTS
# ══════════════════════════════════════════════

ACHIEVEMENTS = {
    "first_blood":   {"name": "🩸 Premier Sang",        "desc": "1er kill PvP",                           "points": 50},
    "survivor_10h":  {"name": "🏆 Survivant",           "desc": "10h de jeu cumulées",                   "points": 100},
    "zombie_hunter": {"name": "🧟 Chasseur de Zombies", "desc": "100 zombies tués",                      "points": 200},
    "pvp_master":    {"name": "⚔️ Maître PvP",          "desc": "50 kills PvP",                          "points": 300},
    "clan_warrior":  {"name": "🛡️ Guerrier de Clan",   "desc": "10 kills inter-clans",                  "points": 150},
    "nemesis":       {"name": "😈 Nemesis",              "desc": "Tuer le même joueur 5 fois",            "points": 100},
    "comeback":      {"name": "🔥 Comeback",             "desc": "Tuer quelqu'un qui t'avait tué 3+ fois","points": 125},
    "bounty_hunter": {"name": "💰 Chasseur de Primes",  "desc": "Récupérer une prime",                   "points":  75},
}

def check_achievement(player, ach_id, extra=None):
    if ach_id not in ACHIEVEMENTS or player not in player_data: return False
    if ach_id in player_data[player].get("achievements", []):   return False
    d = player_data[player]
    earned = False
    if   ach_id == "first_blood"   and d["kills"] >= 1:                                        earned = True
    elif ach_id == "survivor_10h"  and d["total_minutes"] >= CONFIG["HOURS_FOR_ACTIVE_ROLE"]*60: earned = True
    elif ach_id == "zombie_hunter" and d["zombie_kills"] >= 100:                               earned = True
    elif ach_id == "pvp_master"    and d["kills"] >= 50:                                       earned = True
    elif ach_id == "clan_warrior"  and d.get("clan_kills", 0) >= 10:                           earned = True
    elif ach_id == "nemesis"       and extra and d.get("rivals", {}).get(extra, {}).get("kills", 0) >= 5: earned = True
    elif ach_id == "comeback"      and extra and d.get("rivals", {}).get(extra, {}).get("deaths", 0) >= 3: earned = True
    elif ach_id == "bounty_hunter":                                                            earned = True

    if earned:
        player_data[player].setdefault("achievements", []).append(ach_id)
        if player in clan_members:
            cn = clan_members[player]
            if cn in clans:
                clans[cn]["points"] += ACHIEVEMENTS[ach_id]["points"]
        save_data()
        return ACHIEVEMENTS[ach_id]
    return False

# ══════════════════════════════════════════════
#  PARSING LOGS MINECRAFT
# ══════════════════════════════════════════════

def parse_minecraft_logs(log_content):
    events   = []
    patterns = {
        "join":         r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+joined the game",
        "leave":        r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+left the game",
        "pvp_kill":     r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+was (?:slain|killed) by (\w+)",
        "zombie_death": r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+was (?:slain|killed) by (?:Zombie|zombie)",
        "fall_death":   r"\[(\d{2}:\d{2}:\d{2})\].*?(\w+)\s+(?:fell|died)",
    }
    for line in log_content.split('\n'):
        for etype, pat in patterns.items():
            m = re.search(pat, line)
            if m:
                if etype == "pvp_kill":
                    events.append({"type": etype, "time": m.group(1), "victim": m.group(2), "killer": m.group(3)})
                else:
                    events.append({"type": etype, "time": m.group(1), "player": m.group(2)})
                break
    return events

def process_kill(killer, victim, summary_kills):
    init_player(killer)
    init_player(victim)

    deaths_before = player_data[killer].get("rivals", {}).get(victim, {}).get("deaths", 0)

    player_data[killer]["kills"]  += 1
    player_data[victim]["deaths"] += 1
    summary_kills.append(f"{killer} → {victim}")

    record_rivalry(killer, victim)

    killer_clan = clan_members.get(killer)
    victim_clan = clan_members.get(victim)

    if killer_clan and victim_clan and killer_clan != victim_clan:
        clans[killer_clan]["points"] += CONFIG["POINTS_INTERCLAN_KILL"]
        clans[victim_clan]["points"]  = max(0, clans[victim_clan]["points"] - CONFIG["POINTS_INTERCLAN_DEATH"])
        player_data[killer]["clan_kills"] = player_data[killer].get("clan_kills", 0) + 1
        check_achievement(killer, "clan_warrior")

    if victim in bounties:
        b = bounties[victim]
        proposer_clan = b["proposer_clan"]
        bounty_pts    = b["points"]

        if killer_clan and killer_clan != proposer_clan:
            if killer_clan in clans:
                clans[killer_clan]["points"] += bounty_pts
            del bounties[victim]
            save_data()
            check_achievement(killer, "bounty_hunter")
            print(f"[Bounty] {killer} ({killer_clan}) a récupéré la prime sur {victim} : +{bounty_pts} pts")
        else:
            print(f"[Bounty] Kill ignoré pour la prime : {killer} est du même clan que le proposeur ({proposer_clan})")

    if player_data[killer]["kills"] == 1: check_achievement(killer, "first_blood")
    if player_data[killer]["kills"] >= 50: check_achievement(killer, "pvp_master")
    check_achievement(killer, "nemesis",  extra=victim)
    if deaths_before >= 3: check_achievement(killer, "comeback", extra=victim)

def process_events(events):
    summary = {"joins": [], "kills": [], "deaths": [], "zombie_deaths": []}
    for event in events:
        if event["type"] == "join":
            summary["joins"].append(event["player"])
        elif event["type"] == "pvp_kill":
            process_kill(event["killer"], event["victim"], summary["kills"])
        elif event["type"] == "zombie_death":
            p = event["player"]; init_player(p)
            player_data[p]["deaths"]      += 1
            player_data[p]["zombie_kills"] = player_data[p].get("zombie_kills", 0) + 1
            summary["zombie_deaths"].append(p)
            if player_data[p]["zombie_kills"] >= 100: check_achievement(p, "zombie_hunter")
        elif event["type"] == "fall_death":
            p = event["player"]; init_player(p)
            player_data[p]["deaths"] += 1
            summary["deaths"].append(p)
    save_data()
    return summary

# ══════════════════════════════════════════════
#  SERVEUR MC — ASYNC
# ══════════════════════════════════════════════

import asyncio

async def check_server_status():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _check_server_status_sync)

def _check_server_status_sync():
    try:
        server = JavaServer.lookup(SERVER_ADDRESS, timeout=3)
        status = server.status()

        # Aternos en veille repond avec 0/0 -> hors ligne
        if status.players.max == 0:
            return {"online": False, "player_list": []}

        try:
            query       = server.query()
            player_list = query.players.names if query.players.names else []
        except:
            player_list = []

        return {
            "online": True,
            "players": status.players.online,
            "max_players": status.players.max,
            "player_list": player_list
        }
    except Exception as e:
        print(f"[MC] Serveur injoignable : {e}")
        return {"online": False, "player_list": []}

async def check_and_give_role(guild, player_name):
    if player_name not in player_data: return
    if player_data[player_name]["total_minutes"] / 60 < CONFIG["HOURS_FOR_ACTIVE_ROLE"]: return
    role_name = CONFIG["ACTIVE_ROLE_NAME"]
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name, color=discord.Color.gold(), reason="Rôle auto MC")
        except Exception as e:
            print(f"[Erreur] Création rôle : {e}"); return
    for member in guild.members:
        if member.nick == player_name or member.name == player_name or member.display_name == player_name:
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                    print(f"[Rôle] {player_name} → '{role_name}'")
                except Exception as e:
                    print(f"[Erreur] Ajout rôle : {e}")
            break

# ══════════════════════════════════════════════
#  EVENTS BOT
# ══════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"[Bot] {bot.user} connecté")
    load_data()
    synced = await tree.sync()
    print(f"[Bot] {len(synced)} commandes synchronisées")
    server_monitor.start()

@tasks.loop(minutes=3)
async def server_monitor():
    global previous_status, current_session_players
    s = await check_server_status()
    online = s["online"]

    if online:
        await bot.change_presence(activity=discord.Game(name=f"🟢 {s['players']}/{s['max_players']} joueurs"))
        for p in s["player_list"]:
            if p not in current_session_players:
                current_session_players[p] = datetime.now()
                ch_id = CONFIG["LOGS_CHANNEL_ID"]
                if ch_id:
                    ch = bot.get_channel(ch_id)
                    if ch: await ch.send(f"🟢 **{p}** s'est connecté")
        for p in list(current_session_players):
            if p not in s["player_list"]:
                mins = (datetime.now() - current_session_players[p]).total_seconds() / 60
                update_playtime(p, mins)
                del current_session_players[p]
                ch_id = CONFIG["LOGS_CHANNEL_ID"]
                if ch_id:
                    ch = bot.get_channel(ch_id)
                    if ch: await ch.send(f"🔴 **{p}** déconnecté ({int(mins)} min)")
                for guild in bot.guilds:
                    await check_and_give_role(guild, p)
    else:
        await bot.change_presence(activity=discord.Game(name="🔴 Serveur hors ligne"))
        for p, t in current_session_players.items():
            update_playtime(p, (datetime.now() - t).total_seconds() / 60)
        current_session_players.clear()

    if previous_status is not None and previous_status != online:
        ch_id = CONFIG["ANNOUNCEMENT_CHANNEL_ID"]
        if ch_id:
            ch = bot.get_channel(ch_id)
            if ch:
                if online:
                    e = discord.Embed(title="🟢 Serveur en ligne !", description=f"**{SERVER_ADDRESS}** est accessible !", color=discord.Color.green())
                    await ch.send("@everyone", embed=e)
                else:
                    await ch.send(embed=discord.Embed(title="🔴 Serveur hors ligne", color=discord.Color.red()))
    previous_status = online

async def owner_check(interaction) -> bool:
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ Accès refusé — commande réservée au proprio.", ephemeral=True)
        return False
    return True

def is_clan_leader(player_name, clan_name):
    return clans.get(clan_name, {}).get("leader") == player_name

# ══════════════════════════════════════════════
#  ═══════ COMMANDES SLASH ═══════
# ══════════════════════════════════════════════

@tree.command(name="status", description="Statut du serveur Minecraft")
async def slash_status(interaction: discord.Interaction):
    await interaction.response.defer()
    s = await check_server_status()
    if s["online"]:
        e = discord.Embed(title=f"🎮 {SERVER_DISPLAY_NAME}", description="🟢 En ligne", color=discord.Color.green())
    else:
        e = discord.Embed(title=f"🎮 {SERVER_DISPLAY_NAME}", description="🔴 Hors ligne", color=discord.Color.red())
    await interaction.followup.send(embed=e)

@tree.command(name="stats", description="Stats complètes d'un joueur")
async def slash_stats(interaction: discord.Interaction, joueur: str):
    await interaction.response.defer()
    if joueur not in player_data:
        await interaction.followup.send(f"❌ Aucune donnée pour **{joueur}**"); return
    d     = player_data[joueur]
    hours = d["total_minutes"] / 60
    ratio = d["kills"] / d["deaths"] if d["deaths"] > 0 else float(d["kills"])

    e = discord.Embed(title=f"📊 Stats de {joueur}", color=discord.Color.blue())
    e.add_field(name="⏱️ Temps de jeu",      value=f"{hours:.1f}h",                   inline=True)
    e.add_field(name="🎮 Sessions",           value=str(d["sessions"]),                inline=True)
    e.add_field(name="🛡️ Clan",              value=clan_members.get(joueur,"Aucun"),  inline=True)
    e.add_field(name="⚔️ Kills PvP",         value=str(d["kills"]),                   inline=True)
    e.add_field(name="☠️ Morts",             value=str(d["deaths"]),                  inline=True)
    e.add_field(name="📊 K/D",               value=f"{ratio:.2f}",                   inline=True)
    e.add_field(name="🧟 Zombies",           value=str(d.get("zombie_kills",0)),      inline=True)
    e.add_field(name="🛡️ Kills inter-clan", value=str(d.get("clan_kills",0)),        inline=True)

    if joueur in bounties:
        b = bounties[joueur]
        e.add_field(name="💰 Prime active !", value=f"{b['points']} pts — posée par [{b['proposer_clan']}]", inline=False)

    rivals = d.get("rivals", {})
    if rivals:
        tk = sorted([(r,v) for r,v in rivals.items() if v["kills"]>0],  key=lambda x:x[1]["kills"],  reverse=True)[:3]
        td = sorted([(r,v) for r,v in rivals.items() if v["deaths"]>0], key=lambda x:x[1]["deaths"], reverse=True)[:3]
        if tk: e.add_field(name="🔪 Victimes préférées",    value="\n".join([f"**{r}** : {v['kills']}x"  for r,v in tk]), inline=True)
        if td: e.add_field(name="😵 Te tue le plus souvent",value="\n".join([f"**{r}** : {v['deaths']}x" for r,v in td]), inline=True)

    achs = d.get("achievements", [])
    if achs:
        e.add_field(name=f"🏆 Achievements ({len(achs)})", value="\n".join([ACHIEVEMENTS[a]["name"] for a in achs if a in ACHIEVEMENTS]), inline=False)
    await interaction.followup.send(embed=e)

@tree.command(name="rivalry", description="Historique de kills entre deux joueurs")
async def slash_rivalry(interaction: discord.Interaction, joueur1: str, joueur2: str):
    await interaction.response.defer()
    if joueur1 not in player_data or joueur2 not in player_data:
        await interaction.followup.send("❌ L'un des deux joueurs n'a pas de données"); return
    r1 = player_data[joueur1].get("rivals", {}).get(joueur2, {"kills":0,"deaths":0})
    r2 = player_data[joueur2].get("rivals", {}).get(joueur1, {"kills":0,"deaths":0})
    j1k = r1["kills"]; j2k = r2["kills"]; total = j1k + j2k

    e = discord.Embed(title=f"⚔️ {joueur1} vs {joueur2}", color=discord.Color.red())
    if total > 0:
        p1  = int((j1k/total)*10)
        bar = "🟥"*p1 + "🟦"*(10-p1)
        e.add_field(name=f"📊 {joueur1} ←→ {joueur2}", value=bar, inline=False)
    e.add_field(name=f"💀 {joueur1} → {joueur2}", value=f"**{j1k}** kills", inline=True)
    e.add_field(name=f"💀 {joueur2} → {joueur1}", value=f"**{j2k}** kills", inline=True)
    e.add_field(name="🎯 Total",                  value=str(total),         inline=True)
    if j1k > j2k:   e.add_field(name="👑 Dominant", value=f"**{joueur1}** domine (+{j1k-j2k})", inline=False)
    elif j2k > j1k: e.add_field(name="👑 Dominant", value=f"**{joueur2}** domine (+{j2k-j1k})", inline=False)
    else:            e.add_field(name="🤝",          value="Égalité parfaite",                   inline=False)
    await interaction.followup.send(embed=e)

@tree.command(name="myrivalry", description="Tes stats contre un adversaire précis")
async def slash_myrivalry(interaction: discord.Interaction, adversaire: str):
    await interaction.response.defer()
    joueur = interaction.user.display_name
    if joueur not in player_data:
        await interaction.followup.send(f"❌ Aucune donnée pour toi ({joueur})"); return
    if adversaire not in player_data:
        await interaction.followup.send(f"❌ **{adversaire}** n'a pas de données"); return
    r = player_data[joueur].get("rivals",{}).get(adversaire,{"kills":0,"deaths":0})
    k = r["kills"]; d = r["deaths"]; total = k+d
    ratio = k/d if d>0 else float(k)
    if k>d:   desc, color = f"✅ Tu **domines** {adversaire} !", discord.Color.green()
    elif d>k: desc, color = f"❌ **{adversaire}** te domine...", discord.Color.red()
    else:     desc, color = f"🤝 Égalité avec {adversaire}", discord.Color.orange()
    e = discord.Embed(title=f"⚔️ Toi vs {adversaire}", description=desc, color=color)
    e.add_field(name="💀 Fois que tu l'as tué",    value=str(k),          inline=True)
    e.add_field(name="☠️ Fois qu'il t'a tué",     value=str(d),          inline=True)
    e.add_field(name="📊 Ratio vs lui",             value=f"{ratio:.2f}", inline=True)
    e.add_field(name="🎯 Total affrontements",      value=str(total),     inline=True)
    await interaction.followup.send(embed=e)

@tree.command(name="pvpleaderboard", description="Classement PvP")
async def slash_pvpleaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    pvp = sorted([(n,d) for n,d in player_data.items() if d.get("kills",0)>0], key=lambda x:x[1]["kills"], reverse=True)
    if not pvp:
        await interaction.followup.send("❌ Aucune donnée PvP"); return
    e = discord.Embed(title="⚔️ Classement PvP", color=discord.Color.red())
    for i,(player,d) in enumerate(pvp[:10]):
        k=d.get("kills",0); dth=d.get("deaths",0); ratio=k/dth if dth>0 else float(k)
        tag=f" [{clan_members[player]}]" if player in clan_members else ""
        medal=["🥇","🥈","🥉"][i] if i<3 else f"{i+1}."
        e.add_field(name=f"{medal} {player}{tag}", value=f"💀 {k} kills • ☠️ {dth} morts • K/D: {ratio:.2f}", inline=False)
    await interaction.followup.send(embed=e)

@tree.command(name="top", description="Classement par temps de jeu")
async def slash_top(interaction: discord.Interaction):
    await interaction.response.defer()
    if not player_data:
        await interaction.followup.send("❌ Aucune donnée"); return
    sp = sorted(player_data.items(), key=lambda x:x[1]["total_minutes"], reverse=True)
    e  = discord.Embed(title="⏱️ Classement Temps de Jeu", color=discord.Color.blurple())
    for i,(player,d) in enumerate(sp[:10]):
        h=d["total_minutes"]/60; tag=f" [{clan_members[player]}]" if player in clan_members else ""
        medal=["🥇","🥈","🥉"][i] if i<3 else f"{i+1}."
        e.add_field(name=f"{medal} {player}{tag}", value=f"⏱️ {h:.1f}h • 🎮 {d['sessions']} sessions", inline=False)
    await interaction.followup.send(embed=e)

# ── BOUNTIES (PRIMES) ─────────────────────────

@tree.command(name="bounty", description="Poser une prime sur un joueur ennemi")
async def slash_bounty(interaction: discord.Interaction, cible: str, points: int):
    await interaction.response.defer()
    player_name = interaction.user.display_name

    if player_name not in clan_members:
        await interaction.followup.send("❌ Tu dois être dans un clan pour poser une prime"); return

    clan_name = clan_members[player_name]

    if not is_clan_leader(player_name, clan_name):
        await interaction.followup.send("❌ Seul le chef de clan peut poser une prime"); return

    if points <= 0:
        await interaction.followup.send("❌ Les points doivent être positifs"); return

    if points > CONFIG["MAX_BOUNTY_POINTS"]:
        await interaction.followup.send(f"❌ Maximum {CONFIG['MAX_BOUNTY_POINTS']} points par prime"); return

    if clans[clan_name]["points"] < points:
        await interaction.followup.send(f"❌ Ton clan n'a que **{clans[clan_name]['points']}** points, pas assez pour cette prime"); return

    if cible not in player_data:
        await interaction.followup.send(f"❌ **{cible}** n'a jamais joué sur le serveur"); return

    if clan_members.get(cible) == clan_name:
        await interaction.followup.send("❌ Tu ne peux pas mettre une prime sur un membre de TON clan"); return

    if cible in bounties:
        await interaction.followup.send(f"❌ **{cible}** a déjà une prime active ({bounties[cible]['points']} pts)"); return

    clans[clan_name]["points"] -= points
    bounties[cible] = {
        "proposer_clan": clan_name,
        "proposed_by":   player_name,
        "points":        points,
        "created":       datetime.now().isoformat(),
    }
    save_data()

    e = discord.Embed(title="💰 Prime posée !", color=discord.Color.gold())
    e.add_field(name="🎯 Cible",      value=cible,                            inline=True)
    e.add_field(name="💰 Récompense", value=f"{points} pts",                 inline=True)
    e.add_field(name="📤 Proposé par",value=f"{player_name} [{clan_name}]", inline=True)
    e.add_field(name="ℹ️ Info",       value=f"Les {points} pts ont été retirés de **{clan_name}**. Ils seront rendus si la prime est annulée.", inline=False)
    e.set_footer(text="⚠️ Un membre du même clan ne peut pas récupérer la prime (anti-farm)")
    await interaction.followup.send(embed=e)

@tree.command(name="cancelbounty", description="Annuler une prime et récupérer les points")
async def slash_cancelbounty(interaction: discord.Interaction, cible: str):
    await interaction.response.defer()
    player_name = interaction.user.display_name

    if cible not in bounties:
        await interaction.followup.send(f"❌ Aucune prime active sur **{cible}**"); return

    b = bounties[cible]
    is_owner    = interaction.user.id == OWNER_ID
    is_proposer = (player_name in clan_members
                   and clan_members[player_name] == b["proposer_clan"]
                   and is_clan_leader(player_name, b["proposer_clan"]))

    if not is_owner and not is_proposer:
        await interaction.followup.send("❌ Seul le chef du clan proposeur ou le proprio peut annuler cette prime"); return

    pts  = b["points"]
    clan = b["proposer_clan"]
    if clan in clans:
        clans[clan]["points"] += pts
    del bounties[cible]
    save_data()

    await interaction.followup.send(f"✅ Prime sur **{cible}** annulée. **{pts} pts** rendus au clan **{clan}**.")

@tree.command(name="bounties", description="Voir toutes les primes actives")
async def slash_bounties(interaction: discord.Interaction):
    await interaction.response.defer()
    if not bounties:
        await interaction.followup.send("✅ Aucune prime active en ce moment"); return
    e = discord.Embed(title="💰 Primes Actives", color=discord.Color.gold())
    for target, b in bounties.items():
        created = datetime.fromisoformat(b["created"]).strftime("%d/%m %H:%M")
        e.add_field(
            name=f"🎯 {target}",
            value=f"💰 **{b['points']} pts** • Posée par **{b['proposed_by']}** [{b['proposer_clan']}] le {created}",
            inline=False
        )
    e.set_footer(text="⚠️ Un membre du clan proposeur ne peut pas récupérer sa propre prime")
    await interaction.followup.send(embed=e)

# ── CLANS ─────────────────────────────────────

@tree.command(name="createclan", description="Créer un nouveau clan")
async def slash_createclan(interaction: discord.Interaction, nom: str):
    await interaction.response.defer()
    pn = interaction.user.display_name
    if pn in clan_members:
        await interaction.followup.send(f"❌ Tu es déjà dans **{clan_members[pn]}**. Utilise `/leaveclan` d'abord."); return
    if nom in clans:
        await interaction.followup.send("❌ Ce nom de clan existe déjà"); return
    if len(nom) > CONFIG["MAX_CLAN_NAME_LENGTH"]:
        await interaction.followup.send(f"❌ Nom max {CONFIG['MAX_CLAN_NAME_LENGTH']} caractères"); return
    clans[nom] = {"leader": pn, "created": datetime.now().isoformat(), "points": 0}
    clan_members[pn] = nom
    save_data()
    e = discord.Embed(title=f"🛡️ Clan créé : {nom}", color=discord.Color.green())
    e.add_field(name="👑 Chef", value=pn, inline=True)
    e.set_footer(text=f"Les membres rejoignent avec /joinclan {nom}")
    await interaction.followup.send(embed=e)

@tree.command(name="joinclan", description="Rejoindre un clan existant")
async def slash_joinclan(interaction: discord.Interaction, nom: str):
    await interaction.response.defer()
    pn = interaction.user.display_name
    if pn in clan_members:
        await interaction.followup.send(f"❌ Tu es déjà dans **{clan_members[pn]}**"); return
    if nom not in clans:
        await interaction.followup.send(f"❌ Le clan **{nom}** n'existe pas"); return
    clan_members[pn] = nom
    save_data()
    count = len([p for p,c in clan_members.items() if c==nom])
    await interaction.followup.send(f"✅ Tu as rejoint **{nom}** ! ({count} membres au total)")


@tree.command(name="setupclan", description="Créer un clan complet d'un coup : nom, chef et membres (proprio)")
async def slash_setupclan(
    interaction: discord.Interaction,
    nom: str,
    chef: str,
    membres: str  # pseudos séparés par des virgules, ex: "Alice,Bob,Charlie"
):
    """
    Crée un clan en une seule commande.
    membres : pseudos séparés par des virgules (sans espaces autour)
    Ex: /setupclan nom:Warriors chef:Steve membres:Alex,Notch,Herobrine
    """
    if not await owner_check(interaction): return
    await interaction.response.defer(ephemeral=True)

    # Vérif nom
    if nom in clans:
        await interaction.followup.send(f"❌ Le clan **{nom}** existe déjà", ephemeral=True); return
    if len(nom) > CONFIG["MAX_CLAN_NAME_LENGTH"]:
        await interaction.followup.send(f"❌ Nom max {CONFIG['MAX_CLAN_NAME_LENGTH']} caractères", ephemeral=True); return

    # Parse les membres
    membre_list = [m.strip() for m in membres.split(",") if m.strip()]
    if not membre_list:
        await interaction.followup.send("❌ Aucun membre valide fourni", ephemeral=True); return

    # Ajoute le chef dans la liste si pas déjà dedans
    if chef not in membre_list:
        membre_list.insert(0, chef)

    # Vérifie les conflits de clan
    conflicts = [m for m in membre_list if m in clan_members]
    if conflicts:
        conflict_details = ", ".join([f"**{m}** (dans {clan_members[m]})" for m in conflicts])
        await interaction.followup.send(f"❌ Ces joueurs sont déjà dans un clan : {conflict_details}", ephemeral=True); return

    # Crée le clan
    clans[nom] = {"leader": chef, "created": datetime.now().isoformat(), "points": 0}

    # Ajoute tous les membres
    added = []
    for m in membre_list:
        init_player(m)
        clan_members[m] = nom
        added.append(m)

    save_data()

    # Résumé
    membres_str = "\n".join([f"{'👑' if m == chef else '👤'} {m}" for m in added])
    e = discord.Embed(title=f"🛡️ Clan **{nom}** créé !", color=discord.Color.green())
    e.add_field(name="👑 Chef",      value=chef,            inline=True)
    e.add_field(name="👥 Membres",   value=str(len(added)), inline=True)
    e.add_field(name="📋 Liste",     value=membres_str,     inline=False)
    await interaction.followup.send(embed=e, ephemeral=True)

@tree.command(name="setleader", description="Changer le chef d'un clan (proprio)")
async def slash_setleader(interaction: discord.Interaction, clan: str, nouveau_chef: str):
    if not await owner_check(interaction): return
    if clan not in clans:
        await interaction.response.send_message("❌ Ce clan n'existe pas", ephemeral=True); return
    if nouveau_chef in clan_members and clan_members[nouveau_chef] != clan:
        await interaction.response.send_message(f"❌ **{nouveau_chef}** est dans un autre clan. Retire-le d'abord.", ephemeral=True); return
    ancien = clans[clan]["leader"]
    clans[clan]["leader"] = nouveau_chef
    if nouveau_chef not in clan_members:
        clan_members[nouveau_chef] = clan
    save_data()
    await interaction.response.send_message(f"✅ Chef de **{clan}** : **{ancien}** → **{nouveau_chef}**", ephemeral=True)

@tree.command(name="deleteclan", description="Supprimer un clan (proprio)")
async def slash_deleteclan(interaction: discord.Interaction, nom: str):
    if not await owner_check(interaction): return
    if nom not in clans:
        await interaction.response.send_message("❌ Ce clan n'existe pas", ephemeral=True); return
    refund = 0
    for target, b in list(bounties.items()):
        if b["proposer_clan"] == nom:
            refund += b["points"]
            del bounties[target]
    removed=[p for p,c in clan_members.items() if c==nom]
    for m in removed: del clan_members[m]
    del clans[nom]
    save_data()
    msg = f"✅ **{nom}** supprimé ({len(removed)} membres retirés)"
    if refund: msg += f"\n💰 {refund} pts de primes annulées (perdus car le clan n'existe plus)"
    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="addtoclan", description="Ajouter un joueur dans un clan (proprio)")
async def slash_addtoclan(interaction: discord.Interaction, joueur: str, clan: str):
    if not await owner_check(interaction): return
    if clan not in clans:
        await interaction.response.send_message("❌ Ce clan n'existe pas", ephemeral=True); return
    if joueur in clan_members:
        await interaction.response.send_message(f"❌ **{joueur}** est déjà dans **{clan_members[joueur]}**", ephemeral=True); return
    clan_members[joueur] = clan
    save_data()
    await interaction.response.send_message(f"✅ **{joueur}** ajouté dans **{clan}**", ephemeral=True)

@tree.command(name="removefromclan", description="Retirer un joueur d'un clan (proprio)")
async def slash_removefromclan(interaction: discord.Interaction, joueur: str):
    if not await owner_check(interaction): return
    if joueur not in clan_members:
        await interaction.response.send_message(f"❌ **{joueur}** n'est dans aucun clan", ephemeral=True); return
    cn = clan_members[joueur]
    if clans.get(cn,{}).get("leader") == joueur:
        others=[p for p,c in clan_members.items() if c==cn and p!=joueur]
        if others: clans[cn]["leader"] = others[0]
    del clan_members[joueur]
    save_data()
    await interaction.response.send_message(f"✅ **{joueur}** retiré de **{cn}**", ephemeral=True)

@tree.command(name="resetstats", description="Reset les stats d'un joueur (proprio)")
async def slash_resetstats(interaction: discord.Interaction, joueur: str):
    if not await owner_check(interaction): return
    if joueur not in player_data:
        await interaction.response.send_message(f"❌ Aucune donnée pour **{joueur}**", ephemeral=True); return
    player_data[joueur] = {
        "total_minutes":0,"sessions":0,"kills":0,"deaths":0,
        "zombie_kills":0,"clan_kills":0,"last_seen":None,
        "first_seen":datetime.now().isoformat(),"achievements":[],"rivals":{}
    }
    save_data()
    await interaction.response.send_message(f"✅ Stats de **{joueur}** remises à zéro", ephemeral=True)

@tree.command(name="cancelbountyadmin", description="Forcer l'annulation d'une prime (proprio)")
async def slash_cancelbountyadmin(interaction: discord.Interaction, cible: str, rembourser: bool):
    if not await owner_check(interaction): return
    if cible not in bounties:
        await interaction.response.send_message(f"❌ Aucune prime active sur **{cible}**", ephemeral=True); return
    b   = bounties[cible]
    msg = f"✅ Prime sur **{cible}** supprimée ({b['points']} pts)"
    if rembourser and b["proposer_clan"] in clans:
        clans[b["proposer_clan"]]["points"] += b["points"]
        msg += f" — **{b['points']} pts rendus** à **{b['proposer_clan']}**"
    else:
        msg += " — points **perdus**"
    del bounties[cible]
    save_data()
    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="setchannel", description="Salon des annonces (proprio)")
async def slash_setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await owner_check(interaction): return
    CONFIG["ANNOUNCEMENT_CHANNEL_ID"] = channel.id
    save_data()
    await interaction.response.send_message(f"✅ Annonces dans {channel.mention}", ephemeral=True)
    await channel.send("🔔 Ce salon recevra les annonces du serveur Minecraft.")

@tree.command(name="setlogschannel", description="Salon des logs (proprio)")
async def slash_setlogschannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await owner_check(interaction): return
    CONFIG["LOGS_CHANNEL_ID"] = channel.id
    save_data()
    await interaction.response.send_message(f"✅ Logs dans {channel.mention}", ephemeral=True)
    await channel.send("📋 Ce salon recevra les connexions/déconnexions.")

# ── AIDE ──────────────────────────────────────

@tree.command(name="help", description="Liste de toutes les commandes")
async def slash_help(interaction: discord.Interaction):
    # ── Embed 1 : Stats + Bounties + Clans (max 25 champs) ──
    e1 = discord.Embed(title="📖 Commandes du Bot Minecraft (1/2)", color=discord.Color.blurple())

    e1.add_field(name="━━ 🎮 STATS ━━",               value="\u200b", inline=False)
    e1.add_field(name="/status",                       value="Statut serveur",              inline=True)
    e1.add_field(name="/stats <joueur>",               value="Stats complètes",             inline=True)
    e1.add_field(name="/pvpleaderboard",               value="Top kills PvP",               inline=True)
    e1.add_field(name="/top",                          value="Top temps de jeu",            inline=True)
    e1.add_field(name="/rivalry <j1> <j2>",            value="Historique entre 2 joueurs",  inline=True)
    e1.add_field(name="/myrivalry <adversaire>",       value="Tes stats vs un joueur",      inline=True)

    e1.add_field(name="━━ 💰 BOUNTIES ━━",             value="\u200b", inline=False)
    e1.add_field(name="/bounty <cible> <pts>",         value="Poser une prime (chef clan)", inline=True)
    e1.add_field(name="/cancelbounty <cible>",         value="Annuler ta prime",            inline=True)
    e1.add_field(name="/bounties",                     value="Voir toutes les primes",      inline=True)

    e1.add_field(name="━━ 🛡️ CLANS ━━",              value="\u200b", inline=False)
    e1.add_field(name="/createclan <nom>",             value="Créer un clan",               inline=True)
    e1.add_field(name="/joinclan <nom>",               value="Rejoindre un clan",           inline=True)
    e1.add_field(name="/leaveclan",                    value="Quitter ton clan",            inline=True)
    e1.add_field(name="/claninfo <nom>",               value="Infos d'un clan",             inline=True)
    e1.add_field(name="/clanleaderboard",              value="Classement des clans",        inline=True)
    e1.add_field(name="/transferleader <pseudo>",      value="Passer ton leadership",       inline=True)
    e1.add_field(name="/setupclan <nom> <chef> <membres>", value="Créer clan complet (proprio)", inline=True)

    # ── Embed 2 : Admin ──
    e2 = discord.Embed(title="📖 Commandes Admin (2/2)", color=discord.Color.gold())
    e2.add_field(name="━━ 👑 ADMIN (proprio) ━━",      value="\u200b", inline=False)
    e2.add_field(name="/setupclan <nom> <chef> <membres>", value="Créer un clan complet d'un coup",  inline=True)
    e2.add_field(name="/config",                       value="Voir la config du bot",        inline=True)
    e2.add_field(name="/setconfig <clé> <valeur>",     value="Modifier la config",           inline=True)
    e2.add_field(name="/listplayers",                  value="Tous les joueurs enregistrés", inline=True)
    e2.add_field(name="/setleader <clan> <chef>",      value="Changer le chef d'un clan",    inline=True)
    e2.add_field(name="/setpoints <clan> <pts>",       value="Définir les points exactement",inline=True)
    e2.add_field(name="/addpoints <clan> <pts>",       value="Ajouter/retirer des points",   inline=True)
    e2.add_field(name="/renameclan <ancien> <nouveau>",value="Renommer un clan",             inline=True)
    e2.add_field(name="/givekill <killer> <victim>",   value="Enregistrer un kill manuellement",inline=True)
    e2.add_field(name="/addtime <joueur> <min>",       value="Ajouter du temps de jeu",      inline=True)
    e2.add_field(name="/uploadlogs",                   value="Analyser logs MC (.log/.txt)", inline=True)
    e2.add_field(name="/deleteclan <nom>",             value="Supprimer un clan",            inline=True)
    e2.add_field(name="/addtoclan <j> <clan>",         value="Ajouter dans un clan",         inline=True)
    e2.add_field(name="/removefromclan <j>",           value="Retirer d'un clan",            inline=True)
    e2.add_field(name="/resetstats <joueur>",          value="Reset stats d'un joueur",      inline=True)
    e2.add_field(name="/cancelbountyadmin <cible>",    value="Forcer annulation prime",      inline=True)
    e2.add_field(name="/setchannel",                   value="Salon des annonces",           inline=True)
    e2.add_field(name="/setlogschannel",               value="Salon des logs",               inline=True)
    e2.set_footer(text="💡 Points bounty : retenus en escrow dès la création | rendus si annulation")

    await interaction.response.send_message(embeds=[e1, e2])

bot.run(BOT_TOKEN)
