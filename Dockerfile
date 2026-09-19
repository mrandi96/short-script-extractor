FROM python:3.11-slim

# Install system dependencies (ffmpeg is strictly required by yt-dlp for audio conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose default port
EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000

CMD ["python", "main.py"]
