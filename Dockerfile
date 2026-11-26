FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUTO_START_DESK=true

COPY requirements.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements.txt

COPY crokbot ./crokbot
COPY dashboard.html crokbot_live_run.py ./

EXPOSE 8000

CMD ["sh", "-c", "uvicorn crokbot.dashboard.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
