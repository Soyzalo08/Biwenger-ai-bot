import google.generativeai as genai
import config
import json
import re
import time
import os
import requests

def search_knowledge(query: str) -> str:
    """
    Busca información en tiempo real sobre alineaciones, lesiones, titularidad de jugadores,
    fichajes y estado de selecciones en el Mundial 2026 en internet o Wikipedia.
    
    Args:
        query: La consulta de búsqueda (ej. 'Kylian Mbappe seleccion francesa titular').
        
    Returns:
        Un resumen de los resultados de búsqueda encontrados.
    """
    print(f"\n[INFO] Gemini llamó a la herramienta `search_knowledge` con la consulta: '{query}'")
    tavily_key = os.environ.get("TAVILY_API_KEY") or ""
    
    # 1. Intentar Tavily si está configurada
    if tavily_key and not tavily_key.startswith("tu_"):
        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": tavily_key,
                "query": query,
                "max_results": 3,
                "search_depth": "light"
            }
            response = requests.post(url, json=payload, timeout=8)
            if response.status_code == 200:
                results = response.json().get("results", [])
                if results:
                    formatted = []
                    for r in results:
                        formatted.append(f"Título: {r.get('title')}\nContenido: {r.get('content')}\nLink: {r.get('url')}\n")
                    print(f"[+] `search_knowledge` completado exitosamente usando Tavily API (resultados: {len(results)})")
                    return "\n".join(formatted)
        except Exception as e:
            print(f"[!] Falló la búsqueda con Tavily API: {e}")
            
    # 2. Fallback a Wikipedia en Español
    print("[+] Usando fallback de Wikipedia para buscar información...")
    
    # Limpieza de consulta para Wikipedia (elimina palabras conversacionales y acentos)
    cleaned = re.sub(r"[¿\?¡\!¡\.,;:\(\)\-\"\']", "", query)
    stop_words = {
        "es", "titular", "suplente", "lesionado", "juega", "en", "con", "la", "el", "de", "del", 
        "un", "una", "y", "o", "que", "quien", "quienes", "como", "para", "por", "seleccion", 
        "futbol", "convocado", "esta", "lesion", "lesiones", "alineacion", "alineaciones", 
        "partido", "partidos", "proximo", "actual", "actuales", "sobre", "delantero", "portero", 
        "defensa", "centrocampista", "medio", "extremo", "quien", "saber", "si"
    }
    
    words = []
    for w in cleaned.split():
        w_clean = w.lower()
        w_clean = w_clean.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        if w_clean not in stop_words:
            words.append(w)
            
    wiki_query = " ".join(words) if words else cleaned
    print(f"[+] Consulta optimizada para Wikipedia: '{wiki_query}'")
    
    try:
        search_url = "https://es.wikipedia.org/w/api.php"
        search_params = {
            "action": "opensearch",
            "search": wiki_query,
            "limit": 2,
            "namespace": 0,
            "format": "json"
        }
        headers = {"User-Agent": "BiwengerBot/1.0"}
        search_res = requests.get(search_url, params=search_params, headers=headers, timeout=8)
        
        if search_res.status_code == 200:
            titles = search_res.json()[1]
            if titles:
                summaries = []
                for title in titles:
                    title_url = title.replace(" ", "_")
                    sum_url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{title_url}"
                    sum_res = requests.get(sum_url, headers=headers, timeout=8)
                    if sum_res.status_code == 200:
                        sum_data = sum_res.json()
                        extract = sum_data.get("extract", "")
                        if extract:
                            summaries.append(f"Wikipedia - {title}:\n{extract}\n")
                if summaries:
                    print(f"[+] `search_knowledge` completado exitosamente usando Wikipedia (páginas: {len(summaries)})")
                    return "\n".join(summaries)
    except Exception as e:
        print(f"[!] Falló la búsqueda con Wikipedia: {e}")
        
    return "No se pudo obtener información adicional de internet para esta consulta."

class GeminiClient:
    def __init__(self, api_key=None, model_name="gemini-1.5-flash"):
        self.model_name = model_name
        self.current_key_idx = 0
        
        # Cargar todas las claves disponibles
        self.api_keys = []
        
        # 1. Intentar desde GEMINI_API_KEY principal (soporta comas)
        main_key = api_key or config.GEMINI_API_KEY
        if main_key:
            for k in main_key.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in self.api_keys and not k_clean.startswith("tu_"):
                    self.api_keys.append(k_clean)
                    
        # 2. Buscar claves enumeradas GEMINI_API_KEY_1 hasta GEMINI_API_KEY_20
        for i in range(1, 21):
            env_key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if env_key:
                k_clean = env_key.strip()
                if k_clean and k_clean not in self.api_keys and not k_clean.startswith("tu_"):
                    self.api_keys.append(k_clean)
                    
        # Configurar la primera clave activa
        if self.api_keys:
            genai.configure(api_key=self.api_keys[0])
            print(f"[+] Rotador: Cargadas {len(self.api_keys)} claves API de Gemini válidas para rotar.")
        else:
            print("[!] Rotador: No se encontraron claves API de Gemini configuradas.")

    def _get_active_key(self):
        if not self.api_keys:
            raise ValueError("No se han configurado claves GEMINI_API_KEY válidas en el archivo .env.")
        return self.api_keys[self.current_key_idx]

    def _rotate_key(self):
        if len(self.api_keys) > 1:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
            active_key = self._get_active_key()
            genai.configure(api_key=active_key)
            print(f"\n[+] Rotador: Cuota excedida. Rotando instantáneamente a la clave API #{self.current_key_idx + 1}...")
        else:
            print("\n[!] Rotador: Solo hay 1 clave configurada. No es posible rotar.")

    def _compress_league_data(self, data):
        """
        Reduce radicalmente el tamaño del JSON de la liga (eliminando arrays de fitness,
        puntos históricos e IDs internos redundantes) para ahorrar más del 70% de tokens,
        evitando superar los límites de cuota (TPM) en la API gratuita.
        """
        if not data:
            return data
            
        compressed = {}
        
        # 1. Comprimir mi equipo
        if "my_team" in data:
            my_team = data["my_team"]
            compressed["my_team"] = {
                "name": my_team.get("name"),
                "balance": my_team.get("balance"),
                "team_value": my_team.get("team_value"),
                "points": my_team.get("points"),
                "players": [
                    {
                        "name": p.get("name"),
                        "position": p.get("position"),
                        "price": p.get("price"),
                        "points": p.get("points"),
                        "status": p.get("status")
                    } for p in my_team.get("players", [])
                ]
            }
            
        # 2. Comprimir mercado y predicciones de pujas
        if "market" in data:
            compressed["market"] = []
            for p in data["market"]:
                bids = {}
                for r_name, b_info in p.get("rivals_predicted_bids", {}).items():
                    bids[r_name] = {
                        "overbid_pct": b_info.get("predicted_overbid_pct"),
                        "bid_price": b_info.get("predicted_bid_price")
                    }
                compressed["market"].append({
                    "name": p.get("name"),
                    "team": p.get("team"),
                    "position": p.get("position"),
                    "price": p.get("price"),
                    "inc": p.get("priceIncrement"),
                    "seller": p.get("seller"),
                    "predicted_bids": bids
                })
                
        # 3. Comprimir rivales
        if "rivals" in data:
            compressed["rivals"] = []
            for r in data["rivals"]:
                compressed["rivals"].append({
                    "name": r.get("name"),
                    "points": r.get("points"),
                    "estimated_balance": r.get("estimated_balance"),
                    "team_value": r.get("team_value"),
                    "players": [
                        {
                            "name": p.get("name"),
                            "position": p.get("position"),
                            "price": p.get("price"),
                            "points": p.get("points")
                        } for p in r.get("players", [])
                    ]
                })
                
        compressed["timestamp"] = data.get("timestamp")
        return compressed

    def analyze_league_data(self, data):
        """
        Envía los datos comprimidos de la liga a Gemini y devuelve el reporte estratégico.
        """
        if not self.api_keys:
            raise ValueError("No hay claves API de Gemini válidas cargadas.")
            
        compressed_data = self._compress_league_data(data)
        
        prompt = f"""
Eres un analista senior experto en Biwenger (Edición Mundial 2026).
Analiza los datos comprimidos de mercado, mi plantilla y mis rivales que te proporciono en formato JSON.

DATOS EN JSON:
{json.dumps(compressed_data, indent=2, ensure_ascii=False)}

Tu objetivo es formular una estrategia ganadora que equilibre la **rentabilidad económica (especulación)** y el **rendimiento deportivo (puntos)**.
Aplica un criterio futbolístico y estratégico avanzado:

- **Rendimiento Reciente y Edad (Filtro de Edad)**: Evalúa críticamente a los jugadores de edad avanzada en 2026 (por ejemplo: Enner Valencia tiene 36 años y su físico no rendirá igual que a los 32 años en el mundial anterior). Prioriza el momento de forma actual sobre la gloria histórica.
- **Rendimiento en Clubes y Amistosos Recientes (Temporada 2025/2026)**: Utiliza tu conocimiento futbolístico sobre la temporada de clubes y amistosos de preparación para identificar revelaciones y chollos en el mercado.
- **Predicciones de Puja de IAs (Modelos de Regresión)**: En el campo `predicted_bids` de los jugadores del mercado tienes las pujas calculadas por el modelo Transformer de cada rival. Recomienda a cuánto debo pujar para ganar la subasta sin sobrepagar de forma absurda.
- **Contexto de Selección (`team`)**: Jugadores de selecciones top (Argentina, Brasil, Francia, España, Alemania, etc.) jugarán más partidos (más rondas) y asegurarán más puntos a largo plazo.
- **Relación Calidad/Precio**: Asigna un Coeficiente Estratégico (CE) del 1 al 10 para cada recomendación de compra/venta relevante.

Por favor, genera tu análisis de la siguiente forma usando Markdown:

1. 🚀 OPORTUNIDADES ESTRATÉGICAS DE COMPRA Y ESPECULACIÓN:
   Tabla con: Jugador, Selección, Precio de Mercado, Puja Rival Máxima (ML), Tu Puja Recomendada, Coeficiente Estratégico (CE 1-10) y Justificación.

2. ⚠️ RECOMENDACIONES DE VENTA Y DESCARTES:
   Tabla con: Jugador, Selección, Posición, Precio actual, Puntos, Coeficiente Estratégico (CE 1-10) y Razón de venta/descarte.

3. ⚽ OPTIMIZACIÓN DEL ONCE INICIAL:
   Propón el once inicial más competitivo con mi plantilla actual y cambios tácticos recomendados.

4. 📊 EXPLOTACIÓN DE DEBILIDADES DE LOS RIVALES Y ANÁLISIS DE PUJAS:
   Tabla con: Rival, Saldo Estimado, Valor de Plantilla, Puntos, Posición a Reforzar (Debilidad) y Comportamiento/Estrategia de Puja Esperada.
"""
        
        max_retries = len(self.api_keys) * 2
        base_delay = 20
        
        for attempt in range(max_retries):
            try:
                model = genai.GenerativeModel(
                    model_name=self.model_name,
                    system_instruction="Eres un analista senior de Biwenger experto en optimización de plantillas, análisis de mercado y especulación."
                )
                
                response = model.generate_content(
                    prompt,
                    generation_config={"temperature": 0.2}
                )
                
                return response.text
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "quota" in err_msg.lower() or "ResourceExhausted" in err_msg:
                    # Rotar la clave si tenemos más de una
                    if len(self.api_keys) > 1 and attempt < max_retries - 1:
                        self._rotate_key()
                        continue
                        
                    # Si ya rotamos todo y no funciona, aplicar retardo
                    if attempt < max_retries - 1:
                        wait_time = base_delay + attempt * 10
                        match = re.search(r"retry_delay\s*{\s*seconds:\s*(\d+)", err_msg)
                        if not match:
                            match = re.search(r"retry in (\d+\.?\d*)s", err_msg)
                        if match:
                            wait_time = int(float(match.group(1))) + 2
                            
                        print(f"\n[Aviso] Límite de cuota alcanzado. Esperando {wait_time}s antes de reintentar...")
                        time.sleep(wait_time)
                        continue
                elif "401" in err_msg or "403" in err_msg or "invalid" in err_msg.lower() or "key" in err_msg.lower() or "credential" in err_msg.lower():
                    # Rotar la clave si hay un problema de autenticación o clave inválida
                    if len(self.api_keys) > 1 and attempt < max_retries - 1:
                        print(f"\n[!] Error de autenticación (401/403) con la clave #{self.current_key_idx + 1}. Rotando...")
                        self._rotate_key()
                        continue
                raise RuntimeError(f"Error al procesar el análisis con Gemini: {e}")

    def generate_chat_response(self, league_data, user_message, chat_history, recent_transactions=None):
        """
        Genera una respuesta interactiva usando los datos comprimidos de la liga, transacciones recientes y el historial de conversación.
        """
        if not self.api_keys:
            raise ValueError("No hay claves API de Gemini válidas cargadas.")
            
        compressed_data = self._compress_league_data(league_data)
        
        system_context = f"""
[CONTEXTO DE LA LIGA EN TIEMPO REAL]
A continuación tienes los datos de la liga de Biwenger estructurados en JSON:
{json.dumps(compressed_data, indent=1, ensure_ascii=False)}
"""
        if recent_transactions:
            tx_lines = []
            for tx in recent_transactions:
                tx_lines.append(f"- [{tx.get('type', '')}] {tx.get('details', '')}")
            system_context += f"\n[HISTORIAL RECIENTE DE TRANSACCIONES]\n" + "\n".join(tx_lines) + "\n"

        system_context += "\nPor favor, utiliza este contexto para responder a todas las preguntas del usuario.\n"
        
        history_gemini = [
            {"role": "user", "parts": [system_context]},
            {"role": "model", "parts": ["Entendido. He procesado la base de datos de la liga en tiempo real. Estoy listo para ayudarte con cualquier consulta sobre tu equipo, rivales, predicciones de puja (ML) y mercado. ¿En qué te puedo asesorar hoy?"]}
        ]
        
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            history_gemini.append({
                "role": role,
                "parts": [msg["content"]]
            })
            
        max_retries = len(self.api_keys) * 2
        base_delay = 20
        
        for attempt in range(max_retries):
            try:
                model = genai.GenerativeModel(
                    model_name=self.model_name,
                    tools=[search_knowledge],
                    system_instruction=(
                        "Eres un consultor personal interactivo y analista senior experto en Biwenger (Edición Mundial 2026). "
                        "Cuentas con acceso a la base de datos de la liga en tiempo real. "
                        "Tu objetivo es resolver dudas del usuario, sugerir estrategias de compra/venta, alineación, "
                        "y predecir el comportamiento de sus rivales usando predicciones de Machine Learning. "
                        "IMPORTANTE: Tienes acceso real a internet/Wikipedia mediante la herramienta `search_knowledge`. "
                        "Si el usuario pregunta por el estado de forma real de un jugador, si es titular o suplente en su selección real, "
                        "lesiones o cualquier dato de actualidad, DEBES invocar la herramienta `search_knowledge` utilizando "
                        "únicamente palabras clave simples como consulta (ej. 'Nico Williams' o 'Francia futbol'). "
                        "No asumas que no puedes buscar información o que tu conocimiento está limitado a tu fecha de entrenamiento; ¡usa la herramienta! "
                        "Sé directo, estratégico, analítico, cercano y profesional. Responde en formato Markdown."
                    )
                )
                
                chat = model.start_chat(
                    history=history_gemini,
                    enable_automatic_function_calling=True
                )
                response = chat.send_message(user_message)
                return response.text
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "quota" in err_msg.lower() or "ResourceExhausted" in err_msg:
                    # Rotar la clave si tenemos más de una
                    if len(self.api_keys) > 1 and attempt < max_retries - 1:
                        self._rotate_key()
                        continue
                        
                    # Si ya rotamos todo y no funciona, aplicar retardo
                    if attempt < max_retries - 1:
                        wait_time = base_delay + attempt * 10
                        match = re.search(r"retry_delay\s*{\s*seconds:\s*(\d+)", err_msg)
                        if not match:
                            match = re.search(r"retry in (\d+\.?\d*)s", err_msg)
                        if match:
                            wait_time = int(float(match.group(1))) + 2
                            
                        print(f"\n[Aviso Chat] Límite de cuota alcanzado. Esperando {wait_time}s antes de reintentar...")
                        time.sleep(wait_time)
                        continue
                elif "401" in err_msg or "403" in err_msg or "invalid" in err_msg.lower() or "key" in err_msg.lower() or "credential" in err_msg.lower():
                    # Rotar la clave si hay un problema de autenticación o clave inválida
                    if len(self.api_keys) > 1 and attempt < max_retries - 1:
                        print(f"\n[!] Error de autenticación (401/403) con la clave #{self.current_key_idx + 1}. Rotando...")
                        self._rotate_key()
                        continue
                raise e
        raise RuntimeError("No se pudo obtener respuesta de Gemini tras varios reintentos debido a límites de cuota o errores de clave.")
