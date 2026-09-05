FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/
COPY reports/ ./reports/

ENV PYTHONPATH=/app/backend

CMD ["sh", "-c", "cd /app/backend && python -m app.seed || true; cd /app/backend && uvicorn app.main:app --host 0.0.0.0 --port 8000"]