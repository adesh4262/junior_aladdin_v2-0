/**
 * Junior Aladdin — Operator Terminal
 * workspace_diagnostics.js — Diagnostics Workspace
 *
 * System diagnostics with health drill-down, contract validation,
 * performance metrics, error logs, connection test panel, and
 * session cache viewer (HOT/WARM/COLD).
 *
 * Replaces the inline renderDiagnostics() in app.js with a
 * full component following render/unmount lifecycle.
 *
 * Reference: ROADMAP_SIDE_B Step 8.19 — Diagnostics Workspace
 */

const WorkspaceDiagnostics = {
    /** @type {HTMLElement|null} */
    _container: null,

    /** @type {boolean} Polling active */
    _polling: false,

    /** @type {number} Poll timer ID */
    _pollTimer: null,

    /** @type {Function|null} State subscription */
    _stateUnsub: null,

    /** @type {object} Cached diagnostic data */
    _data: {
        health: {},
        cache: {},
        debugState: null,
        connectionTestResults: {},
        contracts: {},
        errors: [],
        metrics: {},
    },

    /**
     * Render the diagnostics workspace into a container.
     * @param {HTMLElement} container
     */
    render(container) {
        this._container = container;
        this._renderLayout();
        this._loadAllData();
        this._startPolling();

        // Subscribe to health state changes for live updates
        this._stateUnsub = StateManager.subscribe('health', (health) => {
            if (health && this._container) {
                this._data.health = health;
                this._updateHealthDetails(health);
            }
        });
    },

    /** Unmount and clean up */
    unmount() {
        this._stopPolling();
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
                <!-- Left: Main Diagnostic Panels -->
                <div class="review-main">
                    <!-- System Health Drill-down -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">● System Health Drill-down</span>
                            <span class="panel-card-badge refresh-hot">HOT</span>
                        </div>
                        <div class="panel-card-body" id="diag-health-detail">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line-sm"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Performance Metrics -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⚡ Performance Metrics</span>
                            <span class="panel-card-badge refresh-warm">WARM</span>
                        </div>
                        <div class="panel-card-body" id="diag-metrics">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line-sm"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Contract Validation -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">✓ Contract Validation</span>
                            <span class="panel-card-badge refresh-cold">COLD</span>
                        </div>
                        <div class="panel-card-body" id="diag-contracts">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Error Logs -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⚠ Error Logs</span>
                            <span class="panel-card-badge" id="diag-error-count">0 errors</span>
                        </div>
                        <div class="panel-card-body review-data-stream" id="diag-error-list">
                            <div class="placeholder-message small">
                                <div class="placeholder-text">No errors recorded</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Right: Sidebar -->
                <div class="review-sidebar">
                    <!-- Connection Status -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">🔌 Connection Status</span>
                            <span class="panel-card-badge refresh-hot">HOT</span>
                        </div>
                        <div class="panel-card-body" id="diag-connections">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Connection Test Panel -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">🧪 Connection Test</span>
                        </div>
                        <div class="panel-card-body" id="diag-test-panel">
                            <div style="display:flex;flex-direction:column;gap:6px;">
                                <button class="control-btn" style="width:100%;font-size:11px;padding:5px 10px;" id="diag-test-all">
                                    ▶ Test All Connections
                                </button>
                                <div id="diag-test-results">
                                    <div class="placeholder-message small" style="min-height:60px;">
                                        <div class="placeholder-text">Click to test connections</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Cache Viewer -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">💾 Session Cache</span>
                            <span class="panel-card-badge refresh-cold">COLD</span>
                        </div>
                        <div class="panel-card-body" id="diag-cache-viewer">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line-sm"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Quick Actions -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⚡ Actions</span>
                        </div>
                        <div class="panel-card-body" style="display:flex;flex-direction:column;gap:6px;">
                            <button class="control-btn" style="width:100%;font-size:11px;padding:5px 10px;" id="diag-refresh-all">
                                ↻ Refresh All Diagnostics
                            </button>
                            <button class="control-btn" style="width:100%;font-size:11px;padding:5px 10px;" id="diag-clear-logs">
                                ✕ Clear Error Log
                            </button>
                            <button class="control-btn" style="width:100%;font-size:11px;padding:5px 10px;" id="diag-toggle-polling">
                                ⏸ Pause Live Updates
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
        const refreshBtn = document.getElementById('diag-refresh-all');
        if (refreshBtn) refreshBtn.addEventListener('click', () => this._loadAllData());

        const clearBtn = document.getElementById('diag-clear-logs');
        if (clearBtn) clearBtn.addEventListener('click', () => this._clearErrorLog());

        const testBtn = document.getElementById('diag-test-all');
        if (testBtn) testBtn.addEventListener('click', () => this._testAllConnections());

        const toggleBtn = document.getElementById('diag-toggle-polling');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                if (this._polling) {
                    this._stopPolling();
                    toggleBtn.textContent = '▶ Resume Live Updates';
                    toggleBtn.style.borderColor = 'var(--yellow-500)';
                } else {
                    this._startPolling();
                    toggleBtn.textContent = '⏸ Pause Live Updates';
                    toggleBtn.style.borderColor = 'var(--border-default)';
                }
            });
        }
    },

    // ── Data Loading ──

    /** @private */
    async _loadAllData() {
        await Promise.all([
            this._loadHealthDetail(),
            this._loadCacheStats(),
            this._loadDebugState(),
            this._loadMetrics(),
            this._loadContracts(),
        ]);
        this._updateSummary();
    },

    /** @private */
    async _loadHealthDetail() {
        try {
            const health = await api.getHealth();
            this._data.health = health;
            this._renderHealthDetail(health);
        } catch (e) {
            this._renderHealthError(e);
            this._logError('Health fetch failed', e);
        }
    },

    /** @private */
    async _loadCacheStats() {
        try {
            const cache = await api.getCacheStats();
            this._data.cache = cache;
            this._renderCacheViewer(cache);
        } catch (e) {
            // Cache may not be available — show placeholder
            const el = document.getElementById('diag-cache-viewer');
            if (el) {
                el.innerHTML = `
                    <div class="panel-row">
                        <span class="panel-label">Status</span>
                        <span class="panel-value text-muted">Cache endpoint unavailable</span>
                    </div>
                `;
            }
            this._logError('Cache fetch failed', e);
        }
    },

    /** @private */
    async _loadDebugState() {
        try {
            const st = await api.getDebugState();
            this._data.debugState = st;
        } catch (e) {
            this._logError('Debug state fetch failed', e);
        }
    },

    /** @private */
    async _loadMetrics() {
        // Gather metrics from various sources
        const metrics = {
            timestamp: new Date().toISOString(),
            refreshIntervals: RefreshScheduler.getIntervals(),
            schedulerPaused: RefreshScheduler.isPaused(),
            wsConnected: window.wsClient && window.wsClient.connected,
            stateKeys: Object.keys(StateManager.snapshot()).length,
            workspace: StateManager.get('workspace', 'cockpit'),
        };
        this._data.metrics = metrics;
        this._renderMetrics(metrics);
    },

    /** @private */
    async _loadContracts() {
        // Contract validation checks — verify architecture rules
        const health = StateManager.get('health', {});
        const floors = health.floors || {};
        const sides = health.sides || {};
        const floorCount = Object.keys(floors).length;
        const sideCount = Object.keys(sides).length;

        const contracts = {
            total_floors: floorCount,
            total_sides: sideCount,
            has_health_data: !!health.overall_status,
            has_floor_5: !!floors.floor_5,
            has_floor_4: !!floors.floor_4,
            has_side_a: !!sides.side_a,
            architecture_valid: floorCount > 0 && sideCount > 0,
            health_summary: health.overall_status || 'UNKNOWN',
        };
        this._data.contracts = contracts;
        this._renderContracts(contracts);
    },

    // ── Health Drill-down Renderer ──

    /** @private */
    _renderHealthDetail(health) {
        const el = document.getElementById('diag-health-detail');
        if (!el) return;

        const floors = health.floors || {};
        const sides = health.sides || {};

        const healthDot = (state) => {
            const s = (state || '').toLowerCase();
            if (s === 'healthy' || s === 'good') return '🟢';
            if (s === 'degraded') return '🟡';
            if (s === 'stale') return '🔶';
            if (s === 'critical' || s === 'unavailable' || s === 'error') return '🔴';
            if (s === 'silent') return '⚪';
            if (s === 'locked') return '🔒';
            return '⚪';
        };

        const buildHealthBlock = (title, obj, keyLabel) => {
            const entries = Object.entries(obj);
            if (entries.length === 0) {
                return `<div class="panel-row"><span class="panel-label">${title}</span><span class="panel-value text-muted">No data</span></div>`;
            }
            return entries.map(([name, comp]) => {
                const state = comp.state || 'UNKNOWN';
                const detail = comp.detail || comp.lifecycle || '';
                return `
                    <div class="panel-row" style="border-bottom:1px solid var(--border-subtle);padding:4px 0;">
                        <span style="display:flex;align-items:center;gap:6px;">
                            <span>${healthDot(state)}</span>
                            <span class="panel-label" style="font-family:var(--font-mono);font-size:11px;">${escapeHtml(name)}</span>
                        </span>
                        <span style="display:flex;align-items:center;gap:6px;">
                            <span class="status-tag ${state.toLowerCase().replace(/[^a-z]/g, '')}" style="font-size:9px;">
                                ${state}
                            </span>
                            ${detail ? `<span class="panel-value text-muted" style="font-size:9px;max-width:120px;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(detail)}</span>` : ''}
                        </span>
                    </div>
                `;
            }).join('');
        };

        let html = `
            <!-- Overall Status -->
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;padding:8px 10px;background:var(--bg-elevated);border-radius:6px;">
                <span style="font-size:18px;">${healthDot(health.overall_status)}</span>
                <div>
                    <div style="font-weight:600;font-size:13px;">${health.overall_status || 'UNKNOWN'}</div>
                    <div style="font-size:10px;color:var(--text-dim);">System Health</div>
                </div>
                <div style="margin-left:auto;display:flex;gap:8px;font-size:10px;font-family:var(--font-mono);color:var(--text-muted);">
                    <span>Data: ${health.data_health_signal || '—'}</span>
                    <span>Conn: ${health.connection_status || '—'}</span>
                </div>
            </div>

            <!-- Floors -->
            <div style="margin-bottom:8px;">
                <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;margin-bottom:4px;">
                    🏗 Floors (${Object.keys(floors).length})
                </div>
                ${buildHealthBlock('Floors', floors)}
            </div>

            <!-- Sides -->
            <div>
                <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;margin-bottom:4px;">
                    ↔ Sides (${Object.keys(sides).length})
                </div>
                ${buildHealthBlock('Sides', sides)}
            </div>

            <!-- Critical Alerts Count -->
            <div class="panel-row" style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border-subtle);">
                <span class="panel-label">Critical Alerts</span>
                <span class="panel-value ${(health.critical_alert_count || 0) > 0 ? 'text-red' : 'text-green'}" style="font-weight:600;">
                    ${health.critical_alert_count ?? 0}
                </span>
            </div>
        `;

        el.innerHTML = html;
    },

    /** @private */
    _renderHealthError(err) {
        const el = document.getElementById('diag-health-detail');
        if (!el) return;
        el.innerHTML = `
            <div class="panel-row">
                <span class="panel-label">Error</span>
                <span class="panel-value text-red">${escapeHtml(err.message || 'Failed to load health')}</span>
            </div>
        `;
    },

    /** @private */
    _updateHealthDetails(health) {
        // Live-update the health section without full re-render
        if (this._container && health) {
            this._renderHealthDetail(health);
        }
    },

    // ── Metrics Renderer ──

    /** @private */
    _renderMetrics(metrics) {
        const el = document.getElementById('diag-metrics');
        if (!el) return;

        const intervals = metrics.refreshIntervals || {};
        const wsStatus = metrics.wsConnected
            ? '<span class="text-green">● Connected</span>'
            : '<span class="text-yellow">● Polling Fallback</span>';

        el.innerHTML = `
            <div class="panel-row">
                <span class="panel-label">WebSocket</span>
                <span class="panel-value">${wsStatus}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Scheduler</span>
                <span class="panel-value ${metrics.schedulerPaused ? 'text-yellow' : 'text-green'}">
                    ${metrics.schedulerPaused ? '⏸ Paused' : '▶ Running'}
                </span>
            </div>
            <div class="panel-row">
                <span class="panel-label">HOT Interval</span>
                <span class="panel-value mono">${intervals.hot || '—'}ms</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">WARM Interval</span>
                <span class="panel-value mono">${intervals.warm || '—'}ms</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">COLD Interval</span>
                <span class="panel-value mono">${intervals.cold || '—'}ms</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">State Keys</span>
                <span class="panel-value mono">${metrics.stateKeys}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Active Workspace</span>
                <span class="panel-value">${escapeHtml(metrics.workspace)}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Snapshot</span>
                <span class="panel-value mono" style="font-size:10px;">${new Date(metrics.timestamp).toLocaleTimeString()}</span>
            </div>
        `;
    },

    // ── Contracts Renderer ──

    /** @private */
    _renderContracts(contracts) {
        const el = document.getElementById('diag-contracts');
        if (!el) return;

        const archClass = contracts.architecture_valid ? 'text-green' : 'text-red';

        el.innerHTML = `
            <div class="panel-row">
                <span class="panel-label">Architecture Valid</span>
                <span class="panel-value ${archClass}">${contracts.architecture_valid ? '✅ Yes' : '❌ No'}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Floors Reporting</span>
                <span class="panel-value mono">${contracts.total_floors}/5</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Sides Reporting</span>
                <span class="panel-value mono">${contracts.total_sides}/3</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Floor 4 (Heads)</span>
                <span class="panel-value ${contracts.has_floor_4 ? 'text-green' : 'text-red'}">
                    ${contracts.has_floor_4 ? '✅ Present' : '❌ Missing'}
                </span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Floor 5 (Captain)</span>
                <span class="panel-value ${contracts.has_floor_5 ? 'text-green' : 'text-red'}">
                    ${contracts.has_floor_5 ? '✅ Present' : '❌ Missing'}
                </span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Side A (Execution)</span>
                <span class="panel-value ${contracts.has_side_a ? 'text-green' : 'text-red'}">
                    ${contracts.has_side_a ? '✅ Present' : '❌ Missing'}
                </span>
            </div>
            <div class="panel-row" style="border-top:1px solid var(--border-subtle);padding-top:6px;margin-top:4px;">
                <span class="panel-label">Health Summary</span>
                <span class="panel-value mono">${contracts.health_summary}</span>
            </div>
        `;
    },

    // ── Cache Viewer Renderer ──

    /** @private */
    _renderCacheViewer(cache) {
        const el = document.getElementById('diag-cache-viewer');
        if (!el) return;

        if (!cache || !cache.total_entries) {
            el.innerHTML = `
                <div class="panel-row">
                    <span class="panel-label">Status</span>
                    <span class="panel-value text-muted">Cache data unavailable</span>
                </div>
            `;
            return;
        }

        const hitPct = cache.hit_ratio != null ? (cache.hit_ratio * 100).toFixed(1) + '%' : '—';
        const tiers = cache.tier_counts || {};

        el.innerHTML = `
            <div class="panel-row">
                <span class="panel-label">Total Entries</span>
                <span class="panel-value mono">${cache.total_entries}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Hit Ratio</span>
                <span class="panel-value mono ${cache.hit_ratio > 0.8 ? 'text-green' : cache.hit_ratio > 0.5 ? 'text-yellow' : 'text-red'}">
                    ${hitPct}
                </span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px;">
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);">🔥 HOT</div>
                    <div class="mono" style="font-size:15px;font-weight:700;color:var(--red-500);">${tiers.HOT ?? 0}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);">☀ WARM</div>
                    <div class="mono" style="font-size:15px;font-weight:700;color:var(--yellow-500);">${tiers.WARM ?? 0}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);">❄ COLD</div>
                    <div class="mono" style="font-size:15px;font-weight:700;color:var(--blue-500);">${tiers.COLD ?? 0}</div>
                </div>
            </div>
        `;
    },

    // ── Connection Status Renderer ──

    /** @private */
    _renderConnections() {
        const el = document.getElementById('diag-connections');
        if (!el) return;

        const wsConnected = window.wsClient && window.wsClient.connected;
        const apiBase = api.baseUrl;

        const wsIcon = wsConnected ? '🟢' : '🔴';
        const wsText = wsConnected ? 'Connected' : 'Disconnected';

        // Build connection table
        const endpoints = [
            { name: 'API Server', url: apiBase, status: 'checking' },
            { name: 'WebSocket', url: api.wsUrl, status: wsConnected ? 'connected' : 'disconnected' },
        ];

        let html = `
            <div class="panel-row">
                <span class="panel-label">API Base URL</span>
                <span class="panel-value mono" style="font-size:10px;">${escapeHtml(apiBase)}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">WebSocket URL</span>
                <span class="panel-value mono" style="font-size:10px;">${escapeHtml(api.wsUrl)}</span>
            </div>
            <div class="panel-row" style="border-bottom:1px solid var(--border-subtle);padding-bottom:6px;margin-bottom:6px;">
                <span class="panel-label">WS Status</span>
                <span class="panel-value ${wsConnected ? 'text-green' : 'text-red'}">
                    ${wsIcon} ${wsText}
                </span>
            </div>
        `;

        // Add test results if available
        const testResults = this._data.connectionTestResults;
        if (Object.keys(testResults).length > 0) {
            html += Object.entries(testResults).map(([name, result]) => `
                <div class="panel-row" style="padding:2px 0;">
                    <span class="panel-label" style="font-size:10px;">${escapeHtml(name)}</span>
                    <span class="panel-value ${result.success ? 'text-green' : 'text-red'}" style="font-size:10px;">
                        ${result.success ? '✅' : '❌'} ${result.ms ? result.ms + 'ms' : '—'}
                    </span>
                </div>
            `).join('');
        } else {
            html += '<div class="panel-row"><span class="panel-label" style="font-size:10px;color:var(--text-dim);">Run connection test to verify endpoints</span></div>';
        }

        el.innerHTML = html;
    },

    // ── Connection Test ──

    /** @private */
    async _testAllConnections() {
        const testBtn = document.getElementById('diag-test-all');
        const resultsEl = document.getElementById('diag-test-results');
        if (!resultsEl) return;

        if (testBtn) {
            testBtn.disabled = true;
            testBtn.textContent = '⏳ Testing...';
        }

        resultsEl.innerHTML = '<div style="text-align:center;padding:12px;color:var(--text-dim);font-size:11px;">⏳ Testing connections...</div>';

        const testEndpoints = [
            { name: 'Root API', url: api.baseUrl + '/' },
            { name: 'Health', url: api.baseUrl + '/api/health' },
            { name: 'Captain', url: api.baseUrl + '/api/captain/state' },
            { name: 'Execution', url: api.baseUrl + '/api/execution/state' },
            { name: 'Heads', url: api.baseUrl + '/api/heads' },
            { name: 'Market', url: api.baseUrl + '/api/market/snapshot' },
        ];

        const results = {};

        for (const ep of testEndpoints) {
            const start = performance.now();
            try {
                const res = await fetch(ep.url, { method: 'GET', headers: { 'Accept': 'application/json' } });
                const ms = Math.round(performance.now() - start);
                results[ep.name] = { success: res.ok, ms, status: res.status };
            } catch (e) {
                const ms = Math.round(performance.now() - start);
                results[ep.name] = { success: false, ms, error: e.message };
            }
        }

        this._data.connectionTestResults = results;

        // Re-render connections and results
        this._renderConnections();

        resultsEl.innerHTML = Object.entries(results).map(([name, r]) => {
            const icon = r.success ? '✅' : '❌';
            const color = r.success ? 'var(--green-500)' : 'var(--red-500)';
            const detail = r.success ? `${r.ms}ms (${r.status})` : `${r.ms}ms — ${escapeHtml(r.error || 'Failed')}`;
            return `
                <div class="panel-row" style="padding:3px 0;">
                    <span style="display:flex;align-items:center;gap:4px;">
                        <span>${icon}</span>
                        <span class="panel-label" style="font-size:10px;">${escapeHtml(name)}</span>
                    </span>
                    <span class="panel-value mono" style="font-size:10px;color:${color};">${detail}</span>
                </div>
            `;
        }).join('');

        if (testBtn) {
            testBtn.disabled = false;
            testBtn.textContent = '▶ Test All Connections';
        }
    },

    // ── Error Log ──

    /** @private */
    _logError(context, error) {
        const entry = {
            timestamp: new Date().toISOString(),
            context: context,
            message: error && error.message ? error.message : String(error),
            stack: error && error.stack ? error.stack : null,
        };
        this._data.errors.push(entry);

        // Cap at 50 errors
        if (this._data.errors.length > 50) {
            this._data.errors = this._data.errors.slice(-50);
        }

        this._renderErrorLog();
    },

    /** @private */
    _renderErrorLog() {
        const listEl = document.getElementById('diag-error-list');
        const countEl = document.getElementById('diag-error-count');
        if (!listEl) return;

        const errors = this._data.errors;
        if (countEl) countEl.textContent = `${errors.length} errors`;

        if (errors.length === 0) {
            listEl.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text">No errors recorded</div>
                </div>
            `;
            return;
        }

        let html = '<div class="review-entry-list">';
        // Show most recent first
        [...errors].reverse().slice(0, 20).forEach((err, idx) => {
            const time = new Date(err.timestamp).toLocaleTimeString();
            html += `
                <div class="review-entry" style="border-left:3px solid var(--red-500);">
                    <div class="review-entry-header">
                        <span style="font-weight:500;font-size:10px;">⚠ ${escapeHtml(err.context)}</span>
                        <span style="font-size:9px;color:var(--text-dim);font-family:var(--font-mono);">${time}</span>
                    </div>
                    <div class="review-entry-detail" style="font-size:10px;padding:3px 6px;">
                        ${escapeHtml(err.message)}
                    </div>
                </div>
            `;
        });
        html += '</div>';

        listEl.innerHTML = html;

        // Auto-scroll to top to see most recent
        listEl.scrollTop = 0;
    },

    /** @private */
    _clearErrorLog() {
        this._data.errors = [];
        this._renderErrorLog();

        const countEl = document.getElementById('diag-error-count');
        if (countEl) countEl.textContent = '0 errors';
    },

    // ── Summary ──

    /** @private */
    _updateSummary() {
        // Update error log
        this._renderErrorLog();

        // Update connections
        this._renderConnections();
    },

    // ── Polling ──

    /** @private */
    _startPolling() {
        if (this._polling) return;
        this._polling = true;
        this._pollLoop();
    },

    /** @private */
    _stopPolling() {
        this._polling = false;
        if (this._pollTimer) {
            clearTimeout(this._pollTimer);
            this._pollTimer = null;
        }
    },

    /** @private */
    async _pollLoop() {
        if (!this._polling || !this._container) return;

        // Refresh metrics on each cycle
        await this._loadMetrics();

        this._pollTimer = setTimeout(() => this._pollLoop(), 5000);
    },
};
