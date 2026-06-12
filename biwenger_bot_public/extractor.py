import requests
import time

POSITION_MAP = {
    1: "Portero",
    2: "Defensa",
    3: "Centrocampista",
    4: "Delantero",
    5: "Entrenador"
}

class BiwengerExtractor:
    def __init__(self, token, league_id, user_id):
        self.token = token
        self.league_id = league_id
        self.user_id = str(user_id)
        
        self.common_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python/requests",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }
        
        self.auth_headers = {
            **self.common_headers,
            "Authorization": f"Bearer {self.token}",
            "x-league": str(self.league_id),
            "x-user": str(self.user_id),
        }

    def _get_request(self, url, headers, timeout=15):
        """
        Realiza una petición GET segura con manejo de errores HTTP y de parseo JSON.
        """
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            print(f"Error HTTP al consultar {url}: {e}")
            if response is not None:
                print(f"Detalle de la respuesta: {response.text[:200]}")
            raise RuntimeError(f"Error de conexión con Biwenger (HTTP {response.status_code if response else 'Desconocido'})")
        except requests.exceptions.RequestException as e:
            print(f"Error de red al consultar {url}: {e}")
            raise RuntimeError("Error de red al conectar con los servidores de Biwenger. Verifica tu conexión.")
        except requests.exceptions.JSONDecodeError as e:
            print(f"Error al decodificar JSON de {url}: {e}")
            raise RuntimeError("La API de Biwenger devolvió un formato no válido (no JSON).")

    def fetch_global_data(self):
        """
        Obtiene la base de datos global de jugadores y equipos de la competición actual.
        """
        url = "https://cf.biwenger.com/api/v2/competitions/world-cup/data?lang=es"
        data = self._get_request(url, headers=self.common_headers)
        
        comp_data = data.get("data", {})
        players = comp_data.get("players", {})
        teams = comp_data.get("teams", {})
        if not players:
            raise RuntimeError("No se pudo obtener la base de datos de jugadores globales de la API de Biwenger.")
        return players, teams

    def fetch_user_team(self, target_user_id):
        """
        Obtiene el equipo y balance de un usuario específico de la liga.
        """
        url = f"https://biwenger.as.com/api/v2/user/{target_user_id}?fields=*,players(id)"
        data = self._get_request(url, headers=self.auth_headers)
        
        user_info = data.get("data", {})
        if not user_info:
            raise RuntimeError(f"No se pudieron obtener los datos para el usuario ID {target_user_id}.")
        return user_info

    def fetch_market(self):
        """
        Obtiene los jugadores actualmente en el mercado de fichajes.
        """
        url = "https://biwenger.as.com/api/v2/market"
        data = self._get_request(url, headers=self.auth_headers)
        
        market_data = data.get("data", {})
        return market_data

    def fetch_league_users(self):
        """
        Obtiene la lista de todos los usuarios miembros de la liga.
        """
        url = "https://biwenger.as.com/api/v2/league"
        data = self._get_request(url, headers=self.auth_headers)
        
        users = data.get("data", {}).get("users", [])
        return users

    def fetch_board(self, limit=100):
        """
        Obtiene el feed de noticias/tablón de la liga.
        """
        url = f"https://biwenger.as.com/api/v2/league/{self.league_id}/board?limit={limit}"
        data = self._get_request(url, headers=self.auth_headers)
        return data.get("data", [])

    def estimate_rival_balances_with_data(self, global_db, league_users, board_data):
        """
        Reconstruye cronológicamente el saldo estimado de los rivales
        basándose en un listado de board_data proporcionado.
        """
        # 1. Obtener la plantilla actual de cada rival (IDs de jugadores)
        user_current_rosters = {}
        for user in league_users:
            u_id = user.get("id")
            try:
                # Delay prudencial para evitar rate limits
                time.sleep(0.2)
                u_raw = self.fetch_user_team(u_id)
                user_current_rosters[u_id] = set(p["id"] for p in u_raw.get("players", []))
            except Exception:
                user_current_rosters[u_id] = set()

        # 2. Reconstruir plantilla inicial en reversa (T=0)
        initial_rosters = {u_id: set(roster) for u_id, roster in user_current_rosters.items()}
        
        for item in reversed(board_data):
            t = item.get("type")
            content = item.get("content")
            if not content:
                continue
                
            if t in ("transfer", "clause"):
                for sub in content:
                    p_id = sub.get("player")
                    from_user = sub.get("from", {}).get("id")
                    to_user = sub.get("to", {}).get("id")
                    if to_user in initial_rosters:
                        initial_rosters[to_user].discard(p_id)
                    if from_user in initial_rosters:
                        initial_rosters[from_user].add(p_id)
            elif t == "market":
                for sub in content:
                    p_id = sub.get("player")
                    to_user = sub.get("to", {}).get("id")
                    if to_user in initial_rosters:
                        initial_rosters[to_user].discard(p_id)
            elif t == "exchange":
                f_user = content.get("from", {}).get("id")
                to_user = content.get("to", {}).get("id")
                offered = content.get("offeredPlayers", [])
                requested = content.get("requestedPlayers", [])
                if f_user in initial_rosters:
                    for p in offered:
                        initial_rosters[f_user].add(p)
                    for p in requested:
                        initial_rosters[f_user].discard(p)
                if to_user in initial_rosters:
                    for p in offered:
                        initial_rosters[to_user].discard(p)
                    for p in requested:
                        initial_rosters[to_user].add(p)

        # 3. Inicializar saldos a T=0 usando base de 50M de presupuesto total (Plantilla + Saldo)
        user_cash = {}
        for u_id, roster in initial_rosters.items():
            roster_value = sum(global_db.get(str(p_id), {}).get("price", 0) for p_id in roster)
            user_cash[u_id] = 50000000 - roster_value

        # 4. Procesar transacciones cronológicamente para obtener el saldo actual
        for item in board_data:
            t = item.get("type")
            content = item.get("content")
            if not content:
                continue
                
            if t in ("transfer", "clause"):
                for sub in content:
                    f_user = sub.get("from", {}).get("id")
                    to_user = sub.get("to", {}).get("id")
                    amount = sub.get("amount", 0)
                    if f_user in user_cash:
                        user_cash[f_user] += amount
                    if to_user in user_cash:
                        user_cash[to_user] -= amount
            elif t == "market":
                for sub in content:
                    to_user = sub.get("to", {}).get("id")
                    amount = sub.get("amount", 0)
                    if to_user in user_cash:
                        user_cash[to_user] -= amount
            elif t == "pay":
                for sub in content:
                    u_id = sub.get("user", {}).get("id")
                    amount = sub.get("amount", 0)
                    if u_id in user_cash:
                        user_cash[u_id] += amount
            elif t == "clauseIncrement":
                for sub in content:
                    u_id = sub.get("user", {}).get("id")
                    amount = sub.get("amount", 0)
                    if u_id in user_cash:
                        user_cash[u_id] -= amount
            elif t == "exchange":
                f_user = content.get("from", {}).get("id")
                to_user = content.get("to", {}).get("id")
                amount = content.get("amount", 0)
                req_amount = content.get("requestedAmount", 0)
                if f_user in user_cash:
                    user_cash[f_user] -= amount
                    user_cash[f_user] += req_amount
                if to_user in user_cash:
                    user_cash[to_user] += amount
                    user_cash[to_user] -= req_amount
                    
        return user_cash, initial_rosters, board_data

    def estimate_rival_balances(self, global_db, league_users):
        """
        Reconstruye cronológicamente el saldo estimado de los rivales
        basándose en el feed de transferencias y el presupuesto inicial.
        """
        print("[*] Ejecutando Cash Tracker para estimar saldos de rivales...")
        board_data = self.fetch_board(limit=100)
        return self.estimate_rival_balances_with_data(global_db, league_users, board_data)

    def get_player_details(self, player_id, global_db, teams_db):
        """
        Busca un jugador por ID en la base de datos global y devuelve sus detalles formateados
        incluyendo su equipo (país), historial de puntos y estado de forma.
        """
        p_id_str = str(player_id)
        if p_id_str in global_db:
            p_info = global_db[p_id_str]
            pos_code = p_info.get("position", 0)
            
            # Resolver nombre del país/equipo
            team_id = str(p_info.get("teamID", ""))
            team_name = teams_db.get(team_id, {}).get("name", "Desconocido") if teams_db else "Desconocido"
            
            return {
                "id": p_info.get("id"),
                "name": p_info.get("name"),
                "team": team_name,
                "position": POSITION_MAP.get(pos_code, f"Desconocido ({pos_code})"),
                "price": p_info.get("price", 0),
                "priceIncrement": p_info.get("priceIncrement", 0),
                "status": p_info.get("status", "desconocido"),
                "points": p_info.get("points", 0),
                "pointsLastSeason": p_info.get("pointsLastSeason"),
                "fitness": p_info.get("fitness", [])
            }
        return {
            "id": player_id,
            "name": "Jugador Desconocido",
            "team": "Desconocido",
            "position": "Desconocido",
            "price": 0,
            "priceIncrement": 0,
            "status": "desconocido",
            "points": 0,
            "pointsLastSeason": None,
            "fitness": []
        }

    def extract_structured_data(self):
        """
        Extrae y unifica toda la información de la liga en un JSON legible para ser procesado.
        """
        print("[*] Iniciando extracción de datos de Biwenger...")
        
        # 1. Base de datos global
        print("[*] Descargando base de datos global de jugadores y equipos...")
        global_db, teams_db = self.fetch_global_data()
        
        # 2. Mi equipo actual
        print(f"[*] Obteniendo plantilla para el usuario principal {self.user_id}...")
        my_raw_team = self.fetch_user_team(self.user_id)
        
        my_players = []
        for p in my_raw_team.get("players", []):
            details = self.get_player_details(p["id"], global_db, teams_db)
            my_players.append(details)
            
        my_team_summary = {
            "id": my_raw_team.get("id"),
            "name": my_raw_team.get("name"),
            "balance": my_raw_team.get("balance", 0),
            "points": my_raw_team.get("points", 0),
            "team_value": sum(p["price"] for p in my_players),
            "players": my_players
        }
        
        # 3. Datos de rivales y estimación de saldos (Cash Tracker)
        print("[*] Recuperando lista de rivales en la liga...")
        league_users = self.fetch_league_users()
        
        # Estimar saldos y entrenar modelos de IA individuales para predecir comportamiento
        try:
            estimated_balances, initial_rosters, board_data = self.estimate_rival_balances(global_db, league_users)
            
            # Entrenar IAs para predecir pujas de rivales
            from predictor import RivalBidPredictor
            bid_predictor = RivalBidPredictor(global_db, teams_db)
            bid_predictor.train_models(board_data, initial_rosters)
        except Exception as e:
            print(f"[Advertencia] Falló la estimación de saldos o el entrenamiento de IAs: {e}")
            import traceback
            traceback.print_exc()
            estimated_balances = {}
            bid_predictor = None
            
        # 4. Mercado de fichajes con predicciones de Machine Learning
        print("[*] Consultando mercado de fichajes...")
        market_raw = self.fetch_market()
        sales_raw = market_raw.get("sales", [])
        
        market_summary = []
        for sale in sales_raw:
            p_id = sale.get("player", {}).get("id")
            if p_id:
                details = self.get_player_details(p_id, global_db, teams_db)
                details["market_sale_price"] = sale.get("price", details["price"])
                user_info = sale.get("user")
                details["seller"] = "Computer" if user_info is None else "Rival"
                
                # Ejecutar predicción de pujas de rivales usando sus modelos de Machine Learning individuales
                rivals_predicted_bids = {}
                if bid_predictor and bid_predictor.trained:
                    for rival in league_users:
                        r_id = rival.get("id")
                        if str(r_id) == self.user_id:
                            continue
                        
                        r_cash = estimated_balances.get(r_id, 20000000)
                        # El valor del equipo lo podemos aproximar con 25M por ahora para predicción,
                        # o lo calcularemos en el bloque de rivales más abajo y lo cruzamos
                        r_team_val = 25000000 
                        
                        premium = bid_predictor.predict_bid_premium(
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
                
        # 5. Rellenar plantillas de rivales y adjuntar sus saldos
        rivals_summary = []
        for user in league_users:
            u_id = str(user.get("id"))
            # Omitimos nuestro propio usuario
            if u_id == self.user_id:
                continue
                
            print(f"    - Extrayendo plantilla de rival: {user.get('name')} (ID: {u_id})...")
            time.sleep(0.5)
            
            rival_est_balance = estimated_balances.get(user.get("id"), 0)
            
            try:
                rival_raw_team = self.fetch_user_team(u_id)
                rival_players = []
                for p in rival_raw_team.get("players", []):
                    details = self.get_player_details(p["id"], global_db, teams_db)
                    rival_players.append(details)
                
                rivals_summary.append({
                    "id": rival_raw_team.get("id"),
                    "name": rival_raw_team.get("name"),
                    "points": rival_raw_team.get("points", 0),
                    "estimated_balance": rival_est_balance,
                    "team_value": sum(p["price"] for p in rival_players),
                    "players": rival_players
                })
            except Exception as e:
                print(f"      [Advertencia] No se pudo obtener la plantilla de {user.get('name')}: {e}")
                rivals_summary.append({
                    "id": user.get("id"),
                    "name": user.get("name"),
                    "points": 0,
                    "estimated_balance": rival_est_balance,
                    "team_value": 0,
                    "players": [],
                    "error": "No se pudo extraer la plantilla"
                })
        
        # Unificamos todo el JSON estructurado
        final_json = {
            "my_team": my_team_summary,
            "market": market_summary,
            "rivals": rivals_summary,
            "timestamp": int(time.time())
        }
        
        print("[+] Extracción y predicción ML completadas exitosamente.")
        return final_json
