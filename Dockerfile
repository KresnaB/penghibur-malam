FROM node:20-bookworm-slim

ENV NODE_ENV=production \
    YTDLP_COOKIEFILE=/app/cookies.txt \
    PATH="/root/.local/bin:${PATH}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      python3 \
      python3-pip \
      ca-certificates \
      curl \
      tini && \
    pip3 install --break-system-packages --no-cache-dir \
      "yt-dlp @ git+https://github.com/yt-dlp/yt-dlp.git@master" \
      bgutil-ytdlp-pot-provider && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src ./src
COPY data ./data
COPY README.md ./

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "src/index.js"]
