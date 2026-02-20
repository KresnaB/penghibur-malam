# 🎵 Omnia Music Bot

Bot Discord pemutar musik tangguh dari YouTube dengan UI interaktif dan slash commands.

## ⚙️ Fitur

| Command | Deskripsi |
|---------|-----------|
| `/play <query>` | Putar lagu (YouTube URL, Playlist, atau keyword) |
| `/skip` | Skip lagu saat ini |
| `/stop` | Stop dan disconnect |
| `/queue` | Lihat antrian lagu |
| `/move <from> <to>` | Pindahkan lagu di queue |
| `/nowplaying` | Info lagu yang diputar |
| `/loop <off\|single\|queue>` | Atur mode loop |
| `/autoplay` | Toggle autoplay rekomendasi |
| `/lyrics [query]` | Cari lirik lagu (Lrclib/Genius) |
| `/status` | Tampilkan status bot |
| `/help` | Tampilkan daftar command |

### 🔧 Fitur Otomatis
- **Auto disconnect** saat idle 3 menit
- **Auto disconnect** saat sendirian di VC
- **Autoplay** memutar lagu terkait otomatis jika diaktifkan (tanpa duplikat)
- **Playlist limit** maksimal 50 lagu per request
- **Fast first play** optimasi agar lagu pertama lebih cepat terdengar
- **Lyrics** cari lirik lagu via Lrclib & Genius (Race Strategy)

## 📦 Panduan Instalasi

Pilih metode instalasi yang paling sesuai dengan sistem eksosistem Anda:

### 🪟 Windows (Local Desktop)
Metode termudah untuk dijalankan di PC Windows.
1. Install **Python** & **FFmpeg** (pastikan FFmpeg sudah ditambahkan ke System Environment PATH).
2. Install requirements: `pip install -r requirements.txt`
3. Edit file `.env` dengan token Discord Anda.
4. Klik dua kali pada file **`run_bot.bat`** untuk menjalankan bot dengan interface command prompt yang rapi.

### 🐧 Linux / Armbian Server
Direkomendasikan apabila Anda menjalankan bot ini di VPS atau Private Server (misal baremetal Armbian). Termasuk langkah setup `systemd` agar bot beroperasi 24/7.
👉 **[Pergi ke Panduan Instalasi Linux](INSTALL_LINUX.md)**

### 🐳 Docker / CasaOS
Metode terbaik untuk isolasi server (Container) dan *deployment* 1 klik yang bersih, sangat cocok untuk portainer / CasaOS.
👉 **[Pergi ke Panduan Instalasi Docker](INSTALL_DOCKER.md)**

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
