FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Seed on first start only; an existing database is left alone.
CMD ["sh", "-c", "python -m app.seed || true; uvicorn app.main:app --host 0.0.0.0 --port 8000"]
