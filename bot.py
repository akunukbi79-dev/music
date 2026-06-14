import discord
from discord.ext import commands
import asyncio
import yt_dlp
import os
import re
import aiohttp
import base64
from collections import deque

# ─────────────────────────────────────────────
#  KONFIGURASI
# ─────────────────────────────────────────────
TOKEN          = os.environ.get("TOKEN", "MASUKKAN_TOKEN_BOT_KAMU_DISINI")
SPOTIFY_ID     = os.environ.get("SPOTIFY_ID", "MASUKKAN_SPOTIFY_CLIENT_ID")
SPOTIFY_SECRET = os.environ.get("SPOTIFY_SECRET", "MASUKKAN_SPOTIFY_CLIENT_SECRET")
PREFIX         = "!"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ─────────────────────────────────────────────
#  YT-DLP OPTIONS
# ─────────────────────────────────────────────
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "opus",
    }],
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# ─────────────────────────────────────────────
#  STATE PER SERVER
# ─────────────────────────────────────────────
class GuildState:
    def __init__(self):
        self.queue: deque = deque()
        self.current: dict | None = None
        self.loop: bool = False
        self.loop_queue: bool = False
        self.volume: float = 1.0
        self.text_channel = None

guild_states: dict[int, GuildState] = {}

def get_state(guild_id: int) -> GuildState:
    if guild_id not in guild_states:
        guild_states[guild_id] = GuildState()
    return guild_states[guild_id]

# ─────────────────────────────────────────────
#  SPOTIFY API
# ─────────────────────────────────────────────
_spotify_token: str | None = None
_spotify_token_expiry: float = 0

async def get_spotify_token() -> str | None:
    global _spotify_token, _spotify_token_expiry
    import time
    if _spotify_token and time.time() < _spotify_token_expiry:
        return _spotify_token
    if SPOTIFY_ID == "MASUKKAN_SPOTIFY_CLIENT_ID":
        return None
    creds = base64.b64encode(f"{SPOTIFY_ID}:{SPOTIFY_SECRET}".encode()).decode()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "client_credentials"},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            _spotify_token = data.get("access_token")
            _spotify_token_expiry = time.time() + data.get("expires_in", 3600) - 60
            return _spotify_token

def parse_spotify_url(url: str) -> tuple[str, str] | None:
    """Return (type, id) misal ('track','abc123') atau ('playlist','xyz')."""
    pattern = r"spotify\.com/(track|playlist|album)/([A-Za-z0-9]+)"
    m = re.search(pattern, url)
    if m:
        return m.group(1), m.group(2)
    return None

def convert_ytmusic_url(url: str) -> str:
    """
    Konversi URL YouTube Music ke YouTube biasa agar bisa diproses yt-dlp.
    music.youtube.com/watch?v=XXX  →  youtube.com/watch?v=XXX
    music.youtube.com/playlist?list=XXX  →  youtube.com/playlist?list=XXX
    """
    return url.replace("music.youtube.com", "www.youtube.com")

async def spotify_track_to_query(track_id: str) -> str | None:
    token = await get_spotify_token()
    if not token:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://api.spotify.com/v1/tracks/{track_id}",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            artists = ", ".join(a["name"] for a in data["artists"])
            return f"{data['name']} {artists}"

async def spotify_playlist_to_queries(playlist_id: str) -> list[str]:
    token = await get_spotify_token()
    if not token:
        return []
    queries = []
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit=50"
    async with aiohttp.ClientSession() as session:
        while url:
            async with session.get(url, headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                for item in data.get("items", []):
                    track = item.get("track")
                    if track:
                        artists = ", ".join(a["name"] for a in track["artists"])
                        queries.append(f"{track['name']} {artists}")
                url = data.get("next")
    return queries

async def spotify_album_to_queries(album_id: str) -> list[str]:
    token = await get_spotify_token()
    if not token:
        return []
    queries = []
    url = f"https://api.spotify.com/v1/albums/{album_id}/tracks?limit=50"
    async with aiohttp.ClientSession() as session:
        while url:
            async with session.get(url, headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                for track in data.get("items", []):
                    artists = ", ".join(a["name"] for a in track["artists"])
                    queries.append(f"{track['name']} {artists}")
                url = data.get("next")
    return queries

# ─────────────────────────────────────────────
#  HELPER: AMBIL INFO LAGU DARI YOUTUBE
# ─────────────────────────────────────────────
async def fetch_song(query: str) -> list[dict]:
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = await loop.run_in_executor(
                None, lambda: ydl.extract_info(query, download=False)
            )
        except Exception:
            return []

    songs = []
    if "entries" in info:
        for entry in info["entries"]:
            if entry:
                songs.append(_build_song(entry))
    else:
        songs.append(_build_song(info))
    return songs

def _build_song(info: dict) -> dict:
    return {
        "url": info.get("url") or info.get("webpage_url"),
        "title": info.get("title", "Unknown"),
        "duration": info.get("duration", 0),
        "webpage_url": info.get("webpage_url", ""),
        "thumbnail": info.get("thumbnail", ""),
        "uploader": info.get("uploader", "Unknown"),
    }

def format_duration(seconds: int) -> str:
    if not seconds:
        return "Live"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"

def music_embed(title: str, description: str = "", color=0x1DB954, thumbnail: str = "") -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    return e

# ─────────────────────────────────────────────
#  PUTAR LAGU BERIKUTNYA
# ─────────────────────────────────────────────
async def play_next(guild: discord.Guild):
    state = get_state(guild.id)
    vc: discord.VoiceClient = guild.voice_client
    if not vc or not vc.is_connected():
        return

    if state.loop and state.current:
        song = state.current
    elif state.queue:
        song = state.queue.popleft()
        if state.loop_queue:
            state.queue.append(song)
        state.current = song
    else:
        state.current = None
        if state.text_channel:
            await state.text_channel.send(
                embed=music_embed("⏹ Queue Habis", "Tidak ada lagu lagi.", color=0xff6b6b)
            )
        return

    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = await loop.run_in_executor(
                None, lambda: ydl.extract_info(
                    song.get("webpage_url") or song["url"], download=False
                )
            )
            stream_url = info.get("url") or info.get("formats", [{}])[-1].get("url")
        except Exception:
            stream_url = song["url"]

    source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
    source = discord.PCMVolumeTransformer(source, volume=state.volume)

    def after_play(error):
        if error:
            print(f"[Error] {error}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

    vc.play(source, after=after_play)

    if state.text_channel:
        e = music_embed(
            "🎵 Sekarang Memutar",
            f"**[{song['title']}]({song.get('webpage_url', '')})**\n"
            f"⏱ `{format_duration(song['duration'])}`  |  🎤 {song['uploader']}",
            thumbnail=song.get("thumbnail", ""),
        )
        e.set_footer(text=f"Volume: {int(state.volume*100)}%  |  Loop: {'✅' if state.loop else '❌'}  |  Loop Queue: {'✅' if state.loop_queue else '❌'}")
        await state.text_channel.send(embed=e)

# ─────────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot aktif sebagai {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name=f"{PREFIX}help | Music Bot"
    ))

@bot.event
async def on_voice_state_update(member, before, after):
    vc = member.guild.voice_client
    if not vc:
        return
    if len(vc.channel.members) == 1:
        await asyncio.sleep(60)
        if vc.is_connected() and len(vc.channel.members) == 1:
            await vc.disconnect()
            state = get_state(member.guild.id)
            state.queue.clear()
            state.current = None
            if state.text_channel:
                await state.text_channel.send(
                    embed=music_embed("👋 Auto Disconnect", "Bot keluar karena sendirian.", color=0xffa500)
                )

# ─────────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────────

@bot.command(name="join", aliases=["j"])
async def cmd_join(ctx):
    if not ctx.author.voice:
        return await ctx.send(embed=music_embed("❌", "Masuk ke voice channel dulu!", color=0xff0000))
    channel = ctx.author.voice.channel
    if ctx.voice_client:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()
    get_state(ctx.guild.id).text_channel = ctx.channel
    await ctx.send(embed=music_embed("✅ Joined", f"Bergabung ke **{channel.name}**"))

# ─── PLAY (YouTube + Spotify) ───
@bot.command(name="play", aliases=["p"])
async def cmd_play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send(embed=music_embed("❌", "Masuk ke voice channel dulu!", color=0xff0000))
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    state = get_state(ctx.guild.id)
    state.text_channel = ctx.channel

    msg = await ctx.send(embed=music_embed("🔍 Memproses...", f"`{query}`", color=0xffa500))

    # ── Cek apakah link YouTube Music ──
    if "music.youtube.com" in query:
        query = convert_ytmusic_url(query)

    # ── Cek apakah link Spotify ──
    spotify_info = parse_spotify_url(query)
    if spotify_info:
        sp_type, sp_id = spotify_info

        if sp_type == "track":
            search_query = await spotify_track_to_query(sp_id)
            if not search_query:
                return await msg.edit(embed=music_embed("❌", "Gagal ambil info dari Spotify. Cek SPOTIFY_ID & SPOTIFY_SECRET.", color=0xff0000))
            songs = await fetch_song(search_query)
            label = "lagu Spotify"

        elif sp_type in ("playlist", "album"):
            fn = spotify_playlist_to_queries if sp_type == "playlist" else spotify_album_to_queries
            queries = await fn(sp_id)
            if not queries:
                return await msg.edit(embed=music_embed("❌", "Gagal ambil playlist/album dari Spotify.", color=0xff0000))

            await msg.edit(embed=music_embed(
                "🟢 Spotify Playlist/Album",
                f"Memuat **{len(queries)} lagu**... harap tunggu ⏳",
                color=0x1DB954
            ))

            # Ambil lagu pertama langsung, sisanya masuk queue pakai judul
            songs = []
            for q in queries:
                result = await fetch_song(q)
                if result:
                    songs.append(result[0])

            for song in songs:
                state.queue.append(song)

            await msg.edit(embed=music_embed(
                "🟢 Spotify Dimuat",
                f"**{len(songs)} lagu** dari Spotify berhasil masuk ke queue!",
                color=0x1DB954
            ))
            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await play_next(ctx.guild)
            return
        else:
            return await msg.edit(embed=music_embed("❌", "Tipe Spotify tidak didukung.", color=0xff0000))

        label = "lagu Spotify"
    else:
        # YouTube / nama lagu biasa
        songs = await fetch_song(query)
        label = "lagu"

    if not songs:
        return await msg.edit(embed=music_embed("❌ Tidak Ditemukan", f"`{query}` tidak ditemukan.", color=0xff0000))

    for song in songs:
        state.queue.append(song)

    if len(songs) == 1:
        desc = (
            f"**[{songs[0]['title']}]({songs[0].get('webpage_url','')})**\n"
            f"⏱ `{format_duration(songs[0]['duration'])}`"
        )
        await msg.edit(embed=music_embed(f"✅ {label.capitalize()} Ditambahkan", desc, thumbnail=songs[0].get("thumbnail","")))
    else:
        await msg.edit(embed=music_embed("✅ Playlist Ditambahkan", f"**{len(songs)} lagu** masuk ke queue."))

    if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
        await play_next(ctx.guild)

@bot.command(name="skip", aliases=["s", "next"])
async def cmd_skip(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send(embed=music_embed("❌", "Tidak ada lagu yang diputar.", color=0xff0000))
    ctx.voice_client.stop()
    await ctx.send(embed=music_embed("⏭ Skipped", "Lagu di-skip!"))

@bot.command(name="pause")
async def cmd_pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send(embed=music_embed("⏸ Paused", "Lagu di-pause."))
    else:
        await ctx.send(embed=music_embed("❌", "Tidak ada lagu yang diputar.", color=0xff0000))

@bot.command(name="resume", aliases=["r"])
async def cmd_resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send(embed=music_embed("▶️ Resumed", "Lagu dilanjutkan."))
    else:
        await ctx.send(embed=music_embed("❌", "Tidak ada lagu yang di-pause.", color=0xff0000))

@bot.command(name="stop", aliases=["disconnect", "dc", "leave"])
async def cmd_stop(ctx):
    state = get_state(ctx.guild.id)
    state.queue.clear()
    state.current = None
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
    await ctx.send(embed=music_embed("⏹ Stopped", "Bot keluar dan queue dihapus."))

@bot.command(name="queue", aliases=["q", "list"])
async def cmd_queue(ctx):
    state = get_state(ctx.guild.id)
    if not state.current and not state.queue:
        return await ctx.send(embed=music_embed("📭 Queue Kosong", "Tidak ada lagu di queue."))
    desc = ""
    if state.current:
        desc += f"**🎵 Sekarang:**\n[{state.current['title']}]({state.current.get('webpage_url','')}) — `{format_duration(state.current['duration'])}`\n\n"
    if state.queue:
        desc += "**📋 Selanjutnya:**\n"
        for i, song in enumerate(list(state.queue)[:15], 1):
            desc += f"`{i}.` [{song['title']}]({song.get('webpage_url','')}) — `{format_duration(song['duration'])}`\n"
        if len(state.queue) > 15:
            desc += f"\n_...dan {len(state.queue)-15} lagu lainnya_"
    e = music_embed("🎶 Queue Musik", desc)
    e.set_footer(text=f"Total: {len(state.queue)} lagu  |  Loop: {'✅' if state.loop else '❌'}  |  Loop Queue: {'✅' if state.loop_queue else '❌'}")
    await ctx.send(embed=e)

@bot.command(name="nowplaying", aliases=["np", "current"])
async def cmd_np(ctx):
    state = get_state(ctx.guild.id)
    if not state.current:
        return await ctx.send(embed=music_embed("❌", "Tidak ada lagu yang diputar.", color=0xff0000))
    song = state.current
    e = music_embed(
        "🎵 Sekarang Memutar",
        f"**[{song['title']}]({song.get('webpage_url','')})**\n"
        f"⏱ `{format_duration(song['duration'])}`  |  🎤 {song['uploader']}",
        thumbnail=song.get("thumbnail",""),
    )
    await ctx.send(embed=e)

@bot.command(name="volume", aliases=["vol", "v"])
async def cmd_volume(ctx, volume: int):
    if not 1 <= volume <= 200:
        return await ctx.send(embed=music_embed("❌", "Volume harus antara 1–200.", color=0xff0000))
    state = get_state(ctx.guild.id)
    state.volume = volume / 100
    if ctx.voice_client and ctx.voice_client.source:
        ctx.voice_client.source.volume = state.volume
    await ctx.send(embed=music_embed("🔊 Volume", f"Volume diatur ke **{volume}%**"))

@bot.command(name="loop", aliases=["l"])
async def cmd_loop(ctx):
    state = get_state(ctx.guild.id)
    state.loop = not state.loop
    status = "✅ Aktif" if state.loop else "❌ Nonaktif"
    await ctx.send(embed=music_embed("🔂 Loop Lagu", f"Loop lagu saat ini: **{status}**"))

@bot.command(name="loopqueue", aliases=["lq"])
async def cmd_loop_queue(ctx):
    state = get_state(ctx.guild.id)
    state.loop_queue = not state.loop_queue
    status = "✅ Aktif" if state.loop_queue else "❌ Nonaktif"
    await ctx.send(embed=music_embed("🔁 Loop Queue", f"Loop queue: **{status}**"))

@bot.command(name="shuffle", aliases=["sh"])
async def cmd_shuffle(ctx):
    import random
    state = get_state(ctx.guild.id)
    if len(state.queue) < 2:
        return await ctx.send(embed=music_embed("❌", "Queue terlalu sedikit untuk diacak.", color=0xff0000))
    lst = list(state.queue)
    random.shuffle(lst)
    state.queue = deque(lst)
    await ctx.send(embed=music_embed("🔀 Shuffle", "Queue telah diacak!"))

@bot.command(name="remove", aliases=["rm"])
async def cmd_remove(ctx, index: int):
    state = get_state(ctx.guild.id)
    if index < 1 or index > len(state.queue):
        return await ctx.send(embed=music_embed("❌", f"Nomor tidak valid. Queue punya {len(state.queue)} lagu.", color=0xff0000))
    lst = list(state.queue)
    removed = lst.pop(index - 1)
    state.queue = deque(lst)
    await ctx.send(embed=music_embed("🗑 Dihapus", f"**{removed['title']}** dihapus dari queue."))

@bot.command(name="clearqueue", aliases=["cq", "clear"])
async def cmd_clear(ctx):
    get_state(ctx.guild.id).queue.clear()
    await ctx.send(embed=music_embed("🧹 Queue Dikosongkan", "Semua lagu telah dihapus."))

@bot.command(name="search", aliases=["se"])
async def cmd_search(ctx, *, query: str):
    msg = await ctx.send(embed=music_embed("🔍 Mencari...", f"`{query}`", color=0xffa500))
    with yt_dlp.YoutubeDL({**YDL_OPTIONS, "noplaylist": True}) as ydl:
        loop = asyncio.get_event_loop()
        try:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False))
        except Exception:
            return await msg.edit(embed=music_embed("❌", "Pencarian gagal.", color=0xff0000))
    entries = info.get("entries", [])
    if not entries:
        return await msg.edit(embed=music_embed("❌", "Tidak ditemukan hasil.", color=0xff0000))
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"]
    desc = ""
    for i, e in enumerate(entries[:5]):
        desc += f"{emojis[i]} **[{e['title']}]({e.get('webpage_url','')})**  `{format_duration(e.get('duration',0))}`\n"
    await msg.edit(embed=music_embed("🔎 Hasil Pencarian", desc + "\nKetuk emoji untuk pilih atau ❌ batal."))
    for emoji in emojis[:len(entries)]:
        await msg.add_reaction(emoji)
    await msg.add_reaction("❌")
    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in emojis[:len(entries)] + ["❌"] and reaction.message.id == msg.id
    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=30.0, check=check)
    except asyncio.TimeoutError:
        return await msg.edit(embed=music_embed("⏱ Timeout", "Pencarian dibatalkan."))
    if str(reaction.emoji) == "❌":
        return await msg.edit(embed=music_embed("❌ Dibatalkan", "Pencarian dibatalkan."))
    idx = emojis.index(str(reaction.emoji))
    await cmd_play(ctx, query=entries[idx]["webpage_url"])

@bot.command(name="help", aliases=["h"])
async def cmd_help(ctx):
    e = discord.Embed(
        title="🎵 Music Bot — Daftar Perintah",
        description=f"Prefix: `{PREFIX}`  |  YouTube ✅  YouTube Music ✅  Spotify ✅",
        color=0x1DB954,
    )
    cmds = [
        ("🎵 Musik", [
            (f"`{PREFIX}play [lagu/url/spotify]`", "Putar lagu — support YouTube & Spotify"),
            (f"`{PREFIX}search [lagu]`", "Cari 5 lagu dan pilih emoji"),
            (f"`{PREFIX}skip`", "Skip lagu saat ini"),
            (f"`{PREFIX}pause`", "Pause lagu"),
            (f"`{PREFIX}resume`", "Lanjutkan lagu"),
            (f"`{PREFIX}stop`", "Stop & keluar dari VC"),
            (f"`{PREFIX}nowplaying`", "Info lagu yang diputar"),
        ]),
        ("📋 Queue", [
            (f"`{PREFIX}queue`", "Lihat daftar lagu"),
            (f"`{PREFIX}remove [no]`", "Hapus lagu dari queue"),
            (f"`{PREFIX}clearqueue`", "Kosongkan queue"),
            (f"`{PREFIX}shuffle`", "Acak queue"),
        ]),
        ("⚙️ Pengaturan", [
            (f"`{PREFIX}volume [1-200]`", "Atur volume"),
            (f"`{PREFIX}loop`", "Toggle loop lagu saat ini"),
            (f"`{PREFIX}loopqueue`", "Toggle loop seluruh queue"),
            (f"`{PREFIX}join`", "Bot masuk voice channel"),
        ]),
    ]
    for cat, items in cmds:
        e.add_field(name=cat, value="\n".join(f"{c} — {d}" for c, d in items), inline=False)
    e.set_footer(text="YouTube ✅  YouTube Music ✅  Spotify ✅")
    await ctx.send(embed=e)

# ─────────────────────────────────────────────
bot.run(TOKEN)
