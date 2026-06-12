import os
import sys
import time
import json
import sqlite3
import threading
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import config
from extractor import BiwengerExtractor
from predictor import RivalBidPredictor
from gemini_client import GeminiClient

DB_PATH = "biwenger_history.db"
DATA_LOCK = threading.Lock()

# Estado compartido del servidor
LATEST_DATA = None
PREDICTOR = None
INITIAL_ROSTERS = None
LAST_UPDATE_TIME = 0
IS_SYNCING = False
LAST_TRAINED_TX_COUNT = 0
GLOBAL_PLAYERS_DB = {}

app = FastAPI(title="Biwenger Bot Server - Mundial 2026")

# Crear carpeta de estáticos si no existe
os.makedirs("static", exist_ok=True)

# Conector dinámico de Base de Datos para soportar SQLite local y PostgreSQL (Supabase) en producción
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        import psycopg2
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(db_url)
    return sqlite3.connect(DB_PATH)

def get_db_placeholder():
    if os.environ.get("DATABASE_URL"):
        return "%s"
    return "?"

# Inicializar Base de Datos (soporta SQLite y PostgreSQL)
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # En PostgreSQL TEXT PRIMARY KEY es válido.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            type TEXT,
            timestamp INTEGER,
            payload TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at INTEGER,
            messages TEXT
        )
    """)
    conn.commit()
    conn.close()

def load_cached_data_at_startup():
    global LATEST_DATA, LAST_UPDATE_TIME
    if os.path.exists("biwenger_data.json"):
        try:
            with open("biwenger_data.json", "r", encoding="utf-8") as f:
                LATEST_DATA = json.load(f)
                LAST_UPDATE_TIME = LATEST_DATA.get("timestamp", int(time.time()))
            print("[+] Servidor: Datos recuperados desde 'biwenger_data.json' para inicio rápido.")
        except Exception as e:
            print(f"[!] Servidor: No se pudo precargar 'biwenger_data.json': {e}")

def get_item_id(item):
    item_id = item.get("id")
    if item_id:
        return str(item_id)
    import hashlib
    content_str = json.dumps(item.get("content", {}), sort_keys=True)
    h = hashlib.md5((str(item.get("type", "")) + "_" + str(item.get("date", 0)) + "_" + content_str).encode("utf-8")).hexdigest()
    return h

def save_transactions_to_db(board_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    new_count = 0
    p = get_db_placeholder()
    query = f"INSERT INTO transactions (id, type, timestamp, payload) VALUES ({p}, {p}, {p}, {p})"
    for item in board_data:
        t_id = get_item_id(item)
        t_type = item.get("type", "")
        t_timestamp = item.get("date", 0)
        t_payload = json.dumps(item)
        try:
            cursor.execute(query, (t_id, t_type, t_timestamp, t_payload))
            new_count += 1
        except Exception:
            # En caso de duplicado (UniqueViolation / IntegrityError) pasamos silenciosamente
            if not os.environ.get("DATABASE_URL"):
                # Si es SQLite, hace falta rollback explícito si está en transacción rota en algunos drivers,
                # pero para inserts individuales por cursor suele bastar con ignorar.
                pass
            else:
                # Para PostgreSQL/psycopg2 es OBLIGATORIO hacer rollback si ocurre un error para seguir usando la conexión
                conn.rollback()
    conn.commit()
    conn.close()
    return new_count

def load_all_transactions_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT payload FROM transactions ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    conn.close()
    
    board_data = []
    for row in rows:
        board_data.append(json.loads(row[0]))
    return board_data

def get_db_transactions_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions")
    count = cursor.fetchone()[0]
    conn.close()
    return count

# Sincronización principal y entrenamiento de IAs (soportando ejecución síncrona o asíncrona)
def sync_data():
    global LATEST_DATA, PREDICTOR, INITIAL_ROSTERS, LAST_UPDATE_TIME, IS_SYNCING, LAST_TRAINED_TX_COUNT, GLOBAL_PLAYERS_DB
    
    try:
        extractor = BiwengerExtractor(
            token=config.BIWENGER_TOKEN,
            league_id=config.BIWENGER_LEAGUE,
            user_id=config.BIWENGER_USER
        )
        
        print("\n[*] Sincronizador: Consultando datos en Biwenger API...")
        
        # 1. Obtener base de datos de jugadores y usuarios de liga
        global_db, teams_db = extractor.fetch_global_data()
        my_raw_team = extractor.fetch_user_team(extractor.user_id)
        league_users = extractor.fetch_league_users()
        
        # 2. Descargar feed reciente (100 noticias)
        board_raw = extractor.fetch_board(limit=100)
        
        # 3. Guardar transacciones y comprobar si hay nuevas
        new_txs = save_transactions_to_db(board_raw)
        current_txs_count = get_db_transactions_count()
        print(f"[+] Sincronizador: {new_txs} nuevas transacciones añadidas. Total en BD: {current_txs_count}")
        
        # 4. Cargar historial consolidado desde SQLite / Postgres
        all_db_board = load_all_transactions_from_db()
        
        # 5. Reconstruir los saldos de los rivales basados en el historial completo
        estimated_balances, initial_rosters, _ = extractor.estimate_rival_balances_with_data(global_db, league_users, all_db_board)
        
        # 6. Reentrenamiento CONDICIONAL
        if PREDICTOR is None or current_txs_count > LAST_TRAINED_TX_COUNT:
            print(f"[*] Sincronizador: Reentrenamiento disparado. Transacciones previas: {LAST_TRAINED_TX_COUNT}, actuales: {current_txs_count}")
            new_predictor = RivalBidPredictor(global_db, teams_db)
            new_predictor.train_models(all_db_board, initial_rosters)
            
            with DATA_LOCK:
                PREDICTOR = new_predictor
                INITIAL_ROSTERS = initial_rosters
                LAST_TRAINED_TX_COUNT = current_txs_count
            print("[+] Sincronizador: Modelos secuenciales Transformer actualizados con éxito.")
        else:
            print("[*] Sincronizador: Sin nuevas transacciones de fichajes. Conservando modelos en memoria.")
        
        # 7. Procesar mercado con predicciones secuenciales de pujas
        market_raw = extractor.fetch_market()
        sales_raw = market_raw.get("sales", [])
        
        market_summary = []
        for sale in sales_raw:
            p_id = sale.get("player", {}).get("id")
            if p_id:
                details = extractor.get_player_details(p_id, global_db, teams_db)
                details["market_sale_price"] = sale.get("price", details["price"])
                user_info = sale.get("user")
                details["seller"] = "Computer" if user_info is None else "Rival"
                
                rivals_predicted_bids = {}
                with DATA_LOCK:
                    active_predictor = PREDICTOR
                    
                if active_predictor and active_predictor.trained:
                    for rival in league_users:
                        r_id = rival.get("id")
                        if str(r_id) == extractor.user_id:
                            continue
                        
                        r_cash = estimated_balances.get(r_id, 20000000)
                        r_team_val = 25000000
                        
                        premium = active_predictor.predict_bid_premium(
                            user_id=r_id,
                            player_price=details["price"],
                            price_inc=details["priceIncrement"],
                            position_name=details["position"],
                            team_name=details["team"],
                            user_cash=r_cash,
                            user_team_val=r_team_val
                        )
                        predicted_bid_price = int(details["price"] * (1 + premium))
                        rivals_predicted_bids[rival.get("name")] = {
                            "predicted_overbid_pct": round(premium * 100, 1),
                            "predicted_bid_price": predicted_bid_price
                        }
                details["rivals_predicted_bids"] = rivals_predicted_bids
                market_summary.append(details)
        
        # 8. Guardar mi plantilla
        my_players = []
        for p in my_raw_team.get("players", []):
            my_players.append(extractor.get_player_details(p["id"], global_db, teams_db))
            
        my_team_summary = {
            "id": my_raw_team.get("id"),
            "name": my_raw_team.get("name"),
            "balance": my_raw_team.get("balance", 0),
            "points": my_raw_team.get("points", 0),
            "team_value": sum(p["price"] for p in my_players),
            "players": my_players
        }
        
        # 9. Guardar rivales
        rivals_summary = []
        for user in league_users:
            u_id = str(user.get("id"))
            if u_id == extractor.user_id:
                continue
            
            time.sleep(0.1)
            rival_est_balance = estimated_balances.get(user.get("id"), 0)
            try:
                rival_raw_team = extractor.fetch_user_team(u_id)
                rival_players = []
                for p in rival_raw_team.get("players", []):
                    rival_players.append(extractor.get_player_details(p["id"], global_db, teams_db))
                
                rivals_summary.append({
                    "id": rival_raw_team.get("id"),
                    "name": rival_raw_team.get("name"),
                    "points": rival_raw_team.get("points", 0),
                    "estimated_balance": rival_est_balance,
                    "team_value": sum(p["price"] for p in rival_players),
                    "players": rival_players
                })
            except Exception:
                rivals_summary.append({
                    "id": user.get("id"),
                    "name": user.get("name"),
                    "points": 0,
                    "estimated_balance": rival_est_balance,
                    "team_value": 0,
                    "players": []
                })
                
        # 10. Actualizar el estado global en memoria
        with DATA_LOCK:
            LATEST_DATA = {
                "my_team": my_team_summary,
                "market": market_summary,
                "rivals": rivals_summary,
                "timestamp": int(time.time())
            }
            LAST_UPDATE_TIME = int(time.time())
            GLOBAL_PLAYERS_DB = global_db
            
        # Guardar respaldo en disco
        with open("biwenger_data.json", "w", encoding="utf-8") as f:
            json.dump(LATEST_DATA, f, indent=2, ensure_ascii=False)
            
        print(f"[+] Sincronizador: Finalizado y guardado con éxito.")
        return True
    except Exception as e:
        print(f"[Error Sincronizador] Sincronización fallida: {e}")
        import traceback
        traceback.print_exc()
        return False

# Sincronizador asíncrono en segundo plano (Sincronización a 10 minutos)
def background_sync_worker():
    global IS_SYNCING
    time.sleep(2)
    print("[*] Worker: Sincronizador en segundo plano iniciado.")
    
    while True:
        with DATA_LOCK:
            already_syncing = IS_SYNCING
            
        if not already_syncing:
            with DATA_LOCK:
                IS_SYNCING = True
            try:
                sync_data()
            finally:
                with DATA_LOCK:
                    IS_SYNCING = False
                    
        # Esperar 10 minutos (600 segundos) para la próxima sincronización
        time.sleep(600)

# Inicializar e iniciar sincronizador
init_db()
load_cached_data_at_startup()

sync_thread = threading.Thread(target=background_sync_worker, daemon=True)
sync_thread.start()

# Modelos Pydantic para APIs
class ChatInput(BaseModel):
    message: str

# Endpoints de la API
@app.get("/api/status")
def get_status():
    """
    Retorna el estado de sincronización y los datos estructurados en tiempo real.
    """
    with DATA_LOCK:
        data = LATEST_DATA
        update_time = LAST_UPDATE_TIME
        is_sync = IS_SYNCING
        tx_count = LAST_TRAINED_TX_COUNT
        
    if data is None:
        return JSONResponse(
            content={"status": "initializing", "message": "El servidor está descargando datos iniciales y entrenando la IA..."},
            status_code=202
        )
        
    return {
        "status": "ready",
        "last_update": update_time,
        "is_syncing": is_sync,
        "trained_transactions": tx_count,
        "my_team": {
            "name": data["my_team"]["name"],
            "balance": data["my_team"]["balance"],
            "team_value": data["my_team"]["team_value"],
            "player_count": len(data["my_team"]["players"])
        },
        "market_count": len(data["market"]),
        "rivals": [
            {
                "name": r["name"],
                "estimated_balance": r["estimated_balance"],
                "team_value": r["team_value"]
            } for r in data["rivals"]
        ]
    }

@app.post("/api/sync")
def trigger_manual_sync():
    """
    Despierta manualmente al sincronizador para obtener datos de Biwenger y reentrenar.
    """
    global IS_SYNCING
    with DATA_LOCK:
        if IS_SYNCING:
            return JSONResponse(
                content={"status": "error", "message": "Ya hay una sincronización en curso en este momento."},
                status_code=409
            )
        IS_SYNCING = True
        
    success = sync_data()
    if success:
        return {"status": "success", "message": "Datos de Biwenger y modelos Transformer actualizados al instante."}
    else:
        return JSONResponse(
            content={"status": "error", "message": "Hubo un error al sincronizar con la API de Biwenger. Revisa tus credenciales o el estado de la red."},
            status_code=500
        )

# --- ENDPOINTS HISTORIAL DE CHATS ---

@app.get("/api/chats")
def list_chats():
    """
    Devuelve la lista de conversaciones guardadas en la base de datos.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, created_at FROM chats ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {"id": row[0], "title": row[1], "created_at": row[2]} for row in rows
    ]

@app.post("/api/chats")
def create_chat():
    """
    Crea una nueva conversación vacía.
    """
    chat_id = str(uuid.uuid4())
    title = "Nueva Conversación"
    created_at = int(time.time())
    empty_messages = json.dumps([])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    p = get_db_placeholder()
    cursor.execute(
        f"INSERT INTO chats (id, title, created_at, messages) VALUES ({p}, {p}, {p}, {p})",
        (chat_id, title, created_at, empty_messages)
    )
    conn.commit()
    conn.close()
    
    return {"id": chat_id, "title": title}

@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    """
    Devuelve la lista de mensajes de una conversación específica.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    p = get_db_placeholder()
    cursor.execute(f"SELECT messages FROM chats WHERE id = {p}", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return JSONResponse(content={"error": "Conversación no encontrada"}, status_code=404)
        
    return json.loads(row[0])

@app.post("/api/chats/{chat_id}/message")
def post_chat_message(chat_id: str, chat_input: ChatInput):
    """
    Agrega un mensaje de usuario a un chat específico, llama a Gemini y guarda la respuesta en la BD.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    p = get_db_placeholder()
    cursor.execute(f"SELECT title, messages FROM chats WHERE id = {p}", (chat_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return JSONResponse(content={"error": "Conversación no encontrada"}, status_code=404)
        
    title, messages_json = row[0], row[1]
    messages = json.loads(messages_json)
    
    # 1. Llamar a Gemini con el historial actual de ese chat y los datos de Biwenger en tiempo real
    with DATA_LOCK:
        league_data = LATEST_DATA
        
    if league_data is None:
        conn.close()
        return JSONResponse(
            content={"reply": "El servidor se está iniciando y descargando los datos de tu liga. Por favor, reintenta en unos segundos."},
            status_code=503
        )
        
    try:
        client = GeminiClient(model_name=config.GEMINI_MODEL)
        
        # Obtener las últimas 30 transacciones para dárselas como contexto al chatbot
        recent_txs = []
        try:
            recent_txs = get_transactions()[:30]
        except Exception as tx_err:
            print(f"[!] Error al cargar transacciones para el contexto del chat: {tx_err}")
            
        reply = client.generate_chat_response(
            league_data=league_data,
            user_message=chat_input.message,
            chat_history=messages,
            recent_transactions=recent_txs
        )
        
        # 2. Agregar los dos nuevos mensajes al historial
        messages.append({"role": "user", "content": chat_input.message})
        messages.append({"role": "model", "content": reply})
        
        # 3. Actualizar automáticamente el título si es una conversación nueva
        updated_title = title
        if title == "Nueva Conversación" or title.startswith("Conversación "):
            msg_clip = chat_input.message.strip()
            updated_title = msg_clip[:25] + "..." if len(msg_clip) > 25 else msg_clip
            
        cursor.execute(
            f"UPDATE chats SET title = {p}, messages = {p} WHERE id = {p}",
            (updated_title, json.dumps(messages), chat_id)
        )
        conn.commit()
        
    except Exception as e:
        conn.close()
        return JSONResponse(
            content={"reply": f"Error al procesar la consulta con Gemini: {str(e)}"},
            status_code=500
        )
        
    conn.close()
    return {"reply": reply, "title": updated_title}

@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    """
    Elimina una conversación específica de la base de datos.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    p = get_db_placeholder()
    cursor.execute(f"DELETE FROM chats WHERE id = {p}", (chat_id,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Conversación eliminada"}

# --- ENDPOINT HISTORIAL DE OPERACIONES ---

@app.get("/api/transactions")
def get_transactions():
    """
    Retorna el historial de operaciones de mercado formateadas de forma legible.
    """
    board_data = load_all_transactions_from_db()
    with DATA_LOCK:
        data = LATEST_DATA
        global_players = GLOBAL_PLAYERS_DB
        
    # Crear un diccionario para mapeo de IDs de usuarios y jugadores
    user_names = {}
    player_names = {}
    if data:
        user_names[str(data["my_team"]["id"])] = data["my_team"]["name"]
        for p in data["my_team"]["players"]:
            player_names[str(p["id"])] = p["name"]
            
        for r in data["rivals"]:
            user_names[str(r["id"])] = r["name"]
            for p in r["players"]:
                player_names[str(p["id"])] = p["name"]
                
        for p in data["market"]:
            player_names[str(p["id"])] = p["name"]
                
    formatted_txs = []
    
    for item in board_data:
        t_type = item.get("type")
        content = item.get("content")
        ts = item.get("date", 0)
        
        if not content:
            continue
            
        if t_type == "market":
            for sub in content:
                p_id = str(sub.get("player", ""))
                p_name = global_players.get(p_id, {}).get("name") or player_names.get(p_id, f"Jugador #{p_id}")
                
                to_id = str(sub.get("to", {}).get("id", ""))
                to_name = sub.get("to", {}).get("name") or user_names.get(to_id, "Computer")
                if to_name == "Desconocido":
                    to_name = "Computer"
                
                amount = sub.get("amount", 0)
                formatted_txs.append({
                    "id": item.get("id", str(ts)),
                    "type": "Compra de Mercado",
                    "date": ts,
                    "details": f"**{to_name}** compró a **{p_name}** por **{amount:,} €**"
                })
        elif t_type in ("transfer", "clause"):
            for sub in content:
                p_id = str(sub.get("player", ""))
                p_name = global_players.get(p_id, {}).get("name") or player_names.get(p_id, f"Jugador #{p_id}")
                
                from_id = str(sub.get("from", {}).get("id", ""))
                from_name = sub.get("from", {}).get("name") or user_names.get(from_id, "Computer")
                if from_name == "Desconocido":
                    from_name = "Computer"
                
                to_id = str(sub.get("to", {}).get("id", ""))
                to_name = sub.get("to", {}).get("name") or user_names.get(to_id, "Computer")
                if to_name == "Desconocido":
                    to_name = "Computer"
                
                amount = sub.get("amount", 0)
                formatted_txs.append({
                    "id": item.get("id", str(ts)),
                    "type": "Pago Cláusula" if t_type == "clause" else "Transferencia",
                    "date": ts,
                    "details": f"**{to_name}** pagó la cláusula de **{p_name}** a **{from_name}** por **{amount:,} €**" if t_type == "clause" else f"**{to_name}** fichó a **{p_name}** de **{from_name}** por **{amount:,} €**"
                })
        elif t_type == "pay":
            for sub in content:
                u_id = str(sub.get("user", {}).get("id", ""))
                u_name = sub.get("user", {}).get("name") or user_names.get(u_id, "Rival")
                if u_name == "Desconocido":
                    u_name = "Rival"
                
                amount = sub.get("amount", 0)
                op_desc = "Abono de Liga" if amount >= 0 else "Sanción de Liga"
                formatted_txs.append({
                    "id": item.get("id", str(ts)),
                    "type": op_desc,
                    "date": ts,
                    "details": f"**{u_name}** recibió un abono de **{amount:,} €** de la administración" if amount >= 0 else f"**{u_name}** recibió una sanción de **{abs(amount):,} €** de la administración"
                })
        elif t_type == "clauseIncrement":
            for sub in content:
                p_id = str(sub.get("player", ""))
                p_name = global_players.get(p_id, {}).get("name") or player_names.get(p_id, f"Jugador #{p_id}")
                
                u_id = str(sub.get("user", {}).get("id", ""))
                u_name = sub.get("user", {}).get("name") or user_names.get(u_id, "Computer")
                if u_name == "Desconocido":
                    u_name = "Computer"
                
                amount = sub.get("amount", 0)
                formatted_txs.append({
                    "id": item.get("id", str(ts)),
                    "type": "Incremento Cláusula",
                    "date": ts,
                    "details": f"**{u_name}** incrementó la cláusula de **{p_name}** por **{amount:,} €**"
                })
        elif t_type == "exchange":
            f_id = str(content.get("from", {}).get("id", ""))
            f_name = content.get("from", {}).get("name") or user_names.get(f_id, "Computer")
            if f_name == "Desconocido":
                f_name = "Computer"
            
            to_id = str(content.get("to", {}).get("id", ""))
            to_name = content.get("to", {}).get("name") or user_names.get(to_id, "Computer")
            if to_name == "Desconocido":
                to_name = "Computer"
            
            amount = content.get("amount", 0)
            req_amount = content.get("requestedAmount", 0)
            
            offered = []
            for p in content.get("offeredPlayers", []):
                p_id = str(p)
                name = global_players.get(p_id, {}).get("name") or player_names.get(p_id, f"Jugador #{p_id}")
                offered.append(name)
                
            requested = []
            for p in content.get("requestedPlayers", []):
                p_id = str(p)
                name = global_players.get(p_id, {}).get("name") or player_names.get(p_id, f"Jugador #{p_id}")
                requested.append(name)
            
            details = f"Intercambio acordado entre **{f_name}** y **{to_name}**."
            if offered:
                details += f" **{f_name}** entregó a: **{', '.join(offered)}**."
            if requested:
                details += f" **{to_name}** entregó a: **{', '.join(requested)}**."
            diff = amount - req_amount
            if diff != 0:
                details += f" Compensación económica: **{abs(diff):,} €**."
                
            formatted_txs.append({
                "id": item.get("id", str(ts)),
                "type": "Intercambio",
                "date": ts,
                "details": details
            })
            
    formatted_txs.sort(key=lambda x: x["date"], reverse=True)
    return formatted_txs

# Servir Frontend
@app.get("/")
def read_root():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    return HTMLResponse(
        content="<h2>Servidor Iniciado</h2><p>El frontend se está cargando, por favor refresca en un momento.</p>",
        status_code=200
    )

# Montar carpeta estática
app.mount("/static", StaticFiles(directory="static"), name="static")
