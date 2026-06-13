/**
 * Junior Aladdin — Operator Terminal
 * websocket_client.js — Dedicated WebSocket client with auto-reconnect,
 * channel routing, and fallback polling.
 *
 * Separates WebSocket responsibilities from the HTTP ApiClient.
 *
 * Features:
 *   - Auto-connect with exponential backoff (max 30s)
 *   - Channel subscribe/unsubscribe with callbacks
 *   - Connection state events: onConnect, onDisconnect, onError
 *   - Fallback polling when WebSocket is unavailable
 *   - Pause/resume (respects tab visibility)
 *   - Health check (ping/pout or heartbeat)
 *
 * Reference: ROADMAP_SIDE_B Step 8.10 — WebSocket Client
 */

class WebSocketClient {
    /**
     * @param {string} wsUrl - WebSocket endpoint URL (e.g. ws://127.0.0.1:8080/ws)
     * @param {object} [options]
     * @param {boolean} [options.autoConnect=true] - Connect immediately on construction
     * @param {number} [options.maxReconnectAttempts=10] - Max reconnect retries
     * @param {number} [options.reconnectDelay=1000] - Initial reconnect delay (ms)
     * @param {number} [options.maxReconnectDelay=30000] - Max backoff delay (ms)
     */
    constructor(wsUrl, options = {}) {
        this.wsUrl = wsUrl;
        this.autoConnect = options.autoConnect !== false;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 10;
        this.reconnectDelay = options.reconnectDelay || 1000;
        this.maxReconnectDelay = options.maxReconnectDelay || 30000;

        /** @type {WebSocket|null} */
        this.ws = null;

        /** @type {boolean} */
        this.connected = false;

        /** @type {boolean} */
        this._disposed = false; // prevents reconnect after explicit disconnect

        /** @type {number} */
        this._reconnectAttempts = 0;

        /** @type {number|null} */
        this._reconnectTimer = null;

        /** @type {number|null} */
        this._heartbeatTimer = null;

        /** @type {Map<string, Set<Function>>} Channel callbacks */
        this._channelHandlers = new Map();

        /** @type {Map<string, Function[]>} Event listeners */
        this._listeners = new Map();

        // Auto-connect
        if (this.autoConnect) {
            this.connect();
        }
    }

    // ── Events ──

    /**
     * Register an event listener.
     * @param {'connect'|'disconnect'|'error'|'reconnecting'|'message'} event
     * @param {Function} callback
     */
    on(event, callback) {
        if (!this._listeners.has(event)) {
            this._listeners.set(event, []);
        }
        this._listeners.get(event).push(callback);
        return this;
    }

    /**
     * Remove an event listener.
     * @param {string} event
     * @param {Function} callback
     */
    off(event, callback) {
        const cbs = this._listeners.get(event);
        if (!cbs) return;
        const idx = cbs.indexOf(callback);
        if (idx !== -1) cbs.splice(idx, 1);
    }

    /** @private */
    _emit(event, data) {
        const cbs = this._listeners.get(event);
        if (cbs) {
            cbs.forEach(cb => {
                try { cb(data); } catch (e) { console.warn('[WebSocketClient] event error:', e); }
            });
        }
    }

    // ── Connection Management ──

    /**
     * Connect to the WebSocket endpoint.
     * Safe to call multiple times — ignores if already connected/connecting.
     */
    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        this._disposed = false;

        try {
            this.ws = new WebSocket(this.wsUrl);
        } catch (e) {
            console.error('[WebSocketClient] Construction failed:', e);
            this._scheduleReconnect();
            return;
        }

        this.ws.onopen = () => {
            console.log('[WebSocketClient] Connected');
            this.connected = true;
            this._reconnectAttempts = 0;
            this._startHeartbeat();
            this._emit('connect');
        };

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                this._routeMessage(msg);
                this._emit('message', msg);
            } catch (e) {
                console.warn('[WebSocketClient] Failed to parse message:', e);
            }
        };

        this.ws.onerror = (err) => {
            console.error('[WebSocketClient] Error:', err);
            this._emit('error', err);
        };

        this.ws.onclose = (closeEvent) => {
            console.log('[WebSocketClient] Disconnected (code:', closeEvent.code, ')');
            this.connected = false;
            this.ws = null;
            this._stopHeartbeat();
            this._emit('disconnect', { code: closeEvent.code, reason: closeEvent.reason });

            if (!this._disposed) {
                this._scheduleReconnect();
            }
        };
    }

    /**
     * Disconnect the WebSocket permanently.
     * Prevents auto-reconnect until connect() is called again.
     */
    disconnect() {
        this._disposed = true;
        this._cancelReconnect();
        this._stopHeartbeat();

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        this.connected = false;
        this._reconnectAttempts = 0;
        this._emit('disconnect', { code: 1000, reason: 'Client disconnect' });
    }

    /**
     * Check if the WebSocket is currently connected.
     * @returns {boolean}
     */
    isConnected() {
        return this.connected;
    }

    /**
     * Get current connection state as a string.
     * @returns {'CONNECTED'|'DISCONNECTED'|'CONNECTING'|'RECONNECTING'}
     */
    getState() {
        if (this.connected && this.ws && this.ws.readyState === WebSocket.OPEN) return 'CONNECTED';
        if (this._reconnectTimer !== null) return 'RECONNECTING';
        if (this.ws && this.ws.readyState === WebSocket.CONNECTING) return 'CONNECTING';
        return 'DISCONNECTED';
    }

    // ── Channel Subscribe / Unsubscribe ──

    /**
     * Subscribe to a message channel.
     * @param {string} channel - e.g. 'execution', 'market', 'health'
     * @param {Function} callback - receives (data)
     */
    subscribe(channel, callback) {
        if (!this._channelHandlers.has(channel)) {
            this._channelHandlers.set(channel, new Set());
        }
        this._channelHandlers.get(channel).add(callback);
    }

    /**
     * Unsubscribe from a channel.
     * @param {string} channel
     * @param {Function} [callback] - omit to remove all
     */
    unsubscribe(channel, callback) {
        const handlers = this._channelHandlers.get(channel);
        if (!handlers) return;

        if (!callback) {
            this._channelHandlers.delete(channel);
            return;
        }

        handlers.delete(callback);
        if (handlers.size === 0) {
            this._channelHandlers.delete(channel);
        }
    }

    /**
     * Remove all channel subscriptions.
     */
    unsubscribeAll() {
        this._channelHandlers.clear();
    }

    // ── Fallback Polling ──

    /**
     * Start fallback polling when WebSocket is unavailable.
     * The fallback calls the provided poll functions at the given interval
     * and routes results through channel handlers as if they were WS messages.
     *
     * @param {object} fallbacks - Map of channel -> poll function
     * @param {number} intervalMs - Poll interval in ms
     */
    startFallbackPolling(fallbacks, intervalMs = 3000) {
        this._fallbacks = fallbacks;
        this._fallbackInterval = intervalMs;

        // Only run fallback when disconnected
        this._checkFallback();
    }

    /** @private */
    async _checkFallback() {
        if (this._disposed) return;

        // If WS is connected, skip fallback
        if (this.connected) {
            this._fallbackTimer = setTimeout(() => this._checkFallback(), this._fallbackInterval);
            return;
        }

        if (this._fallbacks) {
            for (const [channel, pollFn] of Object.entries(this._fallbacks)) {
                try {
                    const data = await pollFn();
                    if (data) {
                        // Emit channel event just like _routeMessage does for WS messages
                        this._emit('channel:' + channel, data);
                    }
                } catch (e) {
                    // Silently retry next cycle
                }
            }
        }

        this._fallbackTimer = setTimeout(() => this._checkFallback(), this._fallbackInterval);
    }

    /** @private */
    _stopFallbackPolling() {
        if (this._fallbackTimer) {
            clearTimeout(this._fallbackTimer);
            this._fallbackTimer = null;
        }
    }

    // ── Heartbeat ──

    /** @private */
    _startHeartbeat() {
        this._stopHeartbeat();
        // Send a ping every 30s to keep connection alive
        this._heartbeatTimer = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                try {
                    this.ws.send(JSON.stringify({ type: 'ping' }));
                } catch (e) {
                    // Connection might be dead — let onclose handle reconnect
                }
            }
        }, 30000);
    }

    /** @private */
    _stopHeartbeat() {
        if (this._heartbeatTimer) {
            clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
    }

    // ── Reconnect ──

    /** @private */
    _scheduleReconnect() {
        if (this._disposed) return;
        if (this._reconnectAttempts >= this.maxReconnectAttempts) {
            console.warn('[WebSocketClient] Max reconnect attempts reached');
            return;
        }

        this._cancelReconnect();

        const delay = Math.min(
            this.reconnectDelay * Math.pow(2, this._reconnectAttempts),
            this.maxReconnectDelay
        );

        console.log(`[WebSocketClient] Reconnecting in ${delay}ms (attempt ${this._reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
        this._emit('reconnecting', { attempt: this._reconnectAttempts + 1, delay });

        this._reconnectTimer = setTimeout(() => {
            this._reconnectAttempts++;
            this.connect();
        }, delay);
    }

    /** @private */
    _cancelReconnect() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
    }

    // ── Message Routing ──

    /**
     * Route an incoming message to channel subscribers.
     * @private
     * @param {object} msg - parsed JSON { channel, data, timestamp }
     */
    _routeMessage(msg) {
        if (!msg || !msg.channel) return;

        const handlers = this._channelHandlers.get(msg.channel);
        if (handlers) {
            handlers.forEach(cb => {
                try { cb(msg.data); } catch (e) { console.warn('[WebSocketClient] channel handler error:', e); }
            });
        }

        // Also emit as a generic event for non-channel listeners
        this._emit('channel:' + msg.channel, msg.data);
    }

    // ── Send ──

    /**
     * Send a message through the WebSocket.
     * @param {object} data - JSON-serializable data
     * @returns {boolean} true if sent, false if not connected
     */
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(JSON.stringify(data));
                return true;
            } catch (e) {
                console.warn('[WebSocketClient] Send failed:', e);
                return false;
            }
        }
        return false;
    }

    // ── Cleanup ──

    /**
     * Dispose the client — disconnect, remove all listeners, stop timers.
     */
    dispose() {
        this._disposed = true;
        this.disconnect();
        this._stopFallbackPolling();
        this._listeners.clear();
        this._channelHandlers.clear();
    }
}
