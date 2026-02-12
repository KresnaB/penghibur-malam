# Instalasi Penghibur Malam di Server Armbian

Panduan lengkap untuk menjalankan bot musik Discord 24/7 di server Armbian.

---

## 1. Update Sistem

```bash
sudo apt update && sudo apt upgrade -y
```

## 2. Install Python & FFmpeg

```bash
sudo apt install python3 python3-pip python3-venv ffmpeg -y
```

Verifikasi:
```bash
python3 --version
ffmpeg -version
```

## 3. Clone Repository

```bash
cd ~
git clone https://github.com/KresnaB/penghibur-malam.git
cd penghibur-malam
```

## 4. Buat Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

## 5. Install Dependencies

```bash
pip install -r requirements.txt
```

## 6. Konfigurasi Token

```bash
nano .env
```

Isi file `.env`:
```
DISCORD_TOKEN=token_bot_kamu_disini
```

Simpan: `Ctrl+O` → `Enter` → `Ctrl+X`

## 7. Test Bot

```bash
python3 main.py
```

Jika muncul `🎵 Penghibur Malam sudah online!`, bot berjalan dengan benar. Tekan `Ctrl+C` untuk stop.

---

## 8. Jalankan 24/7 dengan systemd

Buat service file:
```bash
sudo nano /etc/systemd/system/penghibur-malam.service
```

Isi dengan (ganti `NAMA_USER` dengan username Armbian kamu, cek dengan perintah `whoami`):
```ini
[Unit]
Description=Penghibur Malam - Discord Music Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/penghibur-malam
ExecStart=/root/penghibur-malam/venv/bin/python3 main.py
Restart=always
RestartSec=10
Environment=PATH=/usr/bin:/usr/local/bin

[Install]
WantedBy=multi-user.target
```

Simpan: `Ctrl+O` → `Enter` → `Ctrl+X`

Aktifkan service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable penghibur-malam
sudo systemctl start penghibur-malam
```

## 9. Cek Status Bot

```bash
sudo systemctl status penghibur-malam
```

## Perintah Berguna

| Perintah | Fungsi |
|----------|--------|
| `sudo systemctl start penghibur-malam` | Jalankan bot |
| `sudo systemctl stop penghibur-malam` | Hentikan bot |
| `sudo systemctl restart penghibur-malam` | Restart bot |
| `sudo systemctl status penghibur-malam` | Cek status |
| `journalctl -u penghibur-malam -f` | Lihat log real-time |
| `journalctl -u penghibur-malam --since "1 hour ago"` | Log 1 jam terakhir |

## Update Bot

Jika ada perubahan kode di GitHub:
```bash
cd ~/penghibur-malam
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart penghibur-malam
```
