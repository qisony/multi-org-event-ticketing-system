FROM python:3.11-slim

# Установка системных зависимостей для pyzbar (zbar) и psycopg2 (libpq)
# libzbar0 - для считывания QR-кодов
# libpq-dev, gcc - для установки psycopg2
RUN apt-get update && apt-get install -y \
    libzbar0 \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем файлы зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]