import numpy as np
import time
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder

# Intentar importar PyTorch de forma segura para dar soporte a la arquitectura Transformer
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Tiers de Selecciones para el Mundial 2026
TIER_MAP = {
    # Tier 1: Favoritas absolutas
    "Argentina": 1, "Francia": 1, "Brasil": 1, "España": 1, "Inglaterra": 1, "Alemania": 1, "Portugal": 1,
    # Tier 2: Selecciones competitivas / nivel medio-alto
    "Bélgica": 2, "Países Bajos": 2, "Croacia": 2, "Uruguay": 2, "Colombia": 2, "Ecuador": 2, 
    "Turquía": 2, "Suiza": 2, "Austria": 2, "Ghana": 2, "Senegal": 2, "Marruecos": 2, "Japón": 2,
    # Tier 3: Selecciones de nivel bajo en fantasy
    "Túnez": 3, "Canadá": 3, "Panamá": 3, "Curazao": 3, "Haití": 3, "Irak": 3, "Cabo Verde": 3, "Egipto": 3
}

POSITION_CODE_MAP = {
    "Portero": 1,
    "Defensa": 2,
    "Centrocampista": 3,
    "Delantero": 4,
    "Entrenador": 5
}

# Definir el modelo Transformer en PyTorch si está disponible
if TORCH_AVAILABLE:
    class BidTransformerModel(nn.Module):
        def __init__(self, input_dim=7, d_model=32, nhead=2, num_layers=1, dim_feedforward=64, dropout=0.1):
            super().__init__()
            self.input_proj = nn.Linear(input_dim, d_model)
            # Longitud de secuencia fija S = 5
            self.pos_encoder = nn.Parameter(torch.zeros(5, d_model))
            
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
                batch_first=True
            )
            self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
            self.output_proj = nn.Linear(d_model, 1)

        def forward(self, x):
            # x shape: (batch_size, seq_len, input_dim)
            x = self.input_proj(x)  # (batch_size, seq_len, d_model)
            x = x + self.pos_encoder  # Broadcasting embedding posicional
            x = self.transformer_encoder(x)  # (batch_size, seq_len, d_model)
            # Tomamos la representación del último token (el contexto de puja actual)
            out = x[:, -1, :]  # (batch_size, d_model)
            pred = self.output_proj(out)  # (batch_size, 1)
            return pred.squeeze(-1)

class RivalBidPredictor:
    def __init__(self, global_db, teams_db):
        self.global_db = global_db
        self.teams_db = teams_db
        
        # Modelos (ID -> Modelo entrenado)
        self.user_models = {}
        self.global_model = None
        
        # Historial de secuencias por usuario para inferencia posterior
        self.user_histories = {}
        
        # Determinar si usamos Transformer en PyTorch o fallback
        self.use_transformer = TORCH_AVAILABLE
        self.trained = False
        
        if self.use_transformer:
            print("[+] PyTorch detectado: Se utilizará la arquitectura Transformer para predecir pujas.")
        else:
            print("[!] PyTorch no detectado: Se utilizará RandomForestRegressor como fallback tabular.")

    def _get_selection_tier(self, team_name):
        return TIER_MAP.get(team_name, 3)

    def train_models(self, board_data, initial_rosters):
        """
        Reconstruye cronológicamente el historial de transacciones de cada usuario
        y entrena los modelos de Machine Learning (Transformer / RandomForest) para predecir pujas.
        """
        print("[*] Preparando entrenamiento de IAs para rivales...")
        
        # Reconstruir historial de saldo y equipo cronológicamente
        user_cash = {}
        user_rosters = {str(u_id): set(roster) for u_id, roster in initial_rosters.items()}
        
        # Inicializar saldo a T=0 usando base de 50M de presupuesto
        for u_id, roster in initial_rosters.items():
            roster_value = sum(self.global_db.get(str(p_id), {}).get("price", 0) for p_id in roster)
            user_cash[str(u_id)] = 50000000 - roster_value

        # Registro cronológico de transacciones por usuario
        user_txs = {str(u_id): [] for u_id in initial_rosters.keys()}

        # Procesamos transacciones cronológicamente
        for item in board_data:
            t = item.get("type")
            content = item.get("content")
            if not content:
                continue
                
            if t == "market":
                for sub in content:
                    p_id = sub.get("player")
                    to_user = sub.get("to", {}).get("id")
                    amount = sub.get("amount", 0)
                    
                    if to_user and p_id:
                        to_user = str(to_user)
                        p_info = self.global_db.get(str(p_id), {})
                        p_price = p_info.get("price", 0)
                        p_inc = p_info.get("priceIncrement", 0)
                        pos_code = p_info.get("position", 0)
                        
                        team_id = str(p_info.get("teamID", ""))
                        team_name = self.teams_db.get(team_id, {}).get("name", "Desconocido")
                        tier = self._get_selection_tier(team_name)
                        
                        u_cash = user_cash.get(to_user, 20000000)
                        u_team_val = sum(self.global_db.get(str(p_id_roster), {}).get("price", 0) for p_id_roster in user_rosters.get(to_user, []))
                        
                        if p_price > 0:
                            overbid_pct = (amount - p_price) / p_price
                            if to_user not in user_txs:
                                user_txs[to_user] = []
                            user_txs[to_user].append({
                                "player_price": p_price,
                                "price_inc": p_inc,
                                "pos_code": pos_code,
                                "tier": tier,
                                "user_cash": u_cash,
                                "user_team_val": u_team_val,
                                "overbid_pct": overbid_pct
                            })
                            
                        # Actualizar estado
                        user_cash[to_user] = user_cash.get(to_user, 20000000) - amount
                        if to_user in user_rosters:
                            user_rosters[to_user].add(p_id)
                        
            elif t in ("transfer", "clause"):
                for sub in content:
                    p_id = sub.get("player")
                    f_user = sub.get("from", {}).get("id")
                    to_user = sub.get("to", {}).get("id")
                    amount = sub.get("amount", 0)
                    
                    to_user = str(to_user) if to_user is not None else None
                    f_user = str(f_user) if f_user is not None else None
                    
                    if to_user and p_id:
                        p_info = self.global_db.get(str(p_id), {})
                        p_price = p_info.get("price", 0)
                        p_inc = p_info.get("priceIncrement", 0)
                        pos_code = p_info.get("position", 0)
                        
                        team_id = str(p_info.get("teamID", ""))
                        team_name = self.teams_db.get(team_id, {}).get("name", "Desconocido")
                        tier = self._get_selection_tier(team_name)
                        
                        u_cash = user_cash.get(to_user, 20000000)
                        u_team_val = sum(self.global_db.get(str(p_id_roster), {}).get("price", 0) for p_id_roster in user_rosters.get(to_user, []))
                        
                        if p_price > 0:
                            overbid_pct = (amount - p_price) / p_price
                            if to_user not in user_txs:
                                user_txs[to_user] = []
                            user_txs[to_user].append({
                                "player_price": p_price,
                                "price_inc": p_inc,
                                "pos_code": pos_code,
                                "tier": tier,
                                "user_cash": u_cash,
                                "user_team_val": u_team_val,
                                "overbid_pct": overbid_pct
                            })
                            
                        # Actualizar estado
                        if f_user in user_cash:
                            user_cash[f_user] += amount
                        if f_user in user_rosters:
                            user_rosters[f_user].discard(p_id)
                            
                        user_cash[to_user] = user_cash.get(to_user, 20000000) - amount
                        if to_user in user_rosters:
                            user_rosters[to_user].add(p_id)
                        
            elif t == "pay":
                for sub in content:
                    u_id = sub.get("user", {}).get("id")
                    amount = sub.get("amount", 0)
                    if u_id:
                        u_id = str(u_id)
                        user_cash[u_id] = user_cash.get(u_id, 20000000) + amount
                        
            elif t == "clauseIncrement":
                for sub in content:
                    u_id = sub.get("user", {}).get("id")
                    amount = sub.get("amount", 0)
                    p_id = sub.get("player")
                    
                    u_id = str(u_id) if u_id is not None else None
                    if u_id and p_id:
                        p_info = self.global_db.get(str(p_id), {})
                        p_price = p_info.get("price", 100000)
                        p_inc = p_info.get("priceIncrement", 0)
                        pos_code = p_info.get("position", 0)
                        
                        team_id = str(p_info.get("teamID", ""))
                        team_name = self.teams_db.get(team_id, {}).get("name", "Desconocido")
                        tier = self._get_selection_tier(team_name)
                        
                        u_cash = user_cash.get(u_id, 20000000)
                        u_team_val = sum(self.global_db.get(str(p_id_roster), {}).get("price", 0) for p_id_roster in user_rosters.get(u_id, []))
                        
                        overbid_pct = amount / p_price
                        if u_id not in user_txs:
                            user_txs[u_id] = []
                        user_txs[u_id].append({
                            "player_price": p_price,
                            "price_inc": p_inc,
                            "pos_code": pos_code,
                            "tier": tier,
                            "user_cash": u_cash,
                            "user_team_val": u_team_val,
                            "overbid_pct": overbid_pct
                        })
                        
                        user_cash[u_id] = user_cash.get(u_id, 20000000) - amount
                        
            elif t == "exchange":
                f_user = content.get("from", {}).get("id")
                to_user = content.get("to", {}).get("id")
                amount = content.get("amount", 0)
                req_amount = content.get("requestedAmount", 0)
                offered = content.get("offeredPlayers", [])
                requested = content.get("requestedPlayers", [])
                
                f_user = str(f_user) if f_user is not None else None
                to_user = str(to_user) if to_user is not None else None
                
                # Actualizar estado de cash
                if f_user in user_cash:
                    user_cash[f_user] = user_cash[f_user] - amount + req_amount
                if f_user in user_rosters:
                    for p in offered:
                        user_rosters[f_user].discard(p)
                    for p in requested:
                        user_rosters[f_user].add(p)
                        
                if to_user in user_cash:
                    user_cash[to_user] = user_cash[to_user] + amount - req_amount
                if to_user in user_rosters:
                    for p in offered:
                        user_rosters[to_user].add(p)
                    for p in requested:
                        user_rosters[to_user].discard(p)

        # Guardar historial de secuencias para inferencias posteriores
        self.user_histories = user_txs

        # Validar si hay transacciones
        total_txs = sum(len(txs) for txs in user_txs.values())
        if total_txs == 0:
            print("[Advertencia] No se encontraron transacciones en el tablón para entrenar los modelos.")
            return

        if self.use_transformer:
            # Entrenamiento basado en la arquitectura Transformer
            global_X = []
            global_y = []
            
            for u_id, txs in user_txs.items():
                if not txs:
                    continue
                u_X, u_y = self._build_sequences_for_txs(txs)
                global_X.extend(u_X)
                global_y.extend(u_y)
                
            if not global_X:
                print("[Advertencia] Muestras de secuencia insuficientes para entrenar el Transformer.")
                return

            try:
                # 1. Entrenar el modelo global
                print(f"[*] Entrenando Transformer global con {len(global_X)} muestras...")
                self.global_model = BidTransformerModel()
                self._train_transformer(self.global_model, global_X, global_y, epochs=120, lr=0.005)
                self.trained = True
                print("[+] Modelo Transformer global entrenado con éxito.")
                
                # 2. Entrenar modelos individuales por Fine-Tuning
                for u_id, txs in user_txs.items():
                    if len(txs) >= 1:
                        print(f"    - Fine-tuneando Transformer para Rival ID {u_id} ({len(txs)} muestras)...")
                        user_model = BidTransformerModel()
                        user_model.load_state_dict(self.global_model.state_dict())
                        
                        u_X, u_y = self._build_sequences_for_txs(txs)
                        # Fine-tuning con menos épocas y lr más bajo
                        self._train_transformer(user_model, u_X, u_y, epochs=40, lr=0.002)
                        self.user_models[u_id] = user_model
            except Exception as e:
                print(f"[Error] Falló el entrenamiento de Transformer: {e}")
                print("[!] Degradando a fallback RandomForest...")
                self.use_transformer = False
                self.trained = False
                # Re-ejecutar entrenamiento bajo fallback RandomForest
                self.train_models(board_data, initial_rosters)

        else:
            # Fallback a RandomForestRegressor
            training_data = []
            for u_id, txs in user_txs.items():
                for tx in txs:
                    training_data.append({
                        "user_id": u_id,
                        "features": [
                            tx["player_price"],
                            tx["price_inc"],
                            tx["pos_code"],
                            tx["tier"],
                            tx["user_cash"],
                            tx["user_team_val"]
                        ],
                        "target": tx["overbid_pct"]
                    })
            
            if not training_data:
                return
                
            X_all = np.array([item["features"] for item in training_data])
            y_all = np.array([item["target"] for item in training_data])
            
            try:
                self.global_model = RandomForestRegressor(n_estimators=50, random_state=42)
                self.global_model.fit(X_all, y_all)
                print(f"[+] Modelo RandomForest global entrenado con éxito ({len(training_data)} muestras).")
                self.trained = True
            except Exception as e:
                print(f"[Error] Falló el entrenamiento del modelo RandomForest global: {e}")
                
            # Modelos específicos por rival
            user_grouped = {}
            for item in training_data:
                u_id = item["user_id"]
                if u_id not in user_grouped:
                    user_grouped[u_id] = {"X": [], "y": []}
                user_grouped[u_id]["X"].append(item["features"])
                user_grouped[u_id]["y"].append(item["target"])

            for u_id, dataset in user_grouped.items():
                if len(dataset["X"]) >= 3:
                    try:
                        user_model = RandomForestRegressor(n_estimators=30, random_state=42)
                        user_model.fit(np.array(dataset["X"]), np.array(dataset["y"]))
                        self.user_models[u_id] = user_model
                        print(f"    - Modelo RandomForest entrenado para Rival ID {u_id} ({len(dataset['X'])} muestras).")
                    except Exception as e:
                        print(f"    - [Advertencia] Error al entrenar RandomForest para {u_id}: {e}")

    def _build_sequences_for_txs(self, txs, seq_len=5):
        """
        Construye conjuntos de secuencias de longitud fija S = 5 a partir de las transacciones.
        """
        X = []
        y = []
        for i in range(len(txs)):
            seq = []
            for offset in range(-seq_len + 1, 1):
                idx = i + offset
                if idx < 0:
                    seq.append([0.0] * 7)
                else:
                    tx = txs[idx]
                    p_price = tx["player_price"] / 1e6
                    p_inc = tx["price_inc"] / 1e6
                    pos = tx["pos_code"]
                    tier = tx["tier"]
                    cash = tx["user_cash"] / 1e6
                    team_val = tx["user_team_val"] / 1e6
                    
                    prev_overbid = tx["overbid_pct"] if idx < i else 0.0
                    seq.append([p_price, p_inc, pos, tier, cash, team_val, prev_overbid])
            X.append(seq)
            y.append(txs[i]["overbid_pct"])
        return X, y

    def _train_transformer(self, model, X_list, y_list, epochs=100, lr=0.01):
        """
        Lazo de optimización de red neuronal para el Transformer.
        """
        X_tensor = torch.tensor(X_list, dtype=torch.float32)
        y_tensor = torch.tensor(y_list, dtype=torch.float32)
        
        optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
        criterion = nn.MSELoss()
        
        model.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            predictions = model(X_tensor)
            loss = criterion(predictions, y_tensor)
            loss.backward()
            optimizer.step()

    def predict_bid_premium(self, user_id, player_price, price_inc, position_name, team_name, user_cash, user_team_val):
        """
        Predice el porcentaje de sobreprecio (premium %) que un rival específico pagará por un jugador.
        """
        if not self.trained:
            return 0.02
            
        user_id = str(user_id)
        
        if self.use_transformer:
            # Obtener el historial de transacciones conocido para este rival
            history = self.user_histories.get(user_id, [])
            
            # Reconstruir la secuencia temporal de tamaño 5
            # Los primeros 4 tokens son las últimas transacciones conocidas del rival
            seq = []
            seq_len = 5
            
            for offset in range(-seq_len + 1, 0):
                idx = len(history) + offset
                if idx < 0:
                    seq.append([0.0] * 7)
                else:
                    tx = history[idx]
                    seq.append([
                        tx["player_price"] / 1e6,
                        tx["price_inc"] / 1e6,
                        tx["pos_code"],
                        tx["tier"],
                        tx["user_cash"] / 1e6,
                        tx["user_team_val"] / 1e6,
                        tx["overbid_pct"]
                    ])
            
            # El 5º token representa el contexto de puja que evaluamos ahora
            pos_code = POSITION_CODE_MAP.get(position_name, 3)
            tier = self._get_selection_tier(team_name)
            
            seq.append([
                player_price / 1e6,
                price_inc / 1e6,
                pos_code,
                tier,
                user_cash / 1e6,
                user_team_val / 1e6,
                0.0 # overbid_pct desconocido
            ])
            
            # Determinar qué modelo neuronal usar
            model = self.user_models.get(user_id, self.global_model)
            if model is None:
                return 0.02
                
            model.eval()
            with torch.no_grad():
                x_tensor = torch.tensor([seq], dtype=torch.float32)
                pred = model(x_tensor).item()
                
            # Limitar el sobreprecio predicho entre 0% y 50% de forma estable
            return float(np.clip(pred, 0.0, 0.50))
            
        else:
            # Fallback a RandomForest
            pos_code = POSITION_CODE_MAP.get(position_name, 3)
            tier = self._get_selection_tier(team_name)
            feature_vector = np.array([[player_price, price_inc, pos_code, tier, user_cash, user_team_val]])
            
            if user_id in self.user_models:
                pred = self.user_models[user_id].predict(feature_vector)[0]
            elif self.global_model is not None:
                pred = self.global_model.predict(feature_vector)[0]
            else:
                pred = 0.02
                
            return float(np.clip(pred, 0.0, 0.50))
