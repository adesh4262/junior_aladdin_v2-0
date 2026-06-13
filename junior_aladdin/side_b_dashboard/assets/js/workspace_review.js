/**
 * Junior Aladdin — Operator Terminal
 * workspace_review.js — Review Workspace
 *
 * Post-session review workspace showing trade journal, decision history,
 * blocked actions, and session performance metrics.
 *
 * Data sourced from Side C read models via memory API routes.
 *
 * Reference: ROADMAP_SIDE_B Step 8.19 — Review Workspace
 */

const WorkspaceReview = {
    /** @type {HTMLElement|null} */
    _container: null,

    /** @type {object} Cached review data */
    _data: {
        trades: [],
        decisions: [],
        blocking: [],
        health: null,
    },

    /** @type {Function|null} State subscription */
    _stateUnsub: null,

    /**
     * Render the review workspace into a container.
     * @param {HTMLElement} container
     */
    render(container) {
        this._container = container;
        this._renderLayout();
        this._loadAllData();

        // Subscribe to health changes for live session info
        this._stateUnsub = StateManager.subscribe('health', (health) => {
            if (health && this._container) {
                this._data.health = health;
                this._updateSessionInfo(health);
            }
        });
    },

    /** Unmount and clean up */
    unmount() {
        if (this._stateUnsub) {
            this._stateUnsub();
            this._stateUnsub = null;
        }
        this._container = null;
    },

    // ── Layout ──

    /** @private */
    _renderLayout() {
        if (!this._container) return;

        this._container.innerHTML = `
            <div class="review-layout">
                <!-- Left: Main Content -->
                <div class="review-main">
                    <!-- Session Summary -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">📋 Session Review</span>
                            <span class="panel-card-badge refresh-cold">COLD</span>
                        </div>
                        <div class="panel-card-body" id="review-session-info">
                            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:8px;">
                                <div class="review-stat">
                                    <div class="review-stat-label">Trades</div>
                                    <div class="review-stat-value" id="review-trade-count">—</div>
                                </div>
                                <div class="review-stat">
                                    <div class="review-stat-label">Decisions</div>
                                    <div class="review-stat-value" id="review-decision-count">—</div>
                                </div>
                                <div class="review-stat">
                                    <div class="review-stat-label">Blocked</div>
                                    <div class="review-stat-value" id="review-blocked-count">0</div>
                                </div>
                                <div class="review-stat">
                                    <div class="review-stat-label">PnL</div>
                                    <div class="review-stat-value" id="review-pnl">—</div>
                                </div>
                            </div>
                            <div class="panel-row">
                                <span class="panel-label">Mode</span>
                                <span class="panel-value" id="review-mode">—</span>
                            </div>
                            <div class="panel-row">
                                <span class="panel-label">Session</span>
                                <span class="panel-value" id="review-session-date">${Formatters.sessionDate()}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Trade Journal -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">📈 Trade Journal</span>
                            <span class="panel-card-badge" id="review-trades-badge">Loading...</span>
                        </div>
                        <div class="panel-card-body review-data-stream" id="review-trades-list">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-block" style="width:100%;"></div>
                                <div class="skeleton skeleton-block" style="width:90%;"></div>
                                <div class="skeleton skeleton-block" style="width:95%;"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Decision History -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">🧠 Decision History</span>
                            <span class="panel-card-badge" id="review-decisions-badge">Loading...</span>
                        </div>
                        <div class="panel-card-body review-data-stream" id="review-decisions-list">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-block" style="width:100%;"></div>
                                <div class="skeleton skeleton-block" style="width:85%;"></div>
                                <div class="skeleton skeleton-block" style="width:70%;"></div>
                                <div class="skeleton skeleton-block" style="width:95%;"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Right: Sidebar -->
                <div class="review-sidebar">
                    <!-- Blocked Actions -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">🚫 Blocked Actions</span>
                            <span class="panel-card-badge" id="review-blocked-badge">0</span>
                        </div>
                        <div class="panel-card-body review-data-stream-sm" id="review-blocked-list">
                            <div class="placeholder-message small">
                                <div class="placeholder-text">No blocked actions recorded</div>
                            </div>
                        </div>
                    </div>

                    <!-- System Status -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⚙ System Status</span>
                        </div>
                        <div class="panel-card-body" id="review-system-status">
                            <div class="review-detail-row">
                                <span class="panel-label">Overall Health</span>
                                <span class="panel-value" id="review-health-status">—</span>
                            </div>
                            <div class="review-detail-row">
                                <span class="panel-label">Data Health</span>
                                <span class="panel-value" id="review-data-health">—</span>
                            </div>
                            <div class="review-detail-row">
                                <span class="panel-label">Connection</span>
                                <span class="panel-value" id="review-connection">—</span>
                            </div>
                        </div>
                    </div>

                    <!-- Quick Actions -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⚡ Actions</span>
                        </div>
                        <div class="panel-card-body">
                            <button class="control-btn" style="width:100%;margin-bottom:6px;" id="review-refresh-btn">
                                ↻ Refresh All Data
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this._wireEvents();
    },

    // ── Event Wiring ──

    /** @private */
    _wireEvents() {
        const refreshBtn = document.getElementById('review-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this._loadAllData());
        }
    },

    // ── Data Loading ──

    /** @private */
    async _loadAllData() {
        await Promise.all([
            this._loadTrades(),
            this._loadDecisions(),
            this._loadBlockedActions(),
        ]);
        this._updateSummary();
    },

    /** @private */
    async _loadTrades() {
        try {
            const result = await api.getMemoryTrades();
            this._data.trades = result.trades || [];
            this._renderTrades();
            const badge = document.getElementById('review-trades-badge');
            if (badge) badge.textContent = `${this._data.trades.length} trades`;
        } catch (e) {
            this._renderTradesError(e);
            const badge = document.getElementById('review-trades-badge');
            if (badge) badge.textContent = 'Error';
        }
    },

    /** @private */
    async _loadDecisions() {
        try {
            const result = await api.getMemoryDecisions();
            this._data.decisions = result.decisions || [];
            this._renderDecisions();
            const badge = document.getElementById('review-decisions-badge');
            if (badge) badge.textContent = `${this._data.decisions.length} entries`;
        } catch (e) {
            this._renderDecisionsError(e);
            const badge = document.getElementById('review-decisions-badge');
            if (badge) badge.textContent = 'Error';
        }
    },

    /** @private */
    async _loadBlockedActions() {
        try {
            const exec = await api.getExecutionBlocked();
            this._data.blocking = exec.blocked_actions || exec.actions || [];
            this._renderBlockedActions();
            const badge = document.getElementById('review-blocked-badge');
            if (badge) badge.textContent = String(this._data.blocking.length);
        } catch (e) {
            // Silently handle — blocked actions may not be available
            this._data.blocking = [];
            this._renderBlockedActions();
        }
    },

    // ── Rendering ──

    /** @private */
    _renderTrades() {
        const listEl = document.getElementById('review-trades-list');
        if (!listEl) return;

        const trades = this._data.trades;
        if (trades.length === 0) {
            listEl.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text">No trades recorded this session</div>
                </div>
            `;
            return;
        }

        let html = '<div class="review-entry-list">';
        trades.forEach((t) => {
            const direction = (t.direction || 'BUY').toLowerCase();
            const isBuy = direction === 'buy';
            const sideColor = isBuy ? 'var(--green-500)' : 'var(--red-500)';
            const sideArrow = isBuy ? '▲' : '▼';
            const pnl = t.pnl != null ? t.pnl : (t.realized_pnl ?? null);
            const pnlStr = pnl != null ? Formatters.pnlInr(pnl) : '—';
            const pnlClass = pnl >= 0 ? 'text-green' : 'text-red';
            const qty = t.filled_qty || t.qty || 0;
            const entryPrice = t.avg_price || t.entry_price || 0;
            const exitPrice = t.exit_price || t.current_price || 0;
            const symbol = t.symbol || t.instrument || '—';
            const timestamp = t.timestamp || t.entry_time || t.time || '';

            html += `
            <div class="review-entry" style="border-left:3px solid ${sideColor};">
                <div class="review-entry-header">
                    <span style="font-weight:600;font-family:var(--font-mono);color:${sideColor};">${sideArrow} ${symbol}</span>
                    <span class="status-tag ${direction}">${(t.direction || 'BUY').toUpperCase()} ${qty}</span>
                    <span class="${pnlClass}" style="font-weight:600;font-family:var(--font-mono);">${pnlStr}</span>
                </div>
                <div class="review-entry-meta">
                    <span>Entry: ${Formatters.price(entryPrice)}</span>
                    <span>Exit: ${Formatters.price(exitPrice)}</span>
                    <span>${Formatters.time(timestamp)}</span>
                </div>
                ${t.trade_class ? `<div class="review-entry-tags"><span class="status-tag">${escapeHtml(t.trade_class)}</span></div>` : ''}
            </div>
            `;
        });
        html += '</div>';

        listEl.innerHTML = html;

        // Stagger animation — apply entry-enter AFTER innerHTML so elements exist
        const entries = listEl.querySelectorAll('.review-entry');
        entries.forEach((el) => {
            el.classList.add('entry-enter');
        });

        // Badge flash update
        const badge = document.getElementById('review-trades-badge');
        if (badge) {
            badge.classList.add('badge-updated');
            setTimeout(() => badge.classList.remove('badge-updated'), 600);
        }
    },

    /** @private */
    _renderTradesError(err) {
        const listEl = document.getElementById('review-trades-list');
        if (!listEl) return;
        listEl.innerHTML = `
            <div class="placeholder-message small" style="animation:fadeIn 0.3s ease;">
                <div class="placeholder-text" style="color:var(--red-500);margin-bottom:8px;">⚠ Failed to load trades: ${escapeHtml(err.message || 'Unknown error')}</div>
                <button class="control-btn retry-btn" style="font-size:11px;padding:4px 12px;">↻ Retry</button>
            </div>
        `;
        // Wire retry via addEventListener instead of inline onclick
        const retryBtn = listEl.querySelector('.retry-btn');
        if (retryBtn) retryBtn.addEventListener('click', () => this._loadTrades());
    },

    /** @private */
    _renderDecisions() {
        const listEl = document.getElementById('review-decisions-list');
        if (!listEl) return;

        const decisions = this._data.decisions;
        if (decisions.length === 0) {
            listEl.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text">No decisions recorded this session</div>
                </div>
            `;
            return;
        }

        let html = '<div class="review-entry-list">';
        decisions.forEach((d) => {
            const decision = d.decision || d.type || d.action || '—';
            const reason = d.reason || d.summary || d.detail || '';
            const conviction = d.conviction_band || d.conviction || '';
            const timestamp = d.timestamp || d.time || '';
            const mood = d.mood || '';
            const isTrade = decision.toUpperCase() === 'TRADE' || decision.toUpperCase() === 'BUY' || decision.toUpperCase() === 'ENTER';

            html += `
            <div class="review-entry" style="border-left:3px solid ${isTrade ? 'var(--green-500)' : 'var(--text-dim)'};">
                <div class="review-entry-header">
                    <span style="font-weight:600;">${isTrade ? '✅' : '⏸'} ${escapeHtml(decision)}</span>
                    <span style="font-size:11px;color:var(--text-muted);">${Formatters.time(timestamp, { showSeconds: false })}</span>
                </div>
                ${conviction ? `<div class="review-entry-meta"><span>Conviction: ${escapeHtml(conviction)}</span></div>` : ''}
                ${mood ? `<div class="review-entry-meta"><span>Mood: ${escapeHtml(mood)}</span></div>` : ''}
                ${reason ? `<div class="review-entry-detail">${escapeHtml(reason)}</div>` : ''}
            </div>
            `;
        });
        html += '</div>';

        listEl.innerHTML = html;

        // Stagger animation — AFTER innerHTML
        const entries = listEl.querySelectorAll('.review-entry');
        entries.forEach((el) => {
            el.classList.add('entry-enter');
        });

        // Badge flash
        const badge = document.getElementById('review-decisions-badge');
        if (badge) {
            badge.classList.add('badge-updated');
            setTimeout(() => badge.classList.remove('badge-updated'), 600);
        }
    },

    /** @private */
    _renderDecisionsError(err) {
        const listEl = document.getElementById('review-decisions-list');
        if (!listEl) return;
        listEl.innerHTML = `
            <div class="placeholder-message small" style="animation:fadeIn 0.3s ease;">
                <div class="placeholder-text" style="color:var(--red-500);margin-bottom:8px;">⚠ Failed to load decisions: ${escapeHtml(err.message || 'Unknown error')}</div>
                <button class="control-btn retry-btn" style="font-size:11px;padding:4px 12px;">↻ Retry</button>
            </div>
        `;
        const retryBtn = listEl.querySelector('.retry-btn');
        if (retryBtn) retryBtn.addEventListener('click', () => this._loadDecisions());
    },

    /** @private */
    _renderBlockedActions() {
        const listEl = document.getElementById('review-blocked-list');
        if (!listEl) return;

        const blocked = this._data.blocking;
        if (blocked.length === 0) {
            listEl.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text">No blocked actions recorded</div>
                </div>
            `;
            return;
        }

        let html = '<div class="review-entry-list">';
        blocked.forEach((b) => {
            const reason = b.block_reason || b.reason || b.message || 'Blocked';
            const severity = (b.severity || 'INFO').toLowerCase();
            const timestamp = b.timestamp || b.time || '';
            const tradeId = b.trade_id || '';

            html += `
            <div class="review-entry" style="border-left:3px solid ${Colors.severity(severity)};">
                <div class="review-entry-header">
                    <span style="font-weight:500;font-size:11px;">🚫 ${escapeHtml(reason)}</span>
                    <span style="font-size:10px;color:var(--text-dim);">${Formatters.time(timestamp)}</span>
                </div>
                ${tradeId ? `<div class="review-entry-meta"><span>Trade: ${escapeHtml(tradeId)}</span></div>` : ''}
            </div>
            `;
        });
        html += '</div>';

        listEl.innerHTML = html;

        // Stagger animation — AFTER innerHTML
        const entries = listEl.querySelectorAll('.review-entry');
        entries.forEach((el) => {
            el.classList.add('entry-enter');
        });

        // Badge flash
        const badge = document.getElementById('review-blocked-badge');
        if (badge) {
            badge.classList.add('badge-updated');
            setTimeout(() => badge.classList.remove('badge-updated'), 600);
        }
    },

    /** @private */
    _updateSummary() {
        const trades = this._data.trades;
        const decisions = this._data.decisions;
        const blocked = this._data.blocking;

        // Count trades
        const tradeCount = document.getElementById('review-trade-count');
        if (tradeCount) tradeCount.textContent = String(trades.length);

        // Count decisions
        const decisionCount = document.getElementById('review-decision-count');
        if (decisionCount) decisionCount.textContent = String(decisions.length);

        // Count blocked
        const blockedCount = document.getElementById('review-blocked-count');
        if (blockedCount) blockedCount.textContent = String(blocked.length);

        // Calculate PnL from trades
        let totalPnl = 0;
        trades.forEach(t => {
            const pnl = t.pnl != null ? t.pnl : (t.realized_pnl ?? 0);
            totalPnl += Number(pnl);
        });
        const pnlEl = document.getElementById('review-pnl');
        if (pnlEl) {
            const pnlClass = totalPnl >= 0 ? 'text-green' : 'text-red';
            pnlEl.innerHTML = `<span class="${pnlClass}" style="font-weight:700;">${Formatters.pnlInr(totalPnl)}</span>`;
        }

        // Update session info from execution state
        const exec = StateManager.get('execution', {});
        const modeEl = document.getElementById('review-mode');
        if (modeEl) modeEl.textContent = exec.mode || '—';
    },

    /** @private */
    _updateSessionInfo(health) {
        if (!health) return;

        const overall = document.getElementById('review-health-status');
        if (overall) {
            const overallStatus = (health.overall_status || '').toLowerCase();
            const dotClass = overallStatus === 'good' ? 'good' : overallStatus === 'degraded' ? 'degraded' : 'critical';
            overall.innerHTML = `<span class="health-dot health-${dotClass}" style="width:8px;height:8px;margin-right:4px;"></span> ${health.overall_status || '—'}`;
        }

        const dataHealth = document.getElementById('review-data-health');
        if (dataHealth) dataHealth.textContent = health.data_health_signal || '—';

        const connection = document.getElementById('review-connection');
        if (connection) connection.textContent = health.connection_status || '—';
    },

};
