FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Platforms inject $PORT; default to 8800 for local `docker run`.
ENV PORT=8800
EXPOSE 8800

# The dashboard. Committed demo data (receipts/equity/abstentions/x402) renders
# immediately; live receipts append into the same files during the trading window.
CMD ["sh", "-c", "uvicorn agent.web:app --host 0.0.0.0 --port ${PORT:-8800}"]
