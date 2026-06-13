/**
 * Junior Aladdin — Operator Terminal
 * state_manager.js — Client-side state management
 *
 * Maintains a local copy of DashboardState updated via WebSocket push +
 * periodic polling. Components subscribe to state changes and re-render.
 *
 * Reference: ROADMAP_SIDE_B Step 8.11
 */

const StateManager = {
    _state: {
        connected: false,
        health: null,
        captain: null,
        execution: null,
        heads: null,
        floorSummary: null,
        market: null,
        alerts: { alerts: [], count: 0 },
        replay: null,
        cache: null,
        workspace: 'cockpit',
        activePanel: null,
        sidebarOpen: true,
        rightPanelOpen: false,
        rightPanelContent: null,
        clock: '',
    },

    _listeners: new Map(), // path -> Set<callback>

    // ── Component → Refresh Tier mapping ──
    _tierMap: {
        execution: 'HOT',
        market: 'HOT',
        alerts: 'HOT',
        captain: 'WARM',
        heads: 'WARM',
        floorSummary: 'WARM',
        health: 'COLD',
        cache: 'COLD',
        replay: 'COLD',
    },

    /**
     * Return the full current client state.
     * @returns {object}
     */
    get_state() {
        return { ...this._state };
    },

    /**
     * Get a state value by dot-separated path.
     * @param {string} path - e.g. 'captain.mood'
     * @param {*} [defaultValue]
     * @returns {*}
     */
    get(path, defaultValue = undefined) {
        const parts = path.split('.');
        let val = this._state;
        for (const p of parts) {
            if (val == null || typeof val !== 'object') return defaultValue;
            val = val[p];
        }
        return val != null ? val : defaultValue;
    },

    /**
     * Alias for get() — dot-separated path lookup.
     * @param {string} path
     * @param {*} [defaultValue]
     * @returns {*}
     */
    get_by_path(path, defaultValue = undefined) {
        return this.get(path, defaultValue);
    },

    /**
     * Update a specific component's state and notify listeners.
     * @param {string} component - e.g. 'execution', 'captain'
     * @param {*} data - new state data
     */
    update(component, data) {
        this.set(component, data);
    },

    /**
     * Get the refresh tier for a given component.
     * @param {string} component
     * @returns {'HOT'|'WARM'|'COLD'|'UNKNOWN'}
     */
    get_refresh_tier(component) {
        return this._tierMap[component] || 'UNKNOWN';
    },

    /**
     * Update a state path and notify listeners.
     * @param {string} path
     * @param {*} value
     */
    set(path, value) {
        const parts = path.split('.');
        let obj = this._state;
        for (let i = 0; i < parts.length - 1; i++) {
            if (!obj[parts[i]] || typeof obj[parts[i]] !== 'object') {
                obj[parts[i]] = {};
            }
            obj = obj[parts[i]];
        }
        obj[parts[parts.length - 1]] = value;
        this._notify(path, value);
    },

    /**
     * Batch update multiple state paths.
     * @param {object} updates - { 'path': value, ... }
     */
    batch(updates) {
        for (const [path, value] of Object.entries(updates)) {
            this.set(path, value);
        }
    },

    /**
     * Subscribe to state changes at a path.
     * @param {string} path - e.g. 'captain' or 'captain.mood'
     * @param {Function} callback - receives (newValue, oldValue)
     * @returns {Function} unsubscribe
     */
    subscribe(path, callback) {
        if (!this._listeners.has(path)) {
            this._listeners.set(path, new Set());
        }
        this._listeners.get(path).add(callback);

        // Return unsubscribe function
        return () => this._listeners.get(path)?.delete(callback);
    },

    /**
     * Subscribe and immediately invoke with current value.
     * Safe alternative to subscribe() when you need the current value.
     * @param {string} path
     * @param {Function} callback - receives (newValue)
     * @returns {Function} unsubscribe
     */
    subscribeAndCall(path, callback) {
        const unsub = this.subscribe(path, callback);
        const current = this.get(path);
        if (current !== undefined) {
            try { callback(current); } catch (e) { console.warn('[StateManager] init callback error:', e); }
        }
        return unsub;
    },

    /** @private */
    _notify(path, value) {
        // Notify exact path listeners
        const exact = this._listeners.get(path);
        if (exact) {
            exact.forEach(cb => {
                try { cb(value); } catch (e) { console.warn('[StateManager] listener error:', e); }
            });
        }

        // Notify parent path listeners (e.g., 'captain' subscribers get notified on 'captain.mood' change)
        const parts = path.split('.');
        for (let i = parts.length - 1; i > 0; i--) {
            const parentPath = parts.slice(0, i).join('.');
            const parentListeners = this._listeners.get(parentPath);
            if (parentListeners) {
                const parentValue = this.get(parentPath);
                parentListeners.forEach(cb => {
                    try { cb(parentValue); } catch (e) { console.warn('[StateManager] listener error:', e); }
                });
            }
        }
    },

    /** Get entire state snapshot (shallow copy) */
    snapshot() {
        return { ...this._state };
    },
};
