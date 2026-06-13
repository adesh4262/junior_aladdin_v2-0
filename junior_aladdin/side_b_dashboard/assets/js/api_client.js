/**
 * Junior Aladdin — Operator Terminal
 * api_client.js — HTTP + WebSocket client for backend API
 *
 * Reference: ROADMAP_SIDE_B Step 8.10
 */

class ApiClient {
    /**
     * @param {string} baseUrl - API base URL (default: http://127.0.0.1:8080)
     */
    constructor(baseUrl = 'http://127.0.0.1:8080') {
        this.baseUrl = baseUrl;
        this.wsUrl = baseUrl.replace(/^http/, 'ws') + '/ws';
        this.ws = null;
        this.wsReconnectTimer = null;
        this.wsReconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.wsSubscriptions = new Map(); // channel -> callback
        this.connected = false;
        this._listeners = new Map(); // event -> callback[]
    }

    // ── Events ──

    /**
     * Subscribe to client events.
     * @param {'connect'|'disconnect'|'error'|'ws_message'} event
     * @param {Function} callback
     */
    on(event, callback) {
        if (!this._listeners.has(event)) {
            this._listeners.set(event, []);
        }
        this._listeners.get(event).push(callback);
        return this;
    }

    /** @private */
    _emit(event, data) {
        const cbs = this._listeners.get(event) || [];
        cbs.forEach(cb => { try { cb(data); } catch (e) { console.warn('[ApiClient] listener error:', e); } });
    }

    // ── HTTP Methods ──

    /**
     * GET request.
     * @param {string} path - e.g. '/api/health'
     * @param {object} [params] - query params
     * @returns {Promise<object>}
     */
    async get(path, params = {}) {
        const url = new URL(this.baseUrl + path);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null) url.searchParams.set(k, v);
        });
        const res = await fetch(url.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
        });
        if (!res.ok) {
            const body = await res.text().catch(() => '');
            throw new ApiError(res.status, `GET ${path} failed: ${res.statusText}`, body);
        }
        return res.json();
    }

    /**
     * POST request.
     * @param {string} path
     * @param {object} [body]
     * @returns {Promise<object>}
     */
    async post(path, body = {}) {
        const res = await fetch(this.baseUrl + path, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new ApiError(res.status, `POST ${path} failed: ${data.detail || res.statusText}`, data);
        }
        return res.json();
    }

    // ── API Endpoints ──

    /** @returns {Promise<object>} Root server metadata */
    async getRoot() {
        return this.get('/');
    }

    /** @returns {Promise<object>} System health */
    async getHealth() {
        return this.get('/api/health');
    }

    /** @param {string} component @returns {Promise<object>} */
    async getComponentHealth(component) {
        return this.get(`/api/health/${encodeURIComponent(component)}`);
    }

    /** @returns {Promise<object>} Data health */
    async getDataHealth() {
        return this.get('/api/health/data');
    }

    /** @returns {Promise<object>} Connections */
    async getConnections() {
        return this.get('/api/health/connections');
    }

    // Captain
    /** @returns {Promise<object>} */
    async getCaptainState() { return this.get('/api/captain/state'); }
    /** @returns {Promise<object>} */
    async getCaptainStory() { return this.get('/api/captain/story'); }
    /** @returns {Promise<object>} */
    async getCaptainReason() { return this.get('/api/captain/reason'); }
    /** @returns {Promise<object>} */
    async getCaptainPlans() { return this.get('/api/captain/plans'); }

    // Heads
    /** @returns {Promise<object>} */
    async getHeads() { return this.get('/api/heads'); }
    /** @param {string} name @returns {Promise<object>} */
    async getHeadDetail(name) { return this.get(`/api/heads/${encodeURIComponent(name)}`); }
    /** @returns {Promise<object>} */
    async getFloorSummary() { return this.get('/api/heads/floor-summary'); }

    // Execution
    /** @returns {Promise<object>} */
    async getExecutionState() { return this.get('/api/execution/state'); }
    /** @returns {Promise<object>} */
    async getExecutionPosition() { return this.get('/api/execution/position'); }
    /** @returns {Promise<object>} */
    async getExecutionOrders() { return this.get('/api/execution/orders'); }
    /** @returns {Promise<object>} */
    async getExecutionBlocked() { return this.get('/api/execution/blocked'); }

    // Market
    /** @returns {Promise<object>} */
    async getMarketSnapshot() { return this.get('/api/market/snapshot'); }
    /** @returns {Promise<object>} */
    async getMarketChart() { return this.get('/api/market/chart'); }
    /** @returns {Promise<object>} */
    async getMarketSession() { return this.get('/api/market/session'); }

    // Memory
    /** @returns {Promise<object>} */
    async getMemoryTrades() { return this.get('/api/memory/trades'); }
    /** @returns {Promise<object>} */
    async getMemoryDecisions() { return this.get('/api/memory/decisions'); }
    /** @returns {Promise<object>} */
    async getMemoryEvents() { return this.get('/api/memory/events'); }

    // Alerts
    /** @returns {Promise<object>} */
    async getAlerts() { return this.get('/api/alerts'); }
    /** @param {object} [filters] @returns {Promise<object>} */
    async getAlertHistory(filters = {}) { return this.get('/api/alerts/history', filters); }
    /** @param {string} alertId @returns {Promise<object>} */
    async acknowledgeAlert(alertId) { return this.post('/api/alerts/acknowledge', { alert_id: alertId }); }

    // Controls
    /** @param {string} mode @param {string} [reason] @returns {Promise<object>} */
    async setMode(mode, reason = '') { return this.post('/api/control/mode', { mode, reason }); }
    /** @param {number} limit @param {string} [reason] @returns {Promise<object>} */
    async setCapital(limit, reason = '') { return this.post('/api/control/capital', { capital_limit: limit, reason }); }
    /** @param {string} state @param {string} reason @returns {Promise<object>} */
    async setKillSwitch(state, reason) { return this.post('/api/control/kill-switch', { state, reason }); }
    /** @param {string} reason @param {string} [tradeId] @returns {Promise<object>} */
    async confirmOverride(reason, tradeId) { return this.post('/api/control/override', { override_confirmation: true, reason, trade_id: tradeId || null }); }
    /** @param {string} [broker] @param {string} [reason] @returns {Promise<object>} */
    async requestReconnect(broker = 'primary', reason = '') { return this.post('/api/control/reconnect', { target: broker, reason }); }
    /** @param {number} [balance] @param {string} reason @returns {Promise<object>} */
    async resetAccount(balance = 100000, reason) { return this.post('/api/control/account/reset', { confirm: true, new_balance: balance, reason }); }

    // Replay
    /** @returns {Promise<object>} */
    async getReplaySessions() { return this.get('/api/replay/sessions'); }
    /** @param {object} [config] @returns {Promise<object>} */
    async startReplay(config = {}) { return this.post('/api/replay/start', config); }
    /** @returns {Promise<object>} */
    async stopReplay() { return this.post('/api/replay/stop'); }
    /** @param {number} speed @returns {Promise<object>} */
    async setReplaySpeed(speed) { return this.post('/api/replay/speed', { speed }); }
    /** @returns {Promise<object>} */
    async getReplayState() { return this.get('/api/replay/state'); }
    /** @returns {Promise<object>} */
    async getReplayData() { return this.get('/api/replay/data'); }

    // Debug
    /** @returns {Promise<object>} */
    async getCacheStats() { return this.get('/api/debug/cache-stats'); }
    /** @returns {Promise<object>} */
    async getDebugState() { return this.get('/api/debug/state'); }

    // ── WebSocket ──

    /**
     * Connect to the WebSocket endpoint.
     * Auto-reconnects on disconnect with exponential backoff.
     */
    connectWebSocket() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        try {
            this.ws = new WebSocket(this.wsUrl);
        } catch (e) {
            console.error('[ApiClient] WebSocket construction failed:', e);
            this._scheduleReconnect();
            return;
        }

        this.ws.onopen = () => {
            console.log('[ApiClient] WebSocket connected');
            this.connected = true;
            this.wsReconnectAttempts = 0;
            this._emit('connect');
        };

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                this._emit('ws_message', msg);
                // Notify channel subscribers
                if (msg.channel && this.wsSubscriptions.has(msg.channel)) {
                    const cbs = this.wsSubscriptions.get(msg.channel);
                    cbs.forEach(cb => { try { cb(msg.data); } catch (e) { console.warn('[ApiClient] channel handler error:', e); } });
                }
            } catch (e) {
                console.warn('[ApiClient] Failed to parse WS message:', e);
            }
        };

        this.ws.onerror = (err) => {
            console.error('[ApiClient] WebSocket error:', err);
            this._emit('error', err);
        };

        this.ws.onclose = () => {
            console.log('[ApiClient] WebSocket disconnected');
            this.connected = false;
            this.ws = null;
            this._emit('disconnect');
            this._scheduleReconnect();
        };
    }

    /**
     * Disconnect the WebSocket.
     */
    disconnectWebSocket() {
        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
            this.wsReconnectTimer = null;
        }
        this.wsReconnectAttempts = this.maxReconnectAttempts; // prevent reconnect
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }

    /**
     * Subscribe to a WebSocket channel.
     * @param {string} channel
     * @param {Function} callback - receives data object
     */
    subscribe(channel, callback) {
        if (!this.wsSubscriptions.has(channel)) {
            this.wsSubscriptions.set(channel, []);
        }
        this.wsSubscriptions.get(channel).push(callback);
    }

    /**
     * Unsubscribe from a WebSocket channel.
     * @param {string} channel
     * @param {Function} [callback] - omit to remove all
     */
    unsubscribe(channel, callback) {
        if (!this.wsSubscriptions.has(channel)) return;
        if (!callback) {
            this.wsSubscriptions.delete(channel);
            return;
        }
        const cbs = this.wsSubscriptions.get(channel);
        const idx = cbs.indexOf(callback);
        if (idx !== -1) cbs.splice(idx, 1);
    }

    /** @private */
    _scheduleReconnect() {
        if (this.wsReconnectAttempts >= this.maxReconnectAttempts) return;
        const delay = Math.min(1000 * Math.pow(2, this.wsReconnectAttempts), 30000);
        console.log(`[ApiClient] Reconnecting in ${delay}ms (attempt ${this.wsReconnectAttempts + 1})`);
        this.wsReconnectTimer = setTimeout(() => {
            this.wsReconnectAttempts++;
            this.connectWebSocket();
        }, delay);
    }
}

/**
 * API error with status code and response body.
 */
class ApiError extends Error {
    constructor(status, message, body) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.body = body;
    }
}
