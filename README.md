# 🎵 Omnia Music Bot

Bot Discord pemutar musik tangguh dari YouTube dengan UI interaktif dan slash commands.

## ⚙️ Fitur

| Command | Deskripsi |
|---------|-----------|
| `/play <query>` | Putar lagu (YouTube URL, Playlist, atau keyword) |
| `/skip` | Skip lagu saat ini |
| `/seek <timestamp>` | Loncat ke posisi tertentu di lagu saat ini (detik, `mm:ss`, atau `hh:mm:ss`) |
| `/stop` | Stop pemutaran dan kosongkan queue, bot tetap di voice |
| `/sleep <durasi>` | Atur timer tidur, misalnya `30m`, `1h30m`, atau `off` |
| `/queue` | Lihat antrian lagu |
| `/move <from> <to>` | Pindahkan lagu di queue |
| `/nowplaying` | Info lagu yang diputar |
| `/loop <off\|single\|queue>` | Atur mode loop |
| `/autoplay [mode]` | Atur mode autoplay (Youtube/Custom1/Custom2) |
| `/lyrics [query]` | Cari lirik lagu (Lrclib/Genius) |
| `/status` | Tampilkan status bot |
| `/playlistcopy <url> [name]` | Copy playlist YouTube dan simpan sebagai playlist server (maks 50 lagu/playlist) |
| `/playlist` | Tampilkan daftar playlist server tanpa menu interaktif |
| `/playlistplay` | Tampilkan daftar playlist server dan pilih dari dropdown untuk diputar / masuk ke queue |
| `/playlistdelete` | Tampilkan daftar playlist server dalam dropdown dan hapus playlist yang dipilih |
| `/help` | Tampilkan daftar command |

### 🔧 Fitur Otomatis
- **Auto disconnect** saat idle 3 menit
- **Auto disconnect** saat sendirian di VC
- **Sleep timer** untuk stop dan disconnect otomatis setelah durasi tertentu
- **Auto clean chat** untuk respons status yang sementara
- **Seamless transitions** dengan handoff cepat dan smoothing audio ringan
- **Playback recovery** yang mencoba ulang stream saat terjadi gangguan sementara
- **Autoplay** memutar lagu terkait otomatis secara cerdas. Tersedia mode YouTube (dasar), Custom 1 (relevan), dan Custom 2 (eksploratif).
- **Playlist limit** maksimal 50 lagu per request
- **Fast first play** optimasi agar lagu pertama lebih cepat terdengar
- **Lyrics** cari lirik lagu via Lrclib & Genius (Race Strategy)
## 🔑 Persiapan Bot Discord
Sebelum menginstal bot di PC/Server Anda, Anda harus membuat bot di Discord Developer Portal terlebih dahulu.
1. Buka [Discord Developer Portal](https://discord.com/developers/applications).
2. Buat aplikasi baru ("New Application") dan beri nama (misal: "Omnia Music").
3. Buka tab **Bot**, lalu klik **Reset Token** dan simpan token tersebut (INI SANGAT RAHASIA).
4. Gulir ke bawah pada tab Bot, pastikan mengaktifkan `Message Content Intent`, `Server Members Intent`, dan `Presence Intent`.
5. Buka tab **OAuth2 > URL Generator**.
6. Centang `bot` dan `applications.commands`. Beri permission `Administrator` (atau sekurang-kurangnya permission kirim/baca pesan dan gabung/bicara di Voice Channel).
7. Salin URL di bagian bawah halaman dan buka di browser untuk mengundang bot ke server Discord Anda.

## 🎤 Persiapan Genius API (Lirik Lagu)
Layanan lirik membutuhkan Genius token agar pencarian lebih akurat.
1. Buka [Genius API Client](https://genius.com/api-clients).
2. Buat "New API Client".
3. Klik **Generate Access Token** dan simpan kredensial tersebut.

## 📦 Panduan Instalasi

Pilih metode instalasi yang paling sesuai dengan sistem eksosistem Anda:

### 🪟 Windows (Local Desktop)
Metode termudah untuk dijalankan di PC Windows.
1. Install **Python** & **FFmpeg** (pastikan FFmpeg sudah ditambahkan ke System Environment PATH).
2. Install requirements: `pip install -r requirements.txt`
3. Edit file `.env` dengan token Discord dan Genius Anda:
```env
DISCORD_TOKEN=token_bot_discord_kamu
GENIUS_ACCESS_TOKEN=token_genius_api_kamu
```
4. Klik dua kali pada file **`run_bot.bat`** untuk menjalankan bot dengan interface command prompt yang rapi.

### 🐧 Linux / Armbian Server
Direkomendasikan apabila Anda menjalankan bot ini di VPS atau Private Server (misal baremetal Armbian). Termasuk langkah setup `systemd` agar bot beroperasi 24/7.
👉 **[Pergi ke Panduan Instalasi Linux](INSTALL_LINUX.md)**

### 🐳 Docker / CasaOS
Metode terbaik untuk isolasi server (Container) dan *deployment* 1 klik yang bersih, sangat cocok untuk portainer / CasaOS.
👉 **[Pergi ke Panduan Instalasi Docker](INSTALL_DOCKER.md)**

---

## 🍪 Troubleshooting YouTube Error (Error 403 / Sign in to confirm)
Jika bot tidak bisa memutar lagu karena diblokir YouTube (seperti IP terkena *ban* atau muncul peringatan usia/Sign in), Anda bisa memakai fitur `cookies.txt`:
1. Ekspor *cookies* dari akun YouTube yang telah login di PC Anda menggunakan ekstensi semacam **Get cookies.txt LOCALLY**.
2. Simpan hasilnya dengan nama `cookies.txt`.
3. Letakkan file ini **tepat di *root* folder bot** (sejajar dengan file `main.py` dan `run_bot.bat`).
4. yt-dlp akan otomatis mendeteksi file `cookies.txt` ini dan menggunakannya untuk menembus *error auth* tanpa perlu modifikasi *source code* lagi.

## 🧠 Debug Memori
Kalau RAM naik perlahan saat musik terus diputar, aktifkan log memori untuk melihat apakah kenaikan datang dari Python heap, jumlah task, atau state player:
```env
DEBUG_MEMORY=1
DEBUG_MEMORY_INTERVAL=600
```

Saat aktif, bot akan mencatat:
- RSS proses
- penggunaan heap Python dari `tracemalloc`
- jumlah task aktif
- ukuran queue, pesan lirik tersimpan, dan state per guild

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
├── data/
│   └── playlists.json   # Pelajari playlist tersimpan (Persisten)
└── utils/
    ├── embed_builder.py     # Rich embeds
    ├── genius_lyrics.py     # Genius lyrics fetcher
    ├── lyrics_service.py    # Lrclib/Genius race strategy
    ├── now_playing_view.py  # Player buttons
    └── playlist_store.py    # JSON storage for shared server playlists
```

## 📋 Teknologi
- **discord.py** 2.x (slash commands)
- **yt-dlp** (YouTube extraction)
- **FFmpeg** (audio streaming)
- **PyNaCl** (voice encryption)
- **lyricsgenius** (Genius API lyrics)
- **Docker** (containerization)

## 📄 Lisensi
[Omnia Music Bot - Non-Commercial License](LICENSE)

Proyek ini gratis digunakan untuk kebutuhan pribadi, komunitas kecil, maupun edukasi secara terbuka. Namun **tidak diizinkan** untuk diperjualbelikan, atau digunakan di dalam produk/layanan komersial lainnya. Silakan baca file `LICENSE` secara lengkap untuk detail hak cipta.
