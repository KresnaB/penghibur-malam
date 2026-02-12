# Instalasi Penghibur Malam di CasaOS

Panduan ini khusus untuk pengguna **CasaOS**. Kita akan menggunakan terminal CasaOS untuk menjalankan bot di dalam container Docker.

---

## 1. Buka Terminal
1. Login ke dashboard CasaOS.
2. Klik icon **Terminal** di pojok kiri atas (atau hubungkan via SSH/PuTTY).
3. Masuk sebagai `root` atau user dengan akses `sudo`.

## 2. Clone Repository
```bash
cd ~
git clone https://github.com/KresnaB/penghibur-malam.git
cd penghibur-malam
```

## 3. Siapkan Konfigurasi (.env)
```bash
nano .env
```
Isi dengan token bot kamu:
```
DISCORD_TOKEN=token_bot_kamu_disini
```
Simpan: `Ctrl+O` → `Enter` → `Ctrl+X`.

## 4. [PENTING] Upload cookies.txt
Agar bot tidak kena blokir YouTube (Error 403), kamu **WAJIB** upload file `cookies.txt` ke folder `~/penghibur-malam`.
- Kamu bisa pakai fitur **Files** di dashboard CasaOS.
- Navigasi ke `/root/penghibur-malam/` (atau `/home/user/penghibur-malam/` tergantung user terminal).
- Upload file `cookies.txt` (hasil export dari extension browser PC).

## 5. Jalankan dengan Docker
Kembali ke terminal, jalankan perintah ini:
```bash
docker-compose up -d --build
```
Tunggu proses build selesai.

## 6. Selesai!
Bot sekarang berjalan di background sebagai container Docker bernama `penghibur_malam`.

---

## Maintanance (Update & Restart)

### Cek Log
```bash
cd ~/penghibur-malam
docker-compose logs -f
```

### Update Bot (Jika ada fitur baru)
```bash
cd ~/penghibur-malam
git pull
docker-compose up -d --build
```

### Restart Bot
```bash
cd ~/penghibur-malam
docker-compose restart
```

### Stop Bot
```bash
cd ~/penghibur-malam
docker-compose down
```
