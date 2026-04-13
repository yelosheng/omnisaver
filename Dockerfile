FROM mcr.microsoft.com/playwright/python:v1.51.0-jammy

WORKDIR /app

# Install system dependencies: ffmpeg (video thumbnails) + curl (yt-dlp install) + git
# Note: nodejs/npm already provided by playwright base image
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install xreach-cli (Twitter thread fetching) and mcporter (XiaoHongShu)
RUN npm install -g xreach-cli mcporter

# Install yt-dlp (video downloads for Twitter/X and XiaoHongShu)
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod +x /usr/local/bin/yt-dlp

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install wechat-article-for-ai (WeChat article scraping)
RUN git clone https://github.com/Panniantong/wechat-article-for-ai.git /root/.agent-reach/tools/wechat-article-for-ai \
    && pip install --no-cache-dir -r /root/.agent-reach/tools/wechat-article-for-ai/requirements.txt \
    && python -m camoufox fetch

# Copy application code
COPY . .

# Data directory for persistent files (DB, users, secrets)
RUN mkdir -p /data

EXPOSE 6201

ENV PLAYWRIGHT_HEADLESS=true
ENV DATA_DIR=/data

CMD ["python", "run_web.py"]
