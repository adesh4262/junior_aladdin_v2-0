/**
 * Junior Aladdin — Operator Terminal
 * app.js — App bootstrap, router, component lifecycle, UI rendering
 *
 * State management lives in state_manager.js (StateManager)
 * Component management lives in component_manager.js (ComponentManager)
 * Refresh scheduling lives in refresh_scheduler.js (RefreshScheduler)
 * API communication lives in api_client.js (ApiClient)
 *
 * Reference: ROADMAP_MEMORY Side B Steps 8.10-8.12
 */

/* ── Global API client ── */
const api = new ApiClient();

// Subscriptions for right panel live updates
let _headsDetailUnsub = null;

/* ══════════════════════════════════════════════════════════════
   Router — simple hash-based SPA router
   ══════════════════════════════════════════════════════════════ */

const Router = {
    _routes: new Map(),

    /**
     * Register a route handler.
     * @param {string} hash - e.g. '#cockpit', '#replay', '#diagnostics'
     * @param {Function} handler - receives (params)
     */
    on(hash, handler) {
        this._routes.set(hash, handler);
    },

    /** Navigate to a hash route. */
    navigate(hash) {
        window.location.hash = hash;
    },

    /** Get current hash (without #) */
    current() {
        return window.location.hash.slice(1) || 'cockpit';
    },

    /** Start the router */
    start() {
        window.addEventListener('hashchange', () => this._handleRoute());
        this._handleRoute();
    },

    /** @private */
    _handleRoute() {
        const hash = this.current();
        const handler = this._routes.get(hash);
        if (handler) {
            StateManager.set('workspace', hash);
            handler({});
        } else {
            this.navigate('cockpit');
        }
    }
};

/* ══════════════════════════════════════════════════════════════
   Initialization
   ══════════════════════════════════════════════════════════════ */

// Global error handler to catch unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
    console.warn('[App] Unhandled rejection caught:', event.reason);
    event.preventDefault();
});

document.addEventListener('DOMContentLoaded', async () => {
    // ── Register routes ──
    Router.on('cockpit', () => switchWorkspace('cockpit'));
    Router.on('replay', () => switchWorkspace('replay'));
    Router.on('review', () => switchWorkspace('review'));
    Router.on('diagnostics', () => switchWorkspace('diagnostics'));
    Router.on('cache', () => switchWorkspace('cache'));

    // ── Sidebar navigation ──
    document.querySelectorAll('.sidebar-item[data-workspace]').forEach(el => {
        el.addEventListener('click', () => {
            const ws = el.dataset.workspace;
            Router.navigate(ws);
            document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
            el.classList.add('active');
        });
    });

    document.querySelectorAll('.sidebar-item[data-panel]').forEach(el => {
        el.addEventListener('click', () => {
            openRightPanel(el.dataset.panel);
        });
    });

    // ── Sidebar toggle ──
    document.getElementById('sidebar-toggle').addEventListener('click', () => {
        const sidebar = document.getElementById('sidebar');
        sidebar.classList.toggle('collapsed');
        StateManager.set('sidebarOpen', !sidebar.classList.contains('collapsed'));
    });

    // ── Right panel close ──
    document.getElementById('right-panel-close').addEventListener('click', closeRightPanel);

    // ── Start router ──
    Router.start();

    // ── Start clock ──
    startClock();
    window.addEventListener('beforeunload', () => {
        if (clockInterval) clearInterval(clockInterval);
    });

    // ── Initialize API connection ──
    await initializeApp();

    // ── Initialize and start RefreshScheduler ──
    RefreshScheduler.init(api);

    // Register poll callbacks for UI updates
    RefreshScheduler.onHotPoll((execution, market, alerts) => {
        if (execution) {
            StateManager.set('execution', execution);
            setText('status-mode', execution.mode || 'ALERT');
            setText('bottom-mode', `Mode: ${execution.mode || 'ALERT'}`);
            const cap = execution.capital_limit;
            setText('bottom-capital', cap != null ? `Capital: ₹${Number(cap).toLocaleString('en-IN')}` : 'Capital: --');
        }
        if (market) {
            StateManager.set('market', market);
            // Feed live price into chart
            const chart = ComponentManager.get('chart');
            if (chart && market.ltp) {
                const now = Math.floor(Date.now() / 1000);
                chart.updateTick(now, market.ltp);
            }
        }
        if (alerts) updateAlertBadge(alerts);
    });

    RefreshScheduler.onWarmPoll((captain, heads) => {
        if (captain) {
            StateManager.set('captain', captain);
            setText('status-decision', captain.decision_state || captain.decision || 'WAIT');
            const band = (captain.conviction_band || 'reject').toLowerCase();
            const fill = document.getElementById('conviction-fill');
            if (fill) fill.className = `conviction-fill ${band}`;
            setText('status-conviction', captain.conviction_band || 'REJECT');
        }
        if (heads) {
            StateManager.set('heads', heads);
        }
    });

    RefreshScheduler.onColdPoll((health, cache) => {
        if (health) updateHealthDisplay(health);
        if (cache) updateCacheDisplay(cache);
        updateStatusBar();
    });

    // Register WebSocket channel handlers
    RefreshScheduler.onWsMessage('execution', (data) => {
        StateManager.set('execution', data);
    });
    RefreshScheduler.onWsMessage('market', (data) => {
        StateManager.set('market', data);
    });
    RefreshScheduler.onWsMessage('health', (data) => {
        updateHealthDisplay(data);
    });
    RefreshScheduler.onWsMessage('alerts', (data) => {
        updateAlertBadge(data);
    });

    RefreshScheduler.start();

    // ── Connect WebSocket via dedicated WebSocketClient ──
    window.wsClient = new WebSocketClient(api.wsUrl, { autoConnect: false });

    // Register event handlers BEFORE connecting to avoid race conditions
    wsClient.on('connect', () => updateConnectionStatus(true));
    wsClient.on('disconnect', () => updateConnectionStatus(false));

    // Subscribe to HOT-tier WS channels only (server pushes these)
    // WARM/COLD channels (captain, heads, etc.) are polled via RefreshScheduler
    const wsChannels = ['execution', 'market', 'health', 'alerts'];
    wsChannels.forEach(channel => {
        wsClient.on('channel:' + channel, (data) => {
            const msg = { channel, data };
            RefreshScheduler.handleWsMessage(msg);
        });
    });

    // Start fallback polling when WS is down (routes through same channel events)
    wsClient.startFallbackPolling({
        execution: () => api.getExecutionState(),
        market: () => api.getMarketSnapshot(),
        health: () => api.getHealth(),
        alerts: () => api.getAlerts(),
    }, 5000);

    // Now connect after all handlers are registered
    wsClient.connect();
});

/* ══════════════════════════════════════════════════════════════
   Initialization
   ══════════════════════════════════════════════════════════════ */

async function initializeApp() {
    const loadingOverlay = document.getElementById('loading-overlay');
    const progressBar = document.getElementById('loading-progress-bar');
    const statusText = document.getElementById('loading-status');
    const errorOverlay = document.getElementById('error-overlay');
    const errorMessage = document.getElementById('error-message');

    try {
        statusText.textContent = 'Connecting to API...';
        progressBar.style.width = '15%';
        await api.getRoot();
        progressBar.style.width = '30%';

        statusText.textContent = 'Fetching system health...';
        const health = await api.getHealth();
        StateManager.set('health', health);
        updateHealthDisplay(health);
        progressBar.style.width = '50%';

        statusText.textContent = 'Loading captain state...';
        try {
            const captain = await api.getCaptainState();
            StateManager.set('captain', captain);
        } catch (e) { /* non-critical */ }
        progressBar.style.width = '65%';

        statusText.textContent = 'Loading execution state...';
        try {
            const execution = await api.getExecutionState();
            StateManager.set('execution', execution);
        } catch (e) { /* non-critical */ }
        progressBar.style.width = '75%';

        statusText.textContent = 'Loading market data...';
        try {
            const market = await api.getMarketSnapshot();
            StateManager.set('market', market);
        } catch (e) { /* non-critical */ }
        progressBar.style.width = '85%';

        statusText.textContent = 'Loading alerts...';
        try {
            const alerts = await api.getAlerts();
            StateManager.set('alerts', alerts);
            updateAlertBadge(alerts);
        } catch (e) { /* non-critical */ }
        progressBar.style.width = '95%';

        statusText.textContent = 'Loading cache stats...';
        try {
            const cache = await api.getCacheStats();
            StateManager.set('cache', cache);
        } catch (e) { /* non-critical */ }
        progressBar.style.width = '100%';

        statusText.textContent = 'Ready';
        setTimeout(() => {
            loadingOverlay.classList.add('fade-out');
            document.getElementById('app').classList.remove('hidden');
            setTimeout(() => { loadingOverlay.style.display = 'none'; }, 400);
            updateStatusBar();
        }, 300);

    } catch (err) {
        console.error('[App] Initialization failed:', err);
        errorMessage.textContent = `Unable to connect to the API server at ${api.baseUrl}.\n\n${err.message || 'Is the server running?'}`;
        errorOverlay.classList.remove('hidden');
    }
}

/* ══════════════════════════════════════════════════════════════
   Workspace Switching
   ══════════════════════════════════════════════════════════════ */

// Track the active workspace object so we can unmount it before switching
let _activeWorkspace = null;

function switchWorkspace(workspace) {
    const container = document.getElementById('workspace-container');
    // Unmount all components before switching workspaces
    ComponentManager.unmountAll();

    // Cleanup previous workspace (e.g. WorkspaceReplay)
    if (_activeWorkspace && _activeWorkspace.unmount) {
        _activeWorkspace.unmount();
        _activeWorkspace = null;
    }

    StateManager.set('workspace', workspace);

    switch (workspace) {
        case 'cockpit':
            renderCockpit(container);
            break;
        case 'replay':
            WorkspaceReplay.render(container);
            _activeWorkspace = WorkspaceReplay;
            break;
        case 'review':
            WorkspaceReview.render(container);
            _activeWorkspace = WorkspaceReview;
            break;
        case 'diagnostics':
            WorkspaceDiagnostics.render(container);
            _activeWorkspace = WorkspaceDiagnostics;
            break;
        case 'cache':
            SessionCacheDisplay.render(container);
            _activeWorkspace = SessionCacheDisplay;
            break;
        default:
            renderCockpit(container);
    }
}

/* ══════════════════════════════════════════════════════════════
   Cockpit Renderer (Primary View)
   ══════════════════════════════════════════════════════════════ */

function renderCockpit(container) {
    container.innerHTML = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">System Status</span>
                <span class="panel-card-badge refresh-hot">HOT</span>
            </div>
            <div class="panel-card-body">
                <div class="status-grid" id="status-grid">
                    <div class="status-item">
                        <span class="panel-label">Health</span>
                        <span class="panel-value" id="status-health">
                            <span class="health-dot health-unknown"></span>
                            INITIALIZING
                        </span>
                    </div>
                    <div class="status-item">
                        <span class="panel-label">Mode</span>
                        <span class="panel-value" id="status-mode">ALERT</span>
                    </div>
                    <div class="status-item">
                        <span class="panel-label">Decision</span>
                        <span class="panel-value" id="status-decision">WAIT</span>
                    </div>
                    <div class="status-item">
                        <span class="panel-label">Conviction</span>
                        <span class="panel-value" id="status-conviction">
                            <span class="conviction-bar"><span class="conviction-fill reject" id="conviction-fill"></span></span>
                            REJECT
                        </span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Chart Surface (full-width) -->
        <div id="chart-surface-mount" class="chart-container"></div>

        <div class="cockpit-row-2">
            <!-- Execution Panel (Component-managed) -->
            <div id="execution-panel-mount"></div>

            <!-- Captain Panel (Component-managed) -->
            <div id="captain-panel-mount"></div>
        </div>

        <!-- Heads Panel (Component-managed) -->
        <div id="heads-panel-mount"></div>

        <div class="cockpit-row-3">
            <!-- Health Panel (Component-managed) -->
            <div id="health-panel-mount"></div>

            <!-- Market Panel (Component-managed) -->
            <div id="market-panel-mount"></div>

            <!-- Alert Panel (Component-managed) -->
            <div id="alert-panel-mount"></div>
        </div>

        <!-- Explainability Panel (WARM) -->
        <div id="explainability-panel-mount"></div>

        <!-- Controls Panel (Component-managed) -->
        <div id="controls-panel-mount"></div>
    `;

    // Mount chart surface (full-width, top of cockpit)
    const chartMount = document.getElementById('chart-surface-mount');
    if (chartMount) ComponentManager.mount('chart', chartMount);

    // Mount component-based panels
    const healthMount = document.getElementById('health-panel-mount');
    if (healthMount) ComponentManager.mount('health', healthMount);

    const alertMount = document.getElementById('alert-panel-mount');
    if (alertMount) ComponentManager.mount('alerts', alertMount);

    const marketMount = document.getElementById('market-panel-mount');
    if (marketMount) ComponentManager.mount('market', marketMount);

    const executionMount = document.getElementById('execution-panel-mount');
    if (executionMount) ComponentManager.mount('execution', executionMount);

    const captainMount = document.getElementById('captain-panel-mount');
    if (captainMount) ComponentManager.mount('captain', captainMount);

    const headsMount = document.getElementById('heads-panel-mount');
    if (headsMount) ComponentManager.mount('heads', headsMount);

    const explainabilityMount = document.getElementById('explainability-panel-mount');
    if (explainabilityMount) ComponentManager.mount('explainability', explainabilityMount);

    const controlsMount = document.getElementById('controls-panel-mount');
    if (controlsMount) ComponentManager.mount('controls', controlsMount);
}



/* ══════════════════════════════════════════════════════════════
   Right Panel (Drill-down)
   ══════════════════════════════════════════════════════════════ */

function openRightPanel(panelName) {
    const panel = document.getElementById('right-panel');
    const title = document.getElementById('right-panel-title');
    const content = document.getElementById('right-panel-content');

    // Clean up any previous detail subscription before switching panels
    if (_headsDetailUnsub) { _headsDetailUnsub(); _headsDetailUnsub = null; }

    const panelTitles = {
        execution: '⚡ Execution Detail',
        captain: '◈ Captain Detail',
        heads: '◆ Head Reports',
        market: '◉ Market Detail',
        health: '● System Health',
        alerts: '⚠ Alerts',
        controls: '⚙ Controls',
        floor_drilldown: '● Floor Drill-down: ', // component name appended dynamically
    };

    title.textContent = panelTitles[panelName] || panelName;
    StateManager.set('activePanel', panelName);

    switch (panelName) {
        case 'health': renderHealthDetail(content); break;
        case 'captain': renderCaptainDetail(content); break;
        case 'execution': renderExecutionDetail(content); break;
        case 'alerts': renderAlertDetail(content); break;
        case 'market': renderMarketDetail(content); break;
        case 'heads':
            renderHeadsDetail(content);
            // Subscribe to live updates via WARM poll
            _headsDetailUnsub = StateManager.subscribe('heads', () => {
                // Only re-render if the right panel is still showing heads
                if (StateManager.get('activePanel') === 'heads') {
                    renderHeadsDetail(content);
                }
            });
            break;
        case 'floor_drilldown':
            const fdComponent = StateManager.get('activePanelComponent') || 'unknown';
            title.textContent = panelTitles.floor_drilldown + fdComponent;
            renderFloorDrilldown(content, fdComponent);
            break;
        default:
            content.innerHTML = `<div class="placeholder-message small"><div class="placeholder-text">${panelName} detail view coming soon</div></div>`;
    }

    panel.classList.remove('collapsed');
    StateManager.set('rightPanelOpen', true);
}

function closeRightPanel() {
    document.getElementById('right-panel').classList.add('collapsed');
    StateManager.set('rightPanelOpen', false);
    StateManager.set('activePanel', null);
    // Clean up any active detail subscriptions
    if (_headsDetailUnsub) { _headsDetailUnsub(); _headsDetailUnsub = null; }
}

/* ── Right Panel Detail Renderers ── */

function renderHealthDetail(container) {
    const health = StateManager.get('health', {});
    const floors = health.floors || {};
    const sides = health.sides || {};

    let html = '<div class="panel-card"><div class="panel-card-header"><span class="panel-card-title">Floors</span></div><div class="panel-card-body">';
    for (const [name, comp] of Object.entries(floors)) {
        const stateClass = (comp.state || '').toLowerCase().replace(/[^a-z]/g, '');
        html += `<div class="panel-row"><span class="panel-label">${name}</span><span class="status-tag ${stateClass}">${comp.state || 'UNKNOWN'}</span></div>`;
    }
    html += '</div></div>';

    html += '<div class="panel-card"><div class="panel-card-header"><span class="panel-card-title">Sides</span></div><div class="panel-card-body">';
    for (const [name, comp] of Object.entries(sides)) {
        const stateClass = (comp.state || '').toLowerCase().replace(/[^a-z]/g, '');
        html += `<div class="panel-row"><span class="panel-label">${name}</span><span class="status-tag ${stateClass}">${comp.state || 'UNKNOWN'}</span></div>`;
    }
    html += '</div></div>';

    html += `<div class="panel-card"><div class="panel-card-body"><div class="panel-row"><span class="panel-label">Data Health</span><span class="panel-value">${health.data_health_signal || 'UNKNOWN'}</span></div><div class="panel-row"><span class="panel-label">Connection</span><span class="panel-value">${health.connection_status || 'UNKNOWN'}</span></div><div class="panel-row"><span class="panel-label">Critical Alerts</span><span class="panel-value">${health.critical_alert_count ?? 0}</span></div></div></div>`;
    container.innerHTML = html;
}

function renderCaptainDetail(container) {
    const captain = StateManager.get('captain', {});
    container.innerHTML = `
        <div class="panel-card"><div class="panel-card-body">
            <div class="panel-row"><span class="panel-label">Mood</span><span class="panel-value">${captain.mood || 'OBSERVER'}</span></div>
            <div class="panel-row"><span class="panel-label">Decision</span><span class="panel-value">${captain.decision_state || captain.decision || 'WAIT'}</span></div>
            <div class="panel-row"><span class="panel-label">Conviction Band</span><span class="panel-value">${captain.conviction_band || 'REJECT'}</span></div>
            <div class="panel-row"><span class="panel-label">Session Phase</span><span class="panel-value">${captain.session_phase || '-'}</span></div>
            <div class="panel-row"><span class="panel-label">Real Mode Locked</span><span class="panel-value">${captain.real_mode_locked ? 'Yes' : 'No'}</span></div>
            <div class="panel-row"><span class="panel-label">Active Trade</span><span class="panel-value">${captain.active_trade ? 'Yes' : 'No'}</span></div>
        </div></div>
        <div class="panel-card"><div class="panel-card-header"><span class="panel-card-title">Story</span></div>
            <div class="panel-card-body"><div style="font-size:var(--font-size-sm);color:var(--text-secondary);line-height:1.6;">${captain.market_story_summary || captain.story_summary || 'No story available.'}</div></div>
        </div>
    `;
}

function renderExecutionDetail(container) {
    const exec = StateManager.get('execution', {});
    container.innerHTML = `
        <div class="panel-card"><div class="panel-card-body">
            <div class="panel-row"><span class="panel-label">State</span><span class="panel-value">${exec.state || exec.mode || 'IDLE'}</span></div>
            <div class="panel-row"><span class="panel-label">Mode</span><span class="panel-value">${exec.mode || 'ALERT'}</span></div>
            <div class="panel-row"><span class="panel-label">Escalation</span><span class="panel-value">${exec.escalation_level || 'NORMAL'}</span></div>
            <div class="panel-row"><span class="panel-label">Locked</span><span class="panel-value">${exec.is_locked ? 'Yes' : 'No'}</span></div>
            <div class="panel-row"><span class="panel-label">Unk. Reconcile</span><span class="panel-value">${exec.unknown_reconcile ? '⚠ Yes' : 'No'}</span></div>
        </div></div>
    `;
}

function renderAlertDetail(container) {
    const alerts = StateManager.get('alerts', { alerts: [], count: 0 });
    const list = alerts.alerts || [];
    container.innerHTML = `
        <div class="panel-card"><div class="panel-card-body"><div class="panel-row"><span class="panel-label">Active Alerts</span><span class="panel-value">${alerts.count ?? list.length}</span></div></div></div>
        <div class="panel-card"><div class="panel-card-header"><span class="panel-card-title">Alert List</span></div>
            <div class="panel-card-body" id="alert-detail-list">
                ${list.length === 0 ? '<div class="panel-value text-muted">No active alerts</div>' : ''}
                ${list.map(a => `
                    <div class="panel-row" style="border-bottom:1px solid var(--border-subtle);padding:4px 0;">
                        <span class="status-tag ${(a.severity || '').toLowerCase()}">${a.severity}</span>
                        <span class="panel-value" style="font-size:10px;max-width:180px;overflow:hidden;text-overflow:ellipsis;">${a.message}</span>
                        <button class="icon-btn ack-alert" data-id="${a.alert_id}" title="Acknowledge">✓</button>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    container.querySelectorAll('.ack-alert').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                await api.acknowledgeAlert(btn.dataset.id);
                btn.textContent = '✓';
                btn.disabled = true;
                btn.style.color = 'var(--green-500)';
            } catch (e) { console.warn('[Alerts] Acknowledge failed:', e); }
        });
    });
}

/* ══════════════════════════════════════════════════════════════
   Heads Detail Renderer
   ══════════════════════════════════════════════════════════════ */

function renderHeadsDetail(container) {
    const heads = StateManager.get('heads', {});
    const fs = heads.floor_summary || {};
    const headList = heads.heads || [];

    // Bias labels
    const biasLabels = {
        'NEUTRAL': '⚪ Neutral',
        'BULLISH': '📈 Bullish',
        'BEARISH': '📉 Bearish',
        'MIXED': '🔀 Mixed',
    };
    const floorBias = fs.floor_bias || 'NEUTRAL';
    const floorConfidence = fs.floor_confidence ?? 0;
    const activeSetups = fs.active_setup_count ?? 0;
    const readyHeads = fs.ready_heads ?? 0;
    const uncertainHeads = fs.uncertain_heads ?? 0;
    const staleHeads = fs.stale_heads ?? 0;
    const dataHealth = fs.data_health_signal || 'GOOD';
    const confPct = Math.round(floorConfidence * 100);

    // Data health color
    const dhLower = dataHealth.toLowerCase();
    const dhDotClass = dhLower === 'good' ? 'health-good'
        : dhLower === 'degraded' ? 'health-degraded'
        : dhLower === 'critical' ? 'health-critical'
        : 'health-unknown';

    // Confidence color
    const confColor = confidenceColor(floorConfidence);

    // Floor Summary Section
    let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">Floor Summary</span>
                <span class="panel-card-badge refresh-warm">WARM</span>
            </div>
            <div class="panel-card-body">
                <!-- Bias + Confidence + Setups row (large) -->
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px;">
                    <div style="background:var(--bg-elevated);border-radius:6px;padding:10px 12px;text-align:center;">
                        <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Floor Bias</div>
                        <div style="font-size:18px;font-weight:700;margin-top:4px;">${biasLabels[floorBias] || floorBias}</div>
                    </div>
                    <div style="background:var(--bg-elevated);border-radius:6px;padding:10px 12px;text-align:center;">
                        <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Confidence</div>
                        <div style="font-size:18px;font-weight:700;font-family:var(--font-mono);margin-top:4px;">${confPct}%</div>
                        <div class="conviction-bar" style="height:6px;background:var(--bg-surface);border-radius:3px;overflow:hidden;margin-top:6px;">
                            <div style="width:${confPct}%;height:100%;border-radius:3px;background:${confColor};transition:width 0.3s;"></div>
                        </div>
                    </div>
                    <div style="background:var(--bg-elevated);border-radius:6px;padding:10px 12px;text-align:center;">
                        <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Active Setups</div>
                        <div style="font-size:18px;font-weight:700;font-family:var(--font-mono);margin-top:4px;">${activeSetups}</div>
                    </div>
                </div>

                <!-- Head Counts + Data Health -->
                <div style="display:flex;gap:12px;flex-wrap:wrap;">
                    <div style="display:flex;align-items:center;gap:5px;background:var(--bg-elevated);border-radius:4px;padding:6px 10px;">
                        <span class="health-dot health-good" style="width:8px;height:8px;"></span>
                        <span class="text-green" style="font-size:13px;font-weight:600;font-family:var(--font-mono);">${readyHeads}</span>
                        <span style="font-size:10px;color:var(--text-dim);">Ready</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:5px;background:var(--bg-elevated);border-radius:4px;padding:6px 10px;">
                        <span class="health-dot health-degraded" style="width:8px;height:8px;"></span>
                        <span class="text-yellow" style="font-size:13px;font-weight:600;font-family:var(--font-mono);">${uncertainHeads}</span>
                        <span style="font-size:10px;color:var(--text-dim);">Uncertain</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:5px;background:var(--bg-elevated);border-radius:4px;padding:6px 10px;">
                        <span class="health-dot health-critical" style="width:8px;height:8px;"></span>
                        <span class="text-red" style="font-size:13px;font-weight:600;font-family:var(--font-mono);">${staleHeads}</span>
                        <span style="font-size:10px;color:var(--text-dim);">Stale</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:5px;background:var(--bg-elevated);border-radius:4px;padding:6px 10px;margin-left:auto;">
                        <span class="health-dot ${dhDotClass}" style="width:8px;height:8px;"></span>
                        <span style="font-size:10px;color:var(--text-dim);">Data Health</span>
                        <span style="font-size:11px;font-weight:600;">${dataHealth}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Per-Head Report Cards -->
        <div style="margin-top:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">
                    ◆ Head Reports (${headList.length})
                </span>
            </div>
            ${headList.length === 0
                ? '<div class="placeholder-message small" style="padding:20px 0;"><div class="placeholder-text">No head reports available</div></div>'
                : headList.map((h, i) => renderHeadDetailCard(h, i)).join('')
            }
        </div>
    `;

    container.innerHTML = html;

    // Wire up expand buttons
    container.querySelectorAll('.head-detail-expand').forEach(btn => {
        btn.addEventListener('click', async () => {
            const headName = btn.dataset.headName;
            const detailBody = document.getElementById(`head-detail-${CSS.escape(headName)}`);
            if (!detailBody) return;

            // Toggle
            if (detailBody.classList.contains('expanded')) {
                detailBody.classList.remove('expanded');
                detailBody.style.display = 'none';
                btn.textContent = '▼';
                return;
            }

            // Show loading
            detailBody.style.display = 'block';
            detailBody.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-dim);font-size:11px;">Loading detail...</div>';
            btn.textContent = '▲';

            try {
                const detail = await api.getHeadDetail(headName);
                detailBody.innerHTML = buildHeadDetailBody(detail);
                detailBody.classList.add('expanded');
            } catch (e) {
                detailBody.innerHTML = `<div style="padding:12px;text-align:center;color:var(--text-red);font-size:11px;">Failed to load: ${e.message}</div>`;
                btn.textContent = '▼';
            }
        });
    });
}

/**
 * Render a single head detail card for the right panel.
 * @param {object} h - head report from state
 * @param {number} idx
 * @returns {string}
 */
function renderHeadDetailCard(h, idx) {
    const name = h.head_name || 'Unknown';
    const stateVal = h.state || 'READY';
    const bias = h.bias || 'NEUTRAL';
    const confidence = h.confidence ?? 0;
    const freshness = h.freshness_tag || 'FRESH';
    const cqs = h.context_quality_score;
    const primarySetup = h.primary_setup;
    const backupSetup = h.backup_setup;
    const noSetup = h.no_setup_flag || false;

    // State badge
    const stateClass = stateVal.toLowerCase();
    const stateDot = stateVal === 'READY' ? '🟢'
        : stateVal === 'UNCERTAIN' ? '🟡'
        : stateVal === 'STALE' ? '🔴'
        : stateVal === 'ERROR' ? '⛔'
        : '⚪';

    // Bias emoji
    const biasIcon = bias === 'NEUTRAL' ? '⚪'
        : bias === 'BULLISH' ? '📈'
        : bias === 'BEARISH' ? '📉'
        : bias === 'MIXED' ? '🔀'
        : '⚪';

    // Freshness
    const freshnessClass = freshness === 'FRESH' ? 'text-green'
        : freshness === 'RECENT' ? 'text-yellow'
        : freshness === 'STALE' ? 'text-red'
        : 'text-muted';

    const confPct = Math.round(confidence * 100);
    const confColor = confidenceColor(confidence);

    // Setup info
    let setupHtml = '';
    if (noSetup) {
        setupHtml = '<span class="status-tag">No Setup (flagged)</span>';
    } else if (primarySetup) {
        setupHtml = `<span class="status-tag">${escapeHtml(primarySetup)}</span>`;
        if (backupSetup) {
            setupHtml += ` <span class="status-tag" style="background:var(--bg-surface);border:1px solid var(--border-subtle);">B: ${escapeHtml(backupSetup)}</span>`;
        }
    } else {
        setupHtml = '<span class="panel-value text-muted" style="font-size:10px;">No setup</span>';
    }

    // CQS
    let cqsHtml = '';
    if (cqs !== null && cqs !== undefined) {
        const cqsColor = cqs >= 0.7 ? 'text-green' : cqs >= 0.4 ? 'text-yellow' : 'text-red';
        cqsHtml = `<div style="display:flex;align-items:center;gap:4px;"><span style="font-size:9px;color:var(--text-dim);">CQ:</span><span class="${cqsColor}" style="font-size:11px;font-weight:600;font-family:var(--font-mono);">${cqs.toFixed(2)}</span></div>`;
    }

    // Confidence bar color as left border
    const borderColor = confidence >= 0.7 ? 'var(--green-500)'
        : confidence >= 0.4 ? 'var(--yellow-500)'
        : confidence >= 0.2 ? 'var(--orange-500)'
        : 'var(--red-500)';

    return `
        <div style="background:var(--bg-elevated);border-radius:6px;margin-bottom:6px;border-left:3px solid ${borderColor};overflow:hidden;">
            <!-- Header row (always visible) -->
            <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;cursor:pointer;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:13px;font-weight:600;color:var(--text-primary);">${escapeHtml(name)}</span>
                    <span class="status-tag ${stateClass}" style="font-size:9px;padding:2px 6px;">${stateDot} ${stateVal}</span>
                    <span style="font-size:12px;">${biasIcon} ${bias}</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:11px;font-weight:600;font-family:var(--font-mono);color:${confColor};">${confPct}%</span>
                    <span class="${freshnessClass}" style="font-size:10px;font-family:var(--font-mono);">${freshness}</span>
                    <button class="head-detail-expand icon-btn" data-head-name="${escapeHtml(name)}" style="font-size:10px;padding:2px 6px;" title="Expand detail">▼</button>
                </div>
            </div>

            <!-- Compact info row -->
            <div style="display:flex;gap:10px;padding:0 10px 6px 10px;align-items:center;">
                <!-- Confidence mini-bar -->
                <div class="conviction-bar" style="flex:1;max-width:100px;height:5px;background:var(--bg-surface);border-radius:3px;overflow:hidden;">
                    <div style="width:${confPct}%;height:100%;border-radius:3px;background:${confColor};transition:width 0.3s;"></div>
                </div>
                ${cqsHtml}
                ${setupHtml}
            </div>

            <!-- Expandable detail body (fetched on demand) -->
            <div id="head-detail-${CSS.escape(name)}" class="head-detail-body" style="display:none;border-top:1px solid var(--border-subtle);padding:10px 12px;background:var(--bg-surface);">
            </div>
        </div>
    `;
}

/**
 * Build the expanded detail body HTML for a head report.
 * @param {object} detail - response from /api/heads/{head_name}
 * @returns {string}
 */
function buildHeadDetailBody(detail) {
    const stateVal = detail.state || 'READY';
    const stateDot = stateVal === 'READY' ? '🟢'
        : stateVal === 'UNCERTAIN' ? '🟡'
        : stateVal === 'STALE' ? '🔴'
        : stateVal === 'ERROR' ? '⛔'
        : '⚪';

    const invalidation = detail.invalidation_summary || '';

    let html = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <div>
            <div class="panel-row"><span class="panel-label">Status</span><span class="panel-value">${stateDot} ${stateVal}</span></div>
            <div class="panel-row"><span class="panel-label">Bias</span><span class="panel-value">${detail.bias || 'NEUTRAL'}</span></div>
            <div class="panel-row"><span class="panel-label">Confidence</span><span class="panel-value mono">${((detail.confidence ?? 0) * 100).toFixed(1)}%</span></div>
            <div class="panel-row"><span class="panel-label">Freshness</span><span class="panel-value">${detail.freshness_tag || 'FRESH'}</span></div>
        </div>
        <div>
            <div class="panel-row"><span class="panel-label">Setup</span><span class="panel-value mono">${escapeHtml(detail.primary_setup || 'None')}</span></div>
            <div class="panel-row"><span class="panel-label">Backup</span><span class="panel-value mono">${escapeHtml(detail.backup_setup || 'None')}</span></div>
            <div class="panel-row"><span class="panel-label">CQ Score</span><span class="panel-value mono">${detail.context_quality_score != null ? detail.context_quality_score.toFixed(3) : '-'}</span></div>
            <div class="panel-row"><span class="panel-label">No Setup</span><span class="panel-value">${detail.no_setup_flag ? '⚠ Yes' : 'No'}</span></div>
        </div>
    </div>`;

    if (invalidation) {
        html += `<div style="margin-top:8px;padding:8px 10px;background:var(--bg-elevated);border-radius:4px;border-left:3px solid var(--red-500);">
            <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px;">Invalidation</div>
            <div style="font-size:11px;color:var(--text-secondary);line-height:1.5;">${escapeHtml(invalidation)}</div>
        </div>`;
    }



    return html;
}

/* ══════════════════════════════════════════════════════════════
   Floor Drill-down Renderer
   ══════════════════════════════════════════════════════════════ */

/**
 * Render floor drill-down detail in the right panel.
 * @param {HTMLElement} container - right panel content
 * @param {string} componentName - e.g. 'floor_1', 'floor_5', 'side_a'
 */
function renderFloorDrilldown(container, componentName) {
    FloorDrilldown.render(container, componentName);
}

/* ══════════════════════════════════════════════════════════════
   Shared Helpers
   ══════════════════════════════════════════════════════════════ */

/** Map a confidence value (0-1) to a hex color string. */
function confidenceColor(confidence) {
    if (confidence >= 0.8) return 'var(--green-500)';
    if (confidence >= 0.6) return 'var(--green-400)';
    if (confidence >= 0.4) return 'var(--yellow-500)';
    if (confidence >= 0.2) return 'var(--orange-500)';
    return 'var(--red-500)';
}

/** Escape HTML special characters. */
function escapeHtml(str) {
    if (str == null) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

function renderMarketDetail(container) {
    const market = StateManager.get('market', {});
    container.innerHTML = `
        <div class="panel-card"><div class="panel-card-body">
            <div class="panel-row"><span class="panel-label">Symbol</span><span class="panel-value">${market.symbol || 'NIFTY 50'}</span></div>
            <div class="panel-row"><span class="panel-label">LTP</span><span class="panel-value mono">${(market.ltp ?? 0).toFixed(2)}</span></div>
            <div class="panel-row"><span class="panel-label">Change</span><span class="panel-value mono ${(market.change ?? 0) >= 0 ? 'text-green' : 'text-red'}">${(market.change ?? 0).toFixed(2)} (${(market.change_percent ?? 0).toFixed(2)}%)</span></div>
            <div class="panel-row"><span class="panel-label">Open</span><span class="panel-value mono">${(market.open ?? 0).toFixed(2)}</span></div>
            <div class="panel-row"><span class="panel-label">High</span><span class="panel-value mono">${(market.high ?? 0).toFixed(2)}</span></div>
            <div class="panel-row"><span class="panel-label">Low</span><span class="panel-value mono">${(market.low ?? 0).toFixed(2)}</span></div>
            <div class="panel-row"><span class="panel-label">Prev Close</span><span class="panel-value mono">${(market.prev_close ?? 0).toFixed(2)}</span></div>
            <div class="panel-row"><span class="panel-label">Volume</span><span class="panel-value mono">${(market.volume ?? 0).toLocaleString()}</span></div>
            <div class="panel-row"><span class="panel-label">VWAP</span><span class="panel-value mono">${(market.vwap ?? 0).toFixed(2)}</span></div>
            <div class="panel-row"><span class="panel-label">Session</span><span class="panel-value">${market.session || '-'}</span></div>
        </div></div>
    `;
}

/* ══════════════════════════════════════════════════════════════
   Status Bar Updates
   ══════════════════════════════════════════════════════════════ */

let clockInterval = null;

function startClock() {
    clockInterval = setInterval(() => {
        const now = new Date();
        const time = now.toTimeString().slice(0, 8);
        document.getElementById('clock').textContent = time;
        StateManager.set('clock', time);
    }, 1000);
}

function updateConnectionStatus(connected) {
    const status = document.getElementById('connection-status');
    const dot = status.querySelector('.conn-dot');
    const label = status.querySelector('.conn-label');
    dot.className = `conn-dot conn-${connected ? 'connected' : 'disconnected'}`;
    label.textContent = connected ? 'Connected' : 'Disconnected';
    StateManager.set('connected', connected);
}

function updateHealthDisplay(health) {
    if (!health) return;
    const healthStrip = document.getElementById('health-strip');
    if (healthStrip) {
        const overall = (health.overall_status || '').toLowerCase();
        healthStrip.innerHTML = `<span class="health-dot health-${overall === 'good' ? 'good' : overall === 'degraded' ? 'degraded' : 'critical'}" title="System: ${health.overall_status}"></span>`;
    }
    const statusHealth = document.getElementById('status-health');
    if (statusHealth) {
        const overall = (health.overall_status || '').toLowerCase();
        statusHealth.innerHTML = `<span class="health-dot health-${overall === 'good' ? 'good' : overall === 'degraded' ? 'degraded' : 'critical'}"></span> ${health.overall_status || 'UNKNOWN'}`;
    }
}

function updateAlertBadge(alerts) {
    if (!alerts) return;
    const count = alerts.count ?? alerts.alerts?.length ?? 0;
    const badge = document.getElementById('alert-count');
    if (!badge) return;
    badge.textContent = count;
    badge.className = `alert-count ${count > 0 ? 'has-alerts' : ''}`;
    const hasCritical = (alerts.alerts || []).some(a => a.severity === 'CRITICAL');
    if (hasCritical) badge.classList.add('has-critical');
    setText('alerts-count', count.toString());
}

function updateCacheDisplay(cache) {
    if (!cache) return;
    const entries = document.getElementById('cache-entries');
    const hitRatio = document.getElementById('cache-hit-ratio');
    const hot = document.getElementById('cache-hot');
    const warm = document.getElementById('cache-warm');
    const cold = document.getElementById('cache-cold');
    if (entries) entries.textContent = cache.total_entries ?? '-';
    if (hitRatio) hitRatio.textContent = cache.hit_ratio != null ? (cache.hit_ratio * 100).toFixed(1) + '%' : '-';
    if (hot) hot.textContent = cache.tier_counts?.HOT ?? '-';
    if (warm) warm.textContent = cache.tier_counts?.WARM ?? '-';
    if (cold) cold.textContent = cache.tier_counts?.COLD ?? '-';
}

function updateStatusBar() {
    const cache = StateManager.get('cache');
    const market = StateManager.get('market');
    const exec = StateManager.get('execution', {});
    const intv = RefreshScheduler.getIntervals();
    setText('session-info', `Session: ${new Date().toLocaleDateString()}`);
    setText('refresh-info', `HOT: ${intv.hot}ms | WARM: ${intv.warm}ms | COLD: ${intv.cold}ms`);
    setText('market-status', `Market: ${(market && market.session) || 'CLOSED'}`);
    setText('bottom-mode', `Mode: ${exec.mode || 'ALERT'}`);
    const cap = exec.capital_limit;
    setText('bottom-capital', cap != null ? `Capital: ₹${Number(cap).toLocaleString('en-IN')}` : 'Capital: --');
    setText('cache-info', `Cache: ${(cache && cache.total_entries) ?? 0} entries`);
    setText('api-status', `WS: ${window.wsClient && window.wsClient.connected ? 'Connected' : 'Polling'}`);
}

/* ══════════════════════════════════════════════════════════════
   Utilities
   ══════════════════════════════════════════════════════════════ */

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function renderPlaceholder(container, icon, title, text) {
    container.innerHTML = `
        <div class="placeholder-message">
            <div class="placeholder-icon">${icon}</div>
            <div class="placeholder-title">${title}</div>
            <div class="placeholder-text">${text}</div>
        </div>
    `;
}
