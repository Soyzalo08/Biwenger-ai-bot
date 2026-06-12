FROM python:3.10-slim

# Instalar dependencias necesarias para compilar psycopg2
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

# Configurar variables de entorno para que el contenedor use el puerto y host correctos
ENV PORT=7860
ENV HOST=0.0.0.0

# Exponer el puerto que espera Hugging Face Spaces (7860)
EXPOSE 7860

# Iniciar la aplicación
CMD ["python", "main.py"]
