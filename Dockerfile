# Gunakan Python 3.11-slim (ringan & modern)
FROM python:3.11-slim

# Install dependencies sistem (ffmpeg & git)
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh kode project
COPY . .

# Command untuk menjalankan bot
CMD ["python", "main.py"]
