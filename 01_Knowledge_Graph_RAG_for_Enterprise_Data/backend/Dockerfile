FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# settings.py resolves .env from Path(__file__).parents[2], which is
# /app here, so mount or copy the file to /app/.env. The defaults in
# settings.py already match docker-compose, so the app boots without it.
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Bind 0.0.0.0, not localhost: a container binding loopback is
# unreachable from outside it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
