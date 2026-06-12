import os
import sys

def load_env(env_path=".env"):
    """
    Carga variables de entorno desde un archivo .env si existe,
    sin necesidad de depender de librerías de terceros como python-dotenv.
    """
    # Buscamos en el directorio del script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    full_env_path = os.path.join(script_dir, env_path)
    
    if os.path.exists(full_env_path):
        with open(full_env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    # Eliminamos posibles comillas de los valores
                    val = val.strip().strip('"').strip("'")
                    os.environ[key.strip()] = val
    elif os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    os.environ[key.strip()] = val

# Cargar configuración al importar el módulo
load_env()

# Credenciales de Biwenger
BIWENGER_TOKEN = os.environ.get("BIWENGER_TOKEN")
BIWENGER_LEAGUE = os.environ.get("BIWENGER_LEAGUE")
BIWENGER_USER = os.environ.get("BIWENGER_USER")

# API Key y Modelo de Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def validate_config():
    """
    Valida que las credenciales mínimas estén configuradas.
    """
    missing = []
    if not BIWENGER_TOKEN:
        missing.append("BIWENGER_TOKEN")
    if not BIWENGER_LEAGUE:
        missing.append("BIWENGER_LEAGUE")
    if not BIWENGER_USER:
        missing.append("BIWENGER_USER")
        
    if missing:
        print(f"Error crítico: Faltan las siguientes variables en el archivo .env o en el entorno: {', '.join(missing)}")
        print("Por favor, asegúrate de configurar tu archivo .env antes de ejecutar el bot.")
        sys.exit(1)
        
    if not GEMINI_API_KEY:
        print("Advertencia: No se ha encontrado GEMINI_API_KEY.")
        print("El módulo de extracción de datos de Biwenger funcionará, pero el análisis con Gemini fallará.")
        print("Por favor, configura tu GEMINI_API_KEY en el archivo .env o en las variables de entorno.")
