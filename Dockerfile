FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and all its system dependencies via Playwright
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Data directory for persistent files (DB, users, secrets)
RUN mkdir -p /data

EXPOSE 6201

ENV PLAYWRIGHT_HEADLESS=true
ENV DATA_DIR=/data

CMD ["python", "run_web.py"]
