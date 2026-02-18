# 🎵 Music Bot — Penghibur Malam

Bot Discord pemutar musik dari YouTube dengan slash commands.

## ⚙️ Fitur

| Command | Deskripsi |
|---------|-----------|
| `/play <query>` | Putar lagu (YouTube URL, Playlist, atau keyword) |
| `/skip` | Skip lagu saat ini |
| `/stop` | Stop dan disconnect |
| `/queue` | Lihat antrian lagu |
| `/nowplaying` | Info lagu yang diputar |
| `/loop <off\|single\|queue>` | Atur mode loop |
| `/autoplay` | Toggle autoplay rekomendasi |
| `/lyrics [query]` | Cari lirik lagu dari Genius |
| `/status` | Tampilkan status bot |
| `/help` | Tampilkan daftar command |

### 🔧 Fitur Otomatis
- **Auto disconnect** saat idle 3 menit
- **Auto disconnect** saat sendirian di VC
- **Autoplay** memutar lagu terkait otomatis jika diaktifkan (tanpa duplikat)
- **Playlist limit** maksimal 50 lagu per request
- **Fast first play** optimasi agar lagu pertama lebih cepat terdengar
- **Lyrics** cari lirik lagu via Genius API (tombol 🎤 di Now Playing + `/lyrics`)

## 📦 Instalasi

### 1. Install FFmpeg
- **Windows**: Download dari [ffmpeg.org](https://ffmpeg.org/download.html), tambahkan ke PATH
- **Linux**: `sudo apt install ffmpeg`
- **Mac**: `brew install ffmpeg`

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Konfigurasi
Edit file `.env`:
```
DISCORD_TOKEN=token_bot_discord_kamu
GENIUS_ACCESS_TOKEN=token_genius_api_kamu
```

### 4. Jalankan
```bash
python main.py
```

### 5. Jalankan dengan Docker
```bash
docker-compose up -d --build
```

## 🏗️ Struktur Project

```
penghibur-malam/
├── main.py              # Entry point
├── Dockerfile           # Docker image
├── docker-compose.yml   # Docker Compose
├── cogs/
│   └── music.py         # Slash commands
├── core/
│   ├── music_player.py  # Player engine
│   ├── queue_manager.py # Queue system
│   └── ytdl_source.py   # yt-dlp wrapper
└── utils/
    ├── embed_builder.py   # Rich embeds
    ├── genius_lyrics.py   # Genius lyrics fetcher
    └── now_playing_view.py # Player buttons
```

## 📋 Teknologi
- **discord.py** 2.x (slash commands)
- **yt-dlp** (YouTube extraction)
- **FFmpeg** (audio streaming)
- **PyNaCl** (voice encryption)
- **lyricsgenius** (Genius API lyrics)
- **Docker** (containerization)
