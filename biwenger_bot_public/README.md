# ⚽ Biwenger AI Advisor - Mundial 2026

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat&logo=FastAPI&logoColor=white)](https://fastapi.tiangolo.com/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C.svg?style=flat&logo=PyTorch&logoColor=white)](https://pytorch.org/)
[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-yellow.svg)](https://huggingface.co/spaces)

Un consultor táctico y financiero inteligente siempre activo (Always-On) para la liga **Biwenger del Mundial 2026**. Combina un modelo de Machine Learning secuencial basado en **Transformers (PyTorch)** para predecir pujas de rivales, un sistema contable de saldo líquido (**Cash Tracker**), un motor de chat conversacional con **Gemini API** y una interfaz premium de diseño **Glassmorphic**.

---

## 📊 Arquitectura General del Sistema

El siguiente diagrama ilustra el flujo de datos entre las APIs externas, la persistencia en base de datos, el backend FastAPI y la interfaz web interactiva:

```mermaid
graph TD
    subgraph APIs Externas
        B_API["Biwenger API"]
        G_API["Gemini API (Google AI)"]
        W_API["Wikipedia & Tavily APIs"]
    end

    subgraph Backend Core (Python/FastAPI)
        EXT["Extractor (extractor.py)"]
        PRED["Predictor (predictor.py - PyTorch Transformer)"]
        GEM["Gemini Client (gemini_client.py)"]
        SERV["FastAPI Server (server.py)"]
        WORK["Background Sync Worker"]
    end

    subgraph Base de Datos
        DB[("Base de Datos (SQLite / PostgreSQL)")]
    end

    subgraph Frontend (Glassmorphic Web App)
        UI["UI (HTML5 / CSS3 / App.js)"]
    end

    %% Conexiones de flujo
    B_API -->|Descarga de datos| EXT
    EXT -->|Persiste transacciones| DB
    DB -->|Historial de fichajes| PRED
    PRED -->|Entrena secuencia temporal| PRED
    EXT -->|Saldos calculados| SERV
    PRED -->|Predicciones de pujas| SERV
    SERV -->|Lanza endpoints y UI| UI
    WORK -->|Sincroniza cada 10m| EXT
    WORK -->|Reentrena si hay fichajes| PRED
    
    UI -->|Pregunta del usuario| SERV
    SERV -->|Genera contexto y chat| GEM
    GEM -->|Rotador de Keys y reintentos| G_API
    GEM -->|Búsqueda (search_knowledge)| W_API
    G_API -->|Genera respuesta táctica| GEM
    GEM -->|Persiste historial| DB
    UI -->|Renderiza Markdown / Status| UI
```

---

## 🛠️ Pilares Tecnológicos

### 1. Cash Tracker (Algoritmo de Conciliación Contable)
Reconstruye el saldo líquido exacto de cada rival en la comunidad analizando cronológicamente todo el historial de transferencias, robos de cláusulas (`clause`), abonos y sanciones de la administración (`pay`) e intercambios directos (`exchange`).

### 2. Bid Predictor (PyTorch Transformer / RandomForest)
Modeliza el historial de pujas de cada jugador como una secuencia temporal. Entrena una red **Transformer** para predecir el porcentaje de sobrepuja (*premium*) esperado según el precio del jugador, variación del mercado, posición, equipo y liquidez del rival. Cuenta con fallback automático a `RandomForestRegressor`.

### 3. Gemini Client & Key Rotator
Genera reportes estratégicos estructurados e interactúa como chatbot conversacional. Integra un **rotador de hasta 20 API Keys en caliente** con algoritmo de reintento exponencial para mitigar el límite de cuota (429) de la API gratuita.

### 4. Search Grounding Híbrido (Wikipedia/Tavily)
Permite al bot consultar internet en segundo plano mediante **Function Calling** cuando detecta consultas sobre el estado real de los jugadores (lesiones, titularidad). Implementa un fallback automático sin claves a Wikipedia en Español y soporte para Tavily Search API.

### 5. FastAPI & Worker Asíncrono
Un daemon que despierta cada 10 minutos para sincronizar los datos de Biwenger de forma no bloqueante y realizar un **reentrenamiento condicional** (solo entrena la IA si hay nuevas transacciones). Soporta SQLite local y migración transparente a PostgreSQL (Neon DB / Supabase).

---

## 🚀 Instalación y Configuración

### 1. Clonar el repositorio
```bash[
git clone https://github.com/Soyzalo08/Biwenger-ai-bot.git
cd Biwenger-ai-bot
```

### 2. Instalar dependencias
Se recomienda utilizar un entorno virtual (venv):
```bash
python -m venv venv
source venv/Scripts/activate  # En Windows
pip install -r requirements.txt
```

### 3. Configurar variables de entorno
Crea un archivo `.env` en la raíz del proyecto tomando como plantilla las siguientes variables:
```env
# Credenciales de Biwenger (extraer de la consola del navegador / cookies)
BIWENGER_TOKEN=tu_token_jwt_aqui
BIWENGER_LEAGUE=id_de_tu_liga_aqui
BIWENGER_USER=id_de_tu_usuario_aqui

# API Keys de Gemini (puedes listar varias separadas por comas para rotar)
GEMINI_API_KEY=tu_api_key_principal_aqui
GEMINI_API_KEY_1=otra_api_key_aqui
GEMINI_MODEL=gemini-2.5-flash-lite

# Búsqueda Web en tiempo real (Opcional - Tavily API)
TAVILY_API_KEY=tu_clave_tavily_aqui

# Base de Datos PostgreSQL (Opcional - Dejar vacío para SQLite local)
DATABASE_URL=postgresql://usuario:contraseña@host:puerto/dbname?sslmode=require
```

### 4. Lanzar el Servidor Local
```bash
python main.py
```
Abre en tu navegador la dirección **`http://127.0.0.1:8000`** para acceder al portal web.

---

## 🎮 Guía de Uso de la Aplicación

Una vez que la aplicación esté corriendo en tu navegador, tienes a tu disposición las siguientes funciones clave:

### 1. El Panel de Control Lateral (Dashboard)
* **Estado del Sincronizador**: Muestra si hay un proceso de sincronización activo en segundo plano y cuándo fue la última actualización.
* **Saldos Estimados**: Visualiza una tarjeta rápida de cada rival con su presupuesto líquido estimado en tiempo real por el **Cash Tracker**.
* **Tu Equipo**: Resumen rápido de tus puntos, valor de plantilla y saldo actual.

### 2. Pestaña 💬 "Chat Consultor"
* Abre nuevas conversaciones utilizando el botón **`+ Nuevo Chat`** en la barra lateral.
* El bot cuenta con memoria conversacional. Pregúntale cosas como:
  * *¿A quién me recomiendas fichar hoy del mercado?*
  * *¿Cuál es el saldo líquido estimado de Fran_pm?*
  * *¿Cuánto debería pujar por Courtois para ganarle a mis rivales sin sobrepagar?*
  * *¿Está lesionado o es suplente Nico Williams en su selección real?* (El bot buscará automáticamente en Wikipedia/Tavily si no tiene la información).

### 3. Pestaña 📊 "Operaciones de Mercado"
* Cambia a esta pestaña en la parte superior del chat para ver un feed limpio y ordenado cronológicamente de todos los movimientos de tu liga.
* Diferencia visualmente las operaciones mediante etiquetas de colores: **Compras de Mercado**, **Transferencias entre rivales**, **Pago de Cláusulas**, **Intercambios** y **Abonos/Sanciones** administrativos.

### 4. ⚡ Sincronización Manual
* El daemon del servidor se conecta y actualiza los datos automáticamente cada **10 minutos**.
* Si acabas de hacer un movimiento en la app de Biwenger y no quieres esperar, pulsa el botón **`🔄 Sincronizar Ahora`** en la esquina superior derecha del panel web. Forzará una descarga inmediata y reentrenará los modelos de Machine Learning al instante si se detecta un nuevo fichaje.

---

### 5. 🔑 Cómo Obtener tus Credenciales de Biwenger

Para conectar el bot a tu cuenta y tu liga de Biwenger, necesitas extraer tres valores:

1. **`BIWENGER_TOKEN` (Token JWT)**:
   - Inicia sesión en [biwenger.as.com](https://biwenger.as.com/).
   - Abre las herramientas de desarrollador en tu navegador (pulsa `F12` o clic derecho -> *Inspeccionar*).
   - Ve a la pestaña **Application** (o **Almacenamiento** / **Storage**).
   - En el menú lateral izquierdo, despliega **Local Storage** y haz clic en `https://biwenger.as.com`.
   - Busca la clave llamada **`token`** y copia su valor (es un texto largo que suele empezar por `eyJ0eX...`).

2. **`BIWENGER_LEAGUE` (ID de la Liga)**:
   - Mira la barra de direcciones de tu navegador cuando estés dentro de tu liga en la web de Biwenger. La URL tiene esta estructura:
     `https://biwenger.as.com/league/1234567/`
   - El número **`1234567`** es tu ID de liga.

3. **`BIWENGER_USER` (ID de tu Usuario)**:
   - En la pestaña **Local Storage** anterior de las herramientas de desarrollador, busca la clave llamada **`user_id`** y copia su valor numérico.

---

## 🐳 Despliegue en Hugging Face Spaces (Docker)

El repositorio incluye un `Dockerfile` optimizado para desplegar en Hugging Face Spaces de manera gratuita:

1. Crea un nuevo **Space** en Hugging Face y selecciona **Docker** como SDK (plantilla `Blank`).
2. Configura los secretos del Space en la pestaña **Settings** (añade `BIWENGER_TOKEN`, `GEMINI_API_KEY`, etc. como Secrets).
3. Sube todos los archivos del repositorio.
4. El contenedor se construirá y expondrá automáticamente en el puerto `7860`.
