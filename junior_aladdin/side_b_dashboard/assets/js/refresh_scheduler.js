/**
 * Junior Aladdin — Operator Terminal
 * refresh_scheduler.js — HOT/WARM/COLD refresh cycle manager
 *
 * Manages the three-tier refresh cycle:
 *   HOT  (500ms)  — execution, market, alerts
 *   WARM (3s)     — head reports, captain, floor summary
 *   COLD (30s)    — reference data, logs, history (or on-demand)
 *
 * On WebSocket message: immediately update relevant state.
 * On user focus: prioritize visible components.
 *
 * Reference: ROADMAP_SIDE_B Step 8.11
 */

const RefreshScheduler = {
    _api: null, // set via init(api)

    _intervals: {
        hot: 500,
        warm: 3000,
        cold: 30000,
    },

    _timers: { hot: null, warm: null, cold: null },
    _paused: false,
    _userFocus: false, // true when user is interacting with the dashboard
    _lastActivity: Date.now(),

    // ── Callback registries ──
    // Components register render callbacks that the scheduler calls when data arrives
    _hotCallbacks: [],
    _warmCallbacks: [],
    _coldCallbacks: [],
    _wsHandlers: new Map(), // channel -> callback

    /**
     * Initialize the scheduler with the API client.
     * @param {ApiClient} apiClient
     */
    init(apiClient) {
        this._api = apiClient;

        // Track user activity
        document.addEventListener('mousemove', () => this._markActivity());
        document.addEventListener('keydown', () => this._markActivity());
        document.addEventListener('click', () => this._markActivity());
        document.addEventListener('focus', () => this._markActivity());

        // Pause when tab hidden
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.pause();
            } else {
                this.resume();
            }
        });
    },

    /** @private */
    _markActivity() {
        this._lastActivity = Date.now();
        this._userFocus = true;
    },

    // ── Interval configuration ──

    /**
     * Set custom refresh intervals (in milliseconds).
     * @param {object} intervals - { hot?, warm?, cold? }
     */
    setIntervals(intervals = {}) {
        if (intervals.hot != null) this._intervals.hot = intervals.hot;
        if (intervals.warm != null) this._intervals.warm = intervals.warm;
        if (intervals.cold != null) this._intervals.cold = intervals.cold;
    },

    // ── Polling ──

    /**
     * Start all three refresh tiers.
     */
    start() {
        if (!this._api) {
            console.warn('[RefreshScheduler] API client not set. Call init(api) first.');
            return;
        }
        this._scheduleHot();
        this._scheduleWarm();
        this._scheduleCold();
    },

    /**
     * Stop all refresh tiers.
     */
    stop() {
        Object.values(this._timers).forEach(t => {
            if (t) { clearTimeout(t); }
        });
        this._timers = { hot: null, warm: null, cold: null };
    },

    /**
     * Pause all polling (e.g., when tab is hidden).
     */
    pause() {
        this._paused = true;
    },

    /**
     * Resume polling.
     */
    resume() {
        this._paused = false;
        this._markActivity();
        // Immediately trigger a hot poll to catch up
        if (this._timers.hot === null) {
            this._scheduleHot();
        }
    },

    /**
     * Check if the scheduler is currently paused.
     * @returns {boolean}
     */
    isPaused() {
        return this._paused;
    },

    /**
     * Get current intervals.
     * @returns {object}
     */
    getIntervals() {
        return { ...this._intervals };
    },

    // ── Register poll callbacks ──

    /**
     * Register a callback to run after each HOT poll.
     * @param {Function} fn - receives (execution, market, alerts)
     */
    onHotPoll(fn) {
        this._hotCallbacks.push(fn);
    },

    /**
     * Register a callback to run after each WARM poll.
     * @param {Function} fn - receives (captain, heads)
     */
    onWarmPoll(fn) {
        this._warmCallbacks.push(fn);
    },

    /**
     * Register a callback to run after each COLD poll.
     * @param {Function} fn - receives (health, cache)
     */
    onColdPoll(fn) {
        this._coldCallbacks.push(fn);
    },

    /**
     * Register a handler for WebSocket message channels.
     * @param {string} channel
     * @param {Function} callback - receives (data)
     */
    onWsMessage(channel, callback) {
        this._wsHandlers.set(channel, callback);
    },

    // ── Internal scheduling ──

    /** @private */
    async _scheduleHot() {
        if (this._paused) {
            this._timers.hot = setTimeout(() => this._scheduleHot(), 500);
            return;
        }

        try {
            const api = this._api;
            const results = await Promise.allSettled([
                api.getExecutionState(),
                api.getMarketSnapshot(),
                api.getAlerts(),
            ]);

            const execution = results[0].status === 'fulfilled' ? results[0].value : null;
            const market = results[1].status === 'fulfilled' ? results[1].value : null;
            const alerts = results[2].status === 'fulfilled' ? results[2].value : null;

            if (execution) StateManager.update('execution', execution);
            if (market) StateManager.update('market', market);
            if (alerts) StateManager.update('alerts', alerts);

            // Notify registered callbacks
            this._hotCallbacks.forEach(cb => {
                try { cb(execution, market, alerts); } catch (e) { console.warn('[RefreshScheduler] hot callback error:', e); }
            });
        } catch (e) {
            // Poll error — silently retry next cycle
        }

        this._timers.hot = setTimeout(() => this._scheduleHot(), this._intervals.hot);
    },

    /** @private */
    async _scheduleWarm() {
        if (this._paused) {
            this._timers.warm = setTimeout(() => this._scheduleWarm(), 1000);
            return;
        }

        try {
            const api = this._api;
            const results = await Promise.allSettled([
                api.getCaptainState(),
                api.getHeads(),
            ]);

            const captain = results[0].status === 'fulfilled' ? results[0].value : null;
            const heads = results[1].status === 'fulfilled' ? results[1].value : null;

            if (captain) StateManager.update('captain', captain);
            if (heads) {
                StateManager.update('heads', heads);
                if (heads.floor_summary) {
                    StateManager.update('floorSummary', heads.floor_summary);
                }
            }

            this._warmCallbacks.forEach(cb => {
                try { cb(captain, heads); } catch (e) { console.warn('[RefreshScheduler] warm callback error:', e); }
            });
        } catch (e) { /* poll error */ }

        this._timers.warm = setTimeout(() => this._scheduleWarm(), this._intervals.warm);
    },

    /** @private */
    async _scheduleCold() {
        if (this._paused) {
            this._timers.cold = setTimeout(() => this._scheduleCold(), 1000);
            return;
        }

        try {
            const api = this._api;
            const results = await Promise.allSettled([
                api.getHealth(),
                api.getCacheStats(),
            ]);

            const health = results[0].status === 'fulfilled' ? results[0].value : null;
            const cache = results[1].status === 'fulfilled' ? results[1].value : null;

            if (health) StateManager.update('health', health);
            if (cache) StateManager.update('cache', cache);

            this._coldCallbacks.forEach(cb => {
                try { cb(health, cache); } catch (e) { console.warn('[RefreshScheduler] cold callback error:', e); }
            });
        } catch (e) { /* poll error */ }

        this._timers.cold = setTimeout(() => this._scheduleCold(), this._intervals.cold);
    },

    // ── WebSocket message handling ──

    /**
     * Handle an incoming WebSocket message.
     * Updates state immediately and notifies channel handlers.
     * @param {object} msg - { channel, data, timestamp }
     */
    handleWsMessage(msg) {
        if (!msg || !msg.channel) return;

        // Update state based on channel
        switch (msg.channel) {
            case 'execution':
                StateManager.update('execution', msg.data);
                break;
            case 'market':
                StateManager.update('market', msg.data);
                break;
            case 'health':
                StateManager.update('health', msg.data);
                break;
            case 'alerts':
                StateManager.update('alerts', msg.data);
                break;
        }

        // Notify registered channel handlers
        const handler = this._wsHandlers.get(msg.channel);
        if (handler) {
            try { handler(msg.data); } catch (e) { console.warn('[RefreshScheduler] WS handler error:', e); }
        }
    }
};
