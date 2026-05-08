FROM python:3.12-slim

LABEL maintainer="First Reply Tajweed"
LABEL description="Telegram auto-reply bot with control bot"

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py control_bot.py main.py persistent_state.py \
     scheduler.py startup_checks.py state.py userbot.py ./

# Create sessions directory (will be overridden by volume mount)
RUN mkdir -p /app/sessions

# Volume for persistent session storage
VOLUME ["/app/sessions"]

# Healthcheck: verify process is alive every 60s
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, signal; pid=1; os.kill(pid, 0)" || exit 1

# Run
CMD ["python", "main.py"]
