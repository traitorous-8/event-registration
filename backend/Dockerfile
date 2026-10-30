FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["sh", "-c", "cd /app/backend && alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
