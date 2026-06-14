# 🎵 Discord Music Bot

Support: YouTube ✅ YouTube Music ✅ Spotify ✅

## File yang dibutuhkan
- `bot.py` — kode utama bot
- `requirements.txt` — library yang dibutuhkan
- `Procfile` — untuk Railway agar tahu cara jalankan bot

---

## Cara Deploy ke Railway (dari HP)

### 1. Buat Bot Discord
1. Buka discord.com/developers/applications
2. New Application → beri nama
3. Tab Bot → Add Bot
4. Aktifkan: Presence Intent, Server Members Intent, Message Content Intent
5. Reset Token → copy token
6. OAuth2 → URL Generator → scope: bot → permission: Connect, Speak, Send Messages, Read Message History, Add Reactions, Embed Links → invite bot ke server

### 2. Buat Akun GitHub
1. Daftar di github.com
2. New Repository → nama: music-bot → Public → Create

### 3. Upload File ke GitHub
Upload 3 file ini satu per satu lewat tombol "Add file" → "Create new file":
- bot.py
- requirements.txt
- Procfile (isi: worker: python bot.py)

### 4. Deploy ke Railway
1. Buka railway.app → login pakai GitHub
2. New Project → Deploy from GitHub repo → pilih music-bot
3. Masuk tab Variables → tambahkan:

| Key            | Value                  |
|----------------|------------------------|
| TOKEN          | token bot Discord      |
| SPOTIFY_ID     | Client ID Spotify      |
| SPOTIFY_SECRET | Client Secret Spotify  |

4. Deploy → tunggu status Active ✅

---

## Cara Dapat Spotify API (Gratis)
1. Buka developer.spotify.com → login
2. Create App → isi nama bebas → centang Web API → Save
3. Masuk Settings → copy Client ID dan Client Secret

> Spotify API opsional. Tanpanya bot tetap bisa YouTube & YouTube Music.

---

## Daftar Perintah

| Perintah | Alias | Fungsi |
|---|---|---|
| `!play [lagu/url]` | `!p` | Putar lagu — YouTube/YT Music/Spotify |
| `!search [lagu]` | `!se` | Cari 5 lagu & pilih pakai emoji |
| `!skip` | `!s` | Skip lagu saat ini |
| `!pause` | — | Pause lagu |
| `!resume` | `!r` | Lanjutkan lagu |
| `!stop` | `!dc` | Stop & keluar dari VC |
| `!nowplaying` | `!np` | Info lagu yang diputar |
| `!queue` | `!q` | Lihat daftar lagu |
| `!remove [no]` | `!rm` | Hapus lagu dari queue |
| `!clearqueue` | `!cq` | Kosongkan queue |
| `!shuffle` | `!sh` | Acak queue |
| `!volume [1-200]` | `!vol` | Atur volume |
| `!loop` | `!l` | Toggle loop lagu |
| `!loopqueue` | `!lq` | Toggle loop queue |
| `!join` | `!j` | Bot masuk voice channel |
| `!help` | `!h` | Tampilkan bantuan |
