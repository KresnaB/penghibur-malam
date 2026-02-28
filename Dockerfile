# Gunakan Python 3.11-slim (ringan & modern)
FROM python:3.11-slim

# Install dependencies sistem (ffmpeg, git, nodejs for PO Token generator)
RUN apt-get update && \
    apt-get install -y ffmpeg git curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/* && \
    node --version && echo "Node.js installed OK"

# Set working directory
WORKDIR /app

# Copy requirements dan install
COPY requirements.txt .

# Install yt-dlp first (from git master)
RUN pip install --no-cache-dir "yt-dlp @ git+https://github.com/yt-dlp/yt-dlp.git@master"

# Install remaining requirements
RUN pip install --no-cache-dir -r requirements.txt

# Install PO Token plugin explicitly and verify
RUN pip install --no-cache-dir --force-reinstall bgutil-ytdlp-pot-provider && \
    python -c "import bgutil_ytdlp_pot_provider; print('PO Token plugin installed successfully')" && \
    ls -la /usr/local/lib/python3.11/site-packages/yt_dlp_plugins/ || true

# Copy seluruh kode project
COPY . .

# Command untuk menjalankan bot
CMD ["python", "main.py"]
