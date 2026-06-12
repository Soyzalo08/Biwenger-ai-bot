import config
import sys
import uvicorn

def main():
    print("======================================================================")
    print("  Bot Consultor de Biwenger - Servidor Web & Chatbot Always-On")
    print("======================================================================")
    
    # 1. Validar configuración básica de Biwenger en .env
    config.validate_config()
    
    # 2. Iniciar el servidor web Uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    print(f"[*] Levantando servidor local en http://{host}:{port} ...")
    try:
        # Servir la aplicación FastAPI 'app' ubicada en 'server.py'
        uvicorn.run("server:app", host=host, port=port, reload=False)
    except KeyboardInterrupt:
        print("\n[+] Servidor detenido por el usuario.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[Error Crítico] No se pudo iniciar el servidor web: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
