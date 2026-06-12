let activeChatId = null;
let activeTab = "chat";

// Carga inicial y auto-suscripción
document.addEventListener("DOMContentLoaded", () => {
    // Consultar estado inicial e iniciar sondeo cada 15 segundos
    fetchStatus();
    setInterval(fetchStatus, 15000);

    // Cargar historial de conversaciones de la barra lateral
    loadChats();

    // Eventos del Input del Chat
    const chatInput = document.getElementById("chat-input");
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    document.getElementById("send-btn").addEventListener("click", sendMessage);
    document.getElementById("clear-chat").addEventListener("click", clearChat);
    document.getElementById("new-chat-btn").addEventListener("click", createNewChat);
    document.getElementById("btn-sync").addEventListener("click", triggerManualSync);
});

// --- GESTIÓN DE PESTAÑAS (TABS) ---
function switchTab(tabName) {
    activeTab = tabName;
    
    // Conmutar botones activos
    document.getElementById("tab-chat").classList.toggle("active", tabName === "chat");
    document.getElementById("tab-operations").classList.toggle("active", tabName === "operations");
    
    // Conmutar visibilidad de contenidos
    document.getElementById("chat-tab-content").style.display = tabName === "chat" ? "flex" : "none";
    document.getElementById("operations-tab-content").style.display = tabName === "operations" ? "flex" : "none";
    
    // Si abrimos operaciones, recargamos la lista
    if (tabName === "operations") {
        fetchTransactions();
    }
}

// --- SONDEO DE LIGA API (/api/status) ---
async function fetchStatus() {
    try {
        const response = await fetch("/api/status");
        if (response.status === 202) {
            updateSyncIndicator("initializing", "Inicializando IA...");
            return;
        }
        
        if (!response.ok) throw new Error("Status endpoint error");
        
        const data = await response.json();
        
        // Actualizar indicador de sincronización
        if (data.is_syncing) {
            updateSyncIndicator("syncing", "Sincronizando...");
        } else {
            updateSyncIndicator("ready", "Online");
        }

        // Actualizar caja de Mi Club
        document.getElementById("my-name").innerText = data.my_team.name;
        document.getElementById("my-balance").innerText = formatCurrency(data.my_team.balance);
        document.getElementById("my-value").innerText = formatCurrency(data.my_team.team_value);
        document.getElementById("my-players").innerText = data.my_team.player_count;

        // Actualizar pie de firma
        document.getElementById("trained-txs").innerText = data.trained_transactions;
        document.getElementById("last-update").innerText = formatTimestamp(data.last_update);

        // Actualizar sábanas de rivales
        renderRivals(data.rivals);

    } catch (error) {
        console.error("Error al obtener estado:", error);
        updateSyncIndicator("initializing", "Desconectado");
    }
}

async function triggerManualSync() {
    const btn = document.getElementById("btn-sync");
    const icon = btn.querySelector("i");
    
    btn.disabled = true;
    icon.classList.add("fa-spin");
    updateSyncIndicator("syncing", "Sincronizando...");
    
    try {
        const response = await fetch("/api/sync", { method: "POST" });
        const data = await response.json();
        
        if (response.ok) {
            // Recargar estado
            await fetchStatus();
            // Si estamos en la pestaña de operaciones, la recargamos
            if (activeTab === "operations") {
                fetchTransactions();
            }
        } else {
            alert("Error al sincronizar: " + data.message);
        }
    } catch (error) {
        console.error("Error al forzar sincronización:", error);
        alert("Error de red al sincronizar con el servidor.");
    } finally {
        btn.disabled = false;
        icon.classList.remove("fa-spin");
    }
}

function updateSyncIndicator(state, text) {
    const dot = document.querySelector(".status-dot");
    const label = document.querySelector(".status-text");
    
    dot.className = "status-dot";
    label.innerText = text;

    if (state === "syncing") {
        dot.classList.add("pulsating", "syncing");
    } else if (state === "initializing") {
        dot.classList.add("pulsating", "initializing");
    } else {
        dot.classList.add("pulsating");
    }
}

function renderRivals(rivals) {
    const container = document.getElementById("rivals-container");
    if (!rivals || rivals.length === 0) {
        container.innerHTML = `<div class="loading-placeholder">Sin rivales</div>`;
        return;
    }

    container.innerHTML = rivals.map(rival => `
        <div class="rival-card">
            <div class="rival-header">
                <span>${escapeHtml(rival.name)}</span>
                <span class="rival-cash">${formatCurrency(rival.estimated_balance)}</span>
            </div>
            <div class="rival-team-val">
                Plantilla: ${formatCurrency(rival.team_value)}
            </div>
        </div>
    `).join("");
}

// --- GESTIÓN DE CONVERSACIONES (CHATS) ---

async function loadChats() {
    try {
        const response = await fetch("/api/chats");
        const chats = await response.json();
        
        const container = document.getElementById("chats-container");
        if (chats.length === 0) {
            container.innerHTML = `<div class="loading-placeholder">Sin conversaciones. Crea una nueva (+)</div>`;
            activeChatId = null;
            clearChatView();
            return;
        }

        container.innerHTML = chats.map(chat => `
            <div class="chat-item ${chat.id === activeChatId ? 'active' : ''}" onclick="loadChat('${chat.id}')">
                <span class="chat-title-text" title="${escapeHtml(chat.title)}">${escapeHtml(chat.title)}</span>
                <button class="delete-chat-btn" onclick="deleteChat(event, '${chat.id}')" title="Borrar chat">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </div>
        `).join("");

        // Cargar por defecto la primera conversación si no hay una activa seleccionada
        if (!activeChatId && chats.length > 0) {
            loadChat(chats[0].id);
        }

    } catch (error) {
        console.error("Error al cargar chats:", error);
    }
}

async function createNewChat() {
    try {
        const response = await fetch("/api/chats", { method: "POST" });
        const newChat = await response.json();
        activeChatId = newChat.id;
        
        // Recargar sidebar e ir a la pestaña del chat
        await loadChats();
        switchTab("chat");
        
    } catch (error) {
        console.error("Error al crear chat:", error);
    }
}

async function loadChat(chatId) {
    activeChatId = chatId;
    
    // Cambiar visualmente el active en el sidebar
    const items = document.querySelectorAll(".chat-item");
    items.forEach(item => item.classList.remove("active"));
    
    try {
        const response = await fetch(`/api/chats/${chatId}`);
        const messages = await response.json();
        
        clearChatView();
        
        if (messages.length === 0) {
            appendMessage("model", "¡Hola! Soy tu consultor de Biwenger. He procesado la base de datos de tu liga y analizado el comportamiento de tus rivales mediante modelos secuenciales de Transformers. ¿En qué te puedo ayudar hoy?");
        } else {
            messages.forEach(msg => {
                appendMessage(msg.role, msg.content);
            });
        }
        
        // Marcar activo en la lista
        loadChats();
        
    } catch (error) {
        console.error("Error al cargar chat específico:", error);
    }
}

async function deleteChat(event, chatId) {
    // Evitar que el clic en borrar dispare el onclick de cargar chat
    event.stopPropagation();
    
    if (!confirm("¿Seguro que deseas eliminar esta conversación?")) return;
    
    try {
        await fetch(`/api/chats/${chatId}`, { method: "DELETE" });
        if (activeChatId === chatId) {
            activeChatId = null;
        }
        loadChats();
    } catch (error) {
        console.error("Error al eliminar chat:", error);
    }
}

function clearChatView() {
    document.getElementById("chat-log").innerHTML = "";
}

function clearChat() {
    if (activeChatId) {
        // Al hacer clear chat borramos mensajes en memoria del chat actual
        // creando una conversación fresca
        createNewChat();
    }
}

// --- ENVÍO DE MENSAJES Y CHAT ---

async function sendMessage() {
    if (!activeChatId) {
        await createNewChat();
    }

    const chatInput = document.getElementById("chat-input");
    const text = chatInput.value.trim();
    if (!text) return;

    // Agregar mensaje del usuario a la pantalla
    appendMessage("user", text);
    chatInput.value = "";

    // Añadir typing indicator
    const typingIndicator = appendTypingIndicator();
    scrollToBottom();

    try {
        const response = await fetch(`/api/chats/${activeChatId}/message`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text })
        });

        const data = await response.json();
        typingIndicator.remove();

        if (response.ok) {
            appendMessage("model", data.reply);
            
            // Actualizar la lista lateral porque el título puede haber cambiado dinámicamente
            loadChats();
        } else {
            appendMessage("model", `[Error] ${data.reply}`);
        }
    } catch (error) {
        console.error("Chat error:", error);
        typingIndicator.remove();
        appendMessage("model", "[Error de Red] No se pudo conectar con el servidor.");
    }

    scrollToBottom();
}

function sendQuickQuery(queryText) {
    document.getElementById("chat-input").value = queryText;
    sendMessage();
}

// --- HISTORIAL DE OPERACIONES DE MERCADO ---

async function fetchTransactions() {
    const container = document.getElementById("operations-log-list");
    container.innerHTML = `<div class="loading-placeholder"><i class="fa-solid fa-spinner fa-spin"></i> Cargando historial...</div>`;
    
    try {
        const response = await fetch("/api/transactions");
        const transactions = await response.json();
        
        if (transactions.length === 0) {
            container.innerHTML = `<div class="loading-placeholder">No se han registrado operaciones de mercado todavía en SQLite.</div>`;
            return;
        }

        container.innerHTML = transactions.map(tx => {
            let pillClass = "op-mercado";
            if (tx.type === "Transferencia") pillClass = "op-transferencia";
            else if (tx.type === "Pago Cláusula") pillClass = "op-clausula";
            else if (tx.type === "Incremento Cláusula") pillClass = "op-clausula";
            else if (tx.type === "Intercambio") pillClass = "op-intercambio";
            else if (tx.type === "Abono de Liga") pillClass = "op-mercado";
            else if (tx.type === "Sanción de Liga") pillClass = "op-clausula";

            return `
                <div class="operation-card">
                    <div class="operation-main">
                        <span class="operation-type-pill ${pillClass}">${escapeHtml(tx.type)}</span>
                        <div class="operation-details">${formatMarkdown(tx.details)}</div>
                    </div>
                    <div class="operation-date">
                        ${formatTimestamp(tx.date)}<br>
                        <span style="font-size: 10px; opacity: 0.6;">${formatFullDate(tx.date)}</span>
                    </div>
                </div>
            `;
        }).join("");

    } catch (error) {
        console.error("Error al cargar operaciones:", error);
        container.innerHTML = `<div class="loading-placeholder" style="color: var(--accent-red);">No se pudo cargar el historial de mercado.</div>`;
    }
}

// --- AUXILIARES DOM Y FORMATEO ---

function appendMessage(sender, text) {
    const chatLog = document.getElementById("chat-log");
    const wrapper = document.createElement("div");
    wrapper.className = `msg-wrapper ${sender}`;

    const label = document.createElement("div");
    label.className = "msg-sender";
    label.innerText = sender === "user" ? "Tú" : "Biwenger AI Expert";

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.innerHTML = sender === "model" ? formatMarkdown(text) : escapeHtml(text);

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    chatLog.appendChild(wrapper);
    scrollToBottom();
}

function appendTypingIndicator() {
    const chatLog = document.getElementById("chat-log");
    const wrapper = document.createElement("div");
    wrapper.className = "msg-wrapper model typing-indicator-wrapper";

    const label = document.createElement("div");
    label.className = "msg-sender";
    label.innerText = "Biwenger AI Expert";

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.innerHTML = `
        <div class="typing-dots">
            <div class="dot"></div>
            <div class="dot"></div>
            <div class="dot"></div>
        </div>
    `;

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    chatLog.appendChild(wrapper);
    return wrapper;
}

function scrollToBottom() {
    const chatLog = document.getElementById("chat-log");
    chatLog.scrollTop = chatLog.scrollHeight;
}

function formatCurrency(amount) {
    if (amount >= 1e6) {
        return (amount / 1e6).toFixed(2) + "M €";
    }
    return amount.toLocaleString("es-ES") + " €";
}

function formatTimestamp(ts) {
    if (!ts) return "-";
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatFullDate(ts) {
    if (!ts) return "-";
    const date = new Date(ts * 1000);
    return date.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit" });
}

function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatMarkdown(text) {
    let html = text.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    
    html = html.replace(/^### (.*?)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.*?)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.*?)$/gm, "<h1>$1</h1>");
    
    let lines = html.split("\n");
    let inTable = false;
    let tableHtml = "";
    
    for (let i = 0; i < lines.length; i++) {
        let line = lines[i].trim();
        if (line.startsWith("|") && line.endsWith("|")) {
            if (!inTable) {
                inTable = true;
                tableHtml = "<table>";
            }
            let cells = line.split("|").map(c => c.trim()).filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
            if (cells.every(c => c.startsWith("-"))) {
                continue;
            }
            let isHeader = (tableHtml === "<table>");
            tableHtml += "<tr>";
            for (let cell of cells) {
                tableHtml += isHeader ? `<th>${cell}</th>` : `<td>${cell}</td>`;
            }
            tableHtml += "</tr>";
            lines[i] = "";
        } else {
            if (inTable) {
                inTable = false;
                tableHtml += "</table>";
                lines[i] = tableHtml + "\n" + lines[i];
            }
        }
    }
    if (inTable) {
        tableHtml += "</table>";
        lines.push(tableHtml);
    }
    
    html = lines.filter(l => l !== "").join("\n");
    html = html.replace(/^\-\s+(.*?)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*?<\/li>)+/gs, "<ul>$&</ul>");
    html = html.replace(/\n\n/g, "<br><br>");
    html = html.replace(/\n/g, "<br>");
    
    return html;
}
