FROM python:3.11-slim

# Tizim kutubxonalari
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Avval requirements — Docker cache uchun
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Qolgan fayllar
COPY . .

CMD ["python", "bot.py"]
