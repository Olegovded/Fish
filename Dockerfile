# Универсальный образ для любого хостинга (Railway, Fly, свой VPS и т.п.).
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Приложение слушает $PORT (или 8080 по умолчанию).
ENV WEB_HOST=0.0.0.0
EXPOSE 8080
CMD ["python", "-m", "bot.main"]
