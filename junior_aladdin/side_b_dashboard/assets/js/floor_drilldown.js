/**
 * Junior Aladdin — Operator Terminal
 * floor_drilldown.js — Per-floor module detail view
 *
 * Renders an expandable, module-level state view for a given floor/side
 * component. Triggered by clicking a health dot / component row in
 * the health panel. Mounted in the right panel.
 *
 * Reference: ROADMAP_SIDE_B Step 8.12 — Floor Drill-down
 */

const FloorDrilldown = {
    /** @type {HTMLElement|null} */
    _container: null,

    /** @type {string|null} Current component name */
    _componentName: null,

    /**
     * Render floor drill-down into a container.
     * @param {HTMLElement} container - right panel content element
     * @param {string} componentName - e.g. 'floor_1', 'floor_5', 'side_a'
     */
    render(container, componentName) {
        this._container = container;
        this._componentName = componentName;
        this._render();
        this._fetchDetail();
    },

    /** Clean up */
    unmount() {
        this._container = null;
        this._componentName = null;
    },

    /** @private */
    _render() {
        if (!this._container || !this._componentName) return;

        const health = StateManager.get('health', {});
        const allFloors = health.floors || {};
        const allSides = health.sides || {};
        const comp = allFloors[this._componentName] || allSides[this._componentName] || null;

        const name = this._componentName;
        const state = comp ? comp.state || 'UNKNOWN' : 'UNKNOWN';
        const lifecycle = comp ? comp.lifecycle || '' : '';
        const detail = comp ? comp.detail || '' : '';

        const stateClass = state.toLowerCase().replace(/[^a-z]/g, '');
        const stateDot = stateClass === 'healthy' || stateClass === 'connected' ? '🟢'
            : stateClass === 'degraded' || stateClass === 'stale' ? '🟡'
            : stateClass === 'critical' || stateClass === 'error' ? '🔴'
            : stateClass === 'unavailable' ? '⚫'
            : '⚪';

        let html = `
        <div class="panel-card">
            <div class="panel-card-header" style="border-bottom:2px solid ${this._stateColor(stateClass)};">
                <span class="panel-card-title">${stateDot} ${this._escapeHtml(name)}</span>
                <span class="panel-card-badge">
                    <span class="health-dot health-${stateClass === 'healthy' || stateClass === 'connected' ? 'good' : stateClass === 'degraded' || stateClass === 'stale' ? 'degraded' : stateClass === 'critical' || stateClass === 'error' ? 'critical' : 'unknown'}" style="width:8px;height:8px;margin-right:4px;"></span>
                    ${state}
                </span>
            </div>
            <div class="panel-card-body">
                <!-- Primary state strip -->
                <div class="panel-row">
                    <span class="panel-label">State</span>
                    <span class="status-tag ${stateClass}">${state}</span>
                </div>
                ${lifecycle ? `
                <div class="panel-row">
                    <span class="panel-label">Lifecycle</span>
                    <span class="panel-value">${this._escapeHtml(lifecycle)}</span>
                </div>` : ''}
                ${detail ? `
                <div class="panel-row" style="align-items:flex-start;">
                    <span class="panel-label">Detail</span>
                    <span class="panel-value" style="font-size:10px;max-width:200px;text-align:right;word-break:break-all;">${this._escapeHtml(detail)}</span>
                </div>` : ''}
                <div class="panel-row">
                    <span class="panel-label">Timestamp</span>
                    <span class="panel-value mono">${health.timestamp ? new Date(health.timestamp).toLocaleTimeString() : '--:--:--'}</span>
                </div>
            </div>
        </div>

        <!-- Module Status (loaded from API) -->
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">📦 Modules</span>
                <span class="panel-card-badge" id="fd-modules-badge">Loading...</span>
            </div>
            <div class="panel-card-body" id="fd-modules-list">
                <div style="text-align:center;padding:20px;color:var(--text-dim);">
                    <div class="loading-spinner" style="width:20px;height:20px;margin:0 auto 8px;border-width:2px;"></div>
                    <div style="font-size:10px;">Fetching module details...</div>
                </div>
            </div>
        </div>

        <!-- Troubleshooting / Actions -->
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">⚡ Actions</span>
            </div>
            <div class="panel-card-body">
                <button class="control-btn" style="width:100%;margin-bottom:4px;" id="fd-refresh-btn">
                    ↻ Refresh Module Data
                </button>
                <a href="/api/health/${this._escapeHtml(this._componentName)}" target="_blank" style="text-decoration:none;">
                    <button class="control-btn" style="width:100%;background:transparent;border:1px solid var(--border-default);">
                        📡 Raw API Response
                    </button>
                </a>
            </div>
        </div>
        `;

        this._container.innerHTML = html;

        // Wire refresh button
        const refreshBtn = document.getElementById('fd-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this._fetchDetail());
        }
    },

    /**
     * Fetch component detail from API and render modules.
     * @private
     */
    async _fetchDetail() {
        if (!this._container || !this._componentName) return;

        const badge = document.getElementById('fd-modules-badge');
        const listEl = document.getElementById('fd-modules-list');
        if (!listEl) return;

        try {
            // Try to get component health detail from API
            const detail = await api.getComponentHealth(this._componentName);
            this._renderModules(detail);
            if (badge) badge.textContent = 'Loaded';
        } catch (e) {
            // Fallback: use health panel data from StateManager
            console.warn('[FloorDrilldown] API fetch failed, using cached state:', e.message);
            const health = StateManager.get('health', {});
            const allFloors = health.floors || {};
            const allSides = health.sides || {};
            const comp = allFloors[this._componentName] || allSides[this._componentName] || {};

            this._renderModulesFallback(comp);
            if (badge) badge.textContent = 'Cached';
        }
    },

    /**
     * Render modules from API response.
     * @private
     * @param {object} detail - response from /api/health/{component}
     */
    _renderModules(detail) {
        const listEl = document.getElementById('fd-modules-list');
        if (!listEl) return;

        const modules = this._extractModules(detail);

        if (modules.length === 0) {
            listEl.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text">No module details available for this component</div>
                </div>
            `;
            return;
        }

        // Group modules by category
        const categories = this._groupByCategory(modules);
        const categoryOrder = ['core', 'data', 'network', 'processing', 'storage', 'other'];

        let html = '';
        categoryOrder.forEach(cat => {
            const items = categories[cat];
            if (!items || items.length === 0) return;

            const catLabels = {
                core: '⚙ Core',
                data: '📊 Data',
                network: '🌐 Network',
                processing: '⚡ Processing',
                storage: '💾 Storage',
                other: '📦 Other',
            };

            html += `
            <div style="margin-bottom:10px;">
                <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;margin-bottom:4px;padding-left:2px;">
                    ${catLabels[cat] || cat}
                </div>
                ${items.map(m => this._moduleCard(m)).join('')}
            </div>`;
        });

        // Add any uncategorized modules
        const categorized = new Set(Object.values(categories).flat().map(m => m.name));
        const uncategorized = modules.filter(m => !categorized.has(m.name));
        if (uncategorized.length > 0) {
            html += `
            <div style="margin-bottom:10px;">
                <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;margin-bottom:4px;padding-left:2px;">
                    📦 Modules
                </div>
                ${uncategorized.map(m => this._moduleCard(m)).join('')}
            </div>`;
        }

        listEl.innerHTML = html;
    },

    /**
     * Fallback: render from cached StateManager data.
     * @private
     */
    _renderModulesFallback(comp) {
        const listEl = document.getElementById('fd-modules-list');
        if (!listEl) return;

        // Try to extract meaningful sub-modules from the component state
        const modules = this._extractFallbackModules(this._componentName);

        if (modules.length === 0) {
            listEl.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text">Cached: ${comp.state || 'UNKNOWN'} | ${comp.lifecycle || ''} | ${comp.detail || 'No detail'}</div>
                </div>
            `;
            return;
        }

        listEl.innerHTML = `
            <div style="margin-bottom:4px;">
                <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;margin-bottom:4px;padding-left:2px;">
                    📦 Known Modules
                </div>
                ${modules.map(m => this._moduleCard(m)).join('')}
            </div>
            <div style="margin-top:8px;padding:6px 8px;background:var(--bg-elevated);border-radius:4px;font-size:9px;color:var(--text-dim);text-align:center;">
                ⚡ Data from cached health snapshot. Click ↻ Refresh to fetch live data.
            </div>
        `;
    },

    /**
     * Build a module card HTML.
     * @private
     * @param {object} module - { name, state, detail, metrics }
     * @returns {string}
     */
    _moduleCard(module) {
        const stateClass = (module.state || 'unknown').toLowerCase().replace(/[^a-z]/g, '');
        const isHealthy = stateClass === 'healthy' || stateClass === 'connected' || stateClass === 'ready';
        const isWarning = stateClass === 'degraded' || stateClass === 'stale' || stateClass === 'uncertain';
        const isCritical = stateClass === 'critical' || stateClass === 'error' || stateClass === 'disconnected';

        const borderColor = isHealthy ? 'var(--green-500)'
            : isWarning ? 'var(--yellow-500)'
            : isCritical ? 'var(--red-500)'
            : 'var(--border-default)';

        const dotClass = isHealthy ? 'health-good'
            : isWarning ? 'health-degraded'
            : isCritical ? 'health-critical'
            : 'health-unknown';

        let metricsHtml = '';
        if (module.metrics && Object.keys(module.metrics).length > 0) {
            metricsHtml = `
            <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;padding-top:4px;border-top:1px solid var(--border-subtle);">
                ${Object.entries(module.metrics).map(([key, val]) => `
                    <div style="display:flex;align-items:center;gap:3px;">
                        <span style="font-size:8px;color:var(--text-dim);text-transform:uppercase;">${key}</span>
                        <span style="font-size:10px;font-weight:600;font-family:var(--font-mono);color:var(--text-secondary);">${val ?? '—'}</span>
                    </div>
                `).join('')}
            </div>`;
        }

        return `
        <div class="panel-row" style="border-left:2px solid ${borderColor};padding-left:8px;margin-bottom:4px;background:var(--bg-elevated);border-radius:4px;padding:6px 8px;flex-direction:column;align-items:stretch;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="display:flex;align-items:center;gap:5px;">
                    <span class="health-dot ${dotClass}" style="width:6px;height:6px;flex-shrink:0;"></span>
                    <span style="font-size:11px;font-weight:500;color:var(--text-primary);">${this._escapeHtml(module.name)}</span>
                </span>
                <span class="status-tag ${stateClass}" style="font-size:9px;padding:1px 6px;">${module.state || 'UNKNOWN'}</span>
            </div>
            ${module.detail ? `
            <div style="font-size:9px;color:var(--text-muted);margin-top:2px;padding-left:11px;">
                ${this._escapeHtml(module.detail)}
            </div>` : ''}
            ${metricsHtml}
        </div>
        `;
    },

    /**
     * Extract structured modules from API detail response.
     * @private
     */
    _extractModules(detail) {
        const modules = [];
        if (!detail) return modules;

        // Primary module: the component itself
        modules.push({
            name: detail.name || this._componentName || 'Component',
            state: detail.state || 'UNKNOWN',
            detail: detail.detail || '',
            metrics: {
                lifecycle: detail.lifecycle || '',
                updated: detail.last_update ? new Date(detail.last_update).toLocaleTimeString() : '',
            },
        });

        // Try to parse sub-modules from detail string (JSON in detail field)
        if (detail.detail && typeof detail.detail === 'string') {
            if (detail.detail.startsWith('{') || detail.detail.startsWith('[')) {
                try {
                    const parsed = JSON.parse(detail.detail);
                    if (Array.isArray(parsed)) {
                        parsed.forEach((item, i) => {
                            modules.push({
                                name: item.name || item.module || `Module ${i + 1}`,
                                state: item.state || item.status || 'UNKNOWN',
                                detail: item.detail || item.message || '',
                                metrics: item.metrics || {},
                            });
                        });
                    } else if (typeof parsed === 'object') {
                        Object.entries(parsed).forEach(([key, val]) => {
                            if (typeof val === 'object' && val !== null) {
                                modules.push({
                                    name: key,
                                    state: val.state || val.status || 'UNKNOWN',
                                    detail: val.detail || val.message || '',
                                    metrics: val.metrics || {},
                                });
                            }
                        });
                    }
                } catch (e) {
                    // Not parseable, use detail as text
                }
            }
        }

        return modules;
    },

    /**
     * Extract known fallback modules for a component from floor data.
     * @private
     */
    _extractFallbackModules(componentName) {
        const health = StateManager.get('health', {});
        const allFloors = health.floors || {};

        // Known modules per floor
        const floorModules = {
            'floor_1': [
                { name: 'Source Health Monitor', state: 'UNKNOWN', detail: 'Monitors connection health and latency', metrics: { status: '—' } },
                { name: 'Auth Manager', state: 'UNKNOWN', detail: 'Manages broker authentication', metrics: { status: '—' } },
                { name: 'Feed Adapters', state: 'UNKNOWN', detail: 'Market data feed connections', metrics: { status: '—' } },
                { name: 'Packet Envelope', state: 'UNKNOWN', detail: 'Data packet normalization', metrics: { status: '—' } },
                { name: 'Ingress Router', state: 'UNKNOWN', detail: 'Routes incoming market data', metrics: { status: '—' } },
            ],
            'floor_2': [
                { name: 'Data Ingest', state: 'UNKNOWN', detail: 'Raw data ingestion pipeline', metrics: { rate: '—' } },
                { name: 'Validation', state: 'UNKNOWN', detail: 'Data quality validation', metrics: { passed: '—', failed: '—' } },
                { name: 'Structuring', state: 'UNKNOWN', detail: 'Data normalization & enrichment', metrics: { status: '—' } },
                { name: 'Review Engine', state: 'UNKNOWN', detail: 'Data quality review', metrics: { status: '—' } },
                { name: 'Cleaning', state: 'UNKNOWN', detail: 'Anomaly detection & repair', metrics: { status: '—' } },
                { name: 'Raw Storage', state: 'UNKNOWN', detail: 'Raw data store with retention', metrics: { entries: '—' } },
            ],
            'floor_3': [
                { name: 'Market Structure', state: 'UNKNOWN', detail: 'Market structure analysis', metrics: { status: '—' } },
                { name: 'SMC Engine', state: 'UNKNOWN', detail: 'Smart Money Concepts analysis', metrics: { status: '—' } },
                { name: 'ICT Engine', state: 'UNKNOWN', detail: 'ICT concepts analysis', metrics: { status: '—' } },
                { name: 'Technical Analysis', state: 'UNKNOWN', detail: 'Technical indicators', metrics: { status: '—' } },
                { name: 'Macro Analysis', state: 'UNKNOWN', detail: 'Macroeconomic analysis', metrics: { status: '—' } },
                { name: 'Options Analysis', state: 'UNKNOWN', detail: 'Options chain analysis', metrics: { status: '—' } },
            ],
            'floor_4': [
                { name: 'Heads Engine', state: 'UNKNOWN', detail: 'Department head modules', metrics: { ready: '—', total: '—' } },
                { name: 'Floor Summary', state: 'UNKNOWN', detail: 'Aggregated floor summary', metrics: { bias: '—', confidence: '—' } },
            ],
            'floor_5': [
                { name: 'Captain Engine', state: 'UNKNOWN', detail: 'Trade decision engine', metrics: { decision: '—', conviction: '—' } },
                { name: 'Decision Snapshot', state: 'UNKNOWN', detail: 'Decision state manager', metrics: { state: '—' } },
                { name: 'Armed Plans', state: 'UNKNOWN', detail: 'Pre-planned strategies', metrics: { count: '—' } },
            ],
            'side_a': [
                { name: 'Execution Engine', state: 'UNKNOWN', detail: 'Order execution handler', metrics: { active: '—' } },
                { name: 'Position Manager', state: 'UNKNOWN', detail: 'Position & risk tracking', metrics: { pnl: '—' } },
            ],
            'side_b': [
                { name: 'API Server', state: 'UNKNOWN', detail: 'REST API endpoint', metrics: { status: '—' } },
                { name: 'WebSocket Server', state: 'UNKNOWN', detail: 'Real-time data push', metrics: { status: '—' } },
                { name: 'Operator Terminal', state: 'UNKNOWN', detail: 'Dashboard UI', metrics: { status: '—' } },
            ],
            'side_c': [
                { name: 'Event Store', state: 'UNKNOWN', detail: 'Persistent event journal', metrics: { events: '—' } },
                { name: 'Read Model', state: 'UNKNOWN', detail: 'CQRS read model', metrics: { status: '—' } },
                { name: 'Retention Manager', state: 'UNKNOWN', detail: 'Data lifecycle management', metrics: { status: '—' } },
            ],
        };

        const modules = floorModules[componentName] || [];

        // Try to update states from health data if component exists
        const comp = allFloors[componentName] || null;
        if (comp && modules.length > 0) {
            // Apply component state to first module as default
            modules[0].state = comp.state || modules[0].state;
            if (comp.detail) {
                modules[0].detail = comp.detail;
            }
        }

        return modules;
    },

    /**
     * Group modules by category based on name keywords.
     * @private
     */
    _groupByCategory(modules) {
        const categories = {};

        modules.forEach(m => {
            const name = (m.name || '').toLowerCase();
            let cat = 'other';

            if (name.includes('source') || name.includes('connection') || name.includes('feed') || name.includes('ingress')) cat = 'network';
            else if (name.includes('auth') || name.includes('engine') || name.includes('captain') || name.includes('head') || name.includes('summary')) cat = 'core';
            else if (name.includes('data') || name.includes('ingest') || name.includes('store') || name.includes('events')) cat = 'data';
            else if (name.includes('valid') || name.includes('clean') || name.includes('review') || name.includes('structur')) cat = 'processing';
            else if (name.includes('storage') || name.includes('retention') || name.includes('archive')) cat = 'storage';

            if (!categories[cat]) categories[cat] = [];
            categories[cat].push(m);
        });

        return categories;
    },

    /**
     * Map state class to CSS color value.
     * @private
     */
    _stateColor(stateClass) {
        switch (stateClass) {
            case 'healthy': case 'connected': case 'good': return 'var(--green-500)';
            case 'degraded': case 'stale': case 'uncertain': return 'var(--yellow-500)';
            case 'critical': case 'error': case 'disconnected': return 'var(--red-500)';
            default: return 'var(--border-default)';
        }
    },

    /** @private */
    _escapeHtml(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    },
};
