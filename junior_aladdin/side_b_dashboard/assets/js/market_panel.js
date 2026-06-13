/**
 * Junior Aladdin — Operator Terminal
 * market_panel.js — Market data component
 *
 * Displays real-time market snapshot: LTP, OHLC, Bid/Ask spread,
 * Volume, VWAP, and session phase. Auto-updates via StateManager.
 *
 * Reference: ROADMAP_SIDE_B Step 8.13
 */

const MarketPanel = {
    /** @type {HTMLElement|null} */
    _container: null,

    /**
     * Mount the market panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._render();

        // Subscribe to market state changes
        this._unsubscribe = StateManager.subscribe('market', (market) => {
            if (market) this._render();
        });
    },

    /** Unmount and clean up */
    unmount() {
        if (this._unsubscribe) this._unsubscribe();
        this._container = null;
    },

    /**
     * Update with new data.
     * @param {object} state
     */
    update(state) {
        if (state && this._container) this._render();
    },

    /** @private */
    _render() {
        if (!this._container) return;
        const market = StateManager.get('market', {});
        const ltp = market.ltp ?? 0;
        const change = market.change ?? 0;
        const changePct = market.change_percent ?? 0;
        const open = market.open ?? 0;
        const high = market.high ?? 0;
        const low = market.low ?? 0;
        const close = market.prev_close ?? 0;
        const bid = market.bid ?? null;
        const ask = market.ask ?? null;
        const volume = market.volume ?? 0;
        const vwap = market.vwap ?? null;
        const session = (market.session || 'CLOSED').toUpperCase();
        const symbol = market.symbol || 'NIFTY 50';
        const changeClass = change >= 0 ? 'text-green' : 'text-red';
        const spread = (bid !== null && ask !== null) ? (ask - bid).toFixed(2) : '--';

        // Session phase display
        const sessionLabels = {
            'PRE_OPEN': '🟡 Pre-Open',
            'OPEN': '🟢 Open',
            'CONTINUOUS': '🟢 Continuous',
            'AUCTION': '🟠 Auction',
            'CLOSING': '🔴 Closing',
            'CLOSED': '⚫ Closed',
            'POST_CLOSE': '⚫ Post-Close',
        };
        const sessionDisplay = sessionLabels[session] || session;

        // Volume formatting
        const volumeDisplay = volume >= 1e7
            ? (volume / 1e7).toFixed(2) + 'Cr'
            : volume >= 1e5
                ? (volume / 1e5).toFixed(2) + 'L'
                : volume.toLocaleString();

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">◉ ${this._escapeHtml(symbol)}</span>
                <span class="panel-card-badge refresh-hot">HOT</span>
            </div>
            <div class="panel-card-body">
                <!-- LTP + Change -->
                <div class="market-ltp-row" style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px;">
                    <span class="market-ltp" style="font-size:24px;font-weight:700;font-family:var(--font-mono);color:var(--text-primary);">
                        ${ltp.toFixed(2)}
                    </span>
                    <span class="market-change ${changeClass}" style="font-size:14px;font-weight:600;font-family:var(--font-mono);">
                        ${change >= 0 ? '+' : ''}${change.toFixed(2)} (${changePct.toFixed(2)}%)
                    </span>
                </div>

                <!-- OHLC Grid -->
                <div class="market-ohlc-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;margin-bottom:8px;">
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Open</span>
                        <span class="panel-value mono" style="font-size:11px;">${open.toFixed(2)}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">High</span>
                        <span class="panel-value mono" style="font-size:11px;">${high.toFixed(2)}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Low</span>
                        <span class="panel-value mono" style="font-size:11px;">${low.toFixed(2)}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Prev Close</span>
                        <span class="panel-value mono" style="font-size:11px;">${close.toFixed(2)}</span>
                    </div>
                </div>

                <!-- Bid / Ask Spread -->
                <div class="market-spread-row" style="display:flex;gap:8px;margin-bottom:8px;">
                    <div class="market-bidask" style="flex:1;background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Bid</div>
                        <div style="font-size:14px;font-weight:600;font-family:var(--font-mono);color:${bid !== null ? 'var(--green-500)' : 'var(--text-muted)'};">${bid !== null ? bid.toFixed(2) : '--'}</div>
                    </div>
                    <div class="market-bidask" style="flex:1;background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Ask</div>
                        <div style="font-size:14px;font-weight:600;font-family:var(--font-mono);color:${ask !== null ? 'var(--red-500)' : 'var(--text-muted)'};">${ask !== null ? ask.toFixed(2) : '--'}</div>
                    </div>
                    <div class="market-bidask" style="flex:1;background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Spread</div>
                        <div style="font-size:14px;font-weight:600;font-family:var(--font-mono);color:var(--text-secondary);">${spread}</div>
                    </div>
                </div>

                <!-- Volume + VWAP -->
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;margin-bottom:6px;">
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Volume</span>
                        <span class="panel-value mono" style="font-size:11px;">${volumeDisplay}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">VWAP</span>
                        <span class="panel-value mono" style="font-size:11px;">${vwap !== null ? vwap.toFixed(2) : '--'}</span>
                    </div>
                </div>

                <!-- Session Phase -->
                <div class="panel-row" style="border-top:1px solid var(--border-subtle);padding-top:6px;margin-top:2px;">
                    <span class="panel-label" style="font-size:10px;">Session</span>
                    <span class="panel-value" style="font-size:11px;">${sessionDisplay}</span>
                </div>
            </div>
        </div>
        `;

        this._container.innerHTML = html;
    },

    /** @private */
    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};

// Register with ComponentManager
ComponentManager.register('market', MarketPanel);
