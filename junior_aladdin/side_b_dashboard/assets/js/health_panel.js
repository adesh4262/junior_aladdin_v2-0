/**
 * Junior Aladdin — Operator Terminal
 * health_panel.js — System health surface component
 *
 * Shows per-floor/side status, data health signal, connection status.
 * Click on any component → opens right panel drill-down.
 *
 * Reference: ROADMAP_SIDE_B Step 8.12
 */

const HealthPanel = {
    /** @type {HTMLElement|null} */
    _container: null,

    /**
     * Mount the health panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._render();

        // Subscribe to health state changes
        this._unsubscribe = StateManager.subscribe('health', (health) => {
            if (health) this._render();
        });
    },

    /** Unmount and clean up */
    unmount() {
        if (this._unsubscribe) this._unsubscribe();
        this._container = null;
    },

    /**
     * Update with new data.
     * @param {object} state - health state
     */
    update(state) {
        if (state && this._container) this._render();
    },

    /** @private */
    _render() {
        if (!this._container) return;
        const health = StateManager.get('health', {});
        const floors = health.floors || {};
        const sides = health.sides || {};

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">● System Health</span>
                <span class="panel-card-badge refresh-hot">HOT</span>
            </div>
            <div class="panel-card-body">
                <div class="panel-row">
                    <span class="panel-label">Overall</span>
                    <span class="panel-value" id="health-overall">
                        <span class="health-dot health-${this._overallClass(health.overall_status)}"></span>
                        ${health.overall_status || 'UNKNOWN'}
                    </span>
                </div>
                <div class="panel-row">
                    <span class="panel-label">Data Health</span>
                    <span class="status-tag ${(health.data_health_signal || '').toLowerCase()}">${health.data_health_signal || 'UNKNOWN'}</span>
                </div>
                <div class="panel-row">
                    <span class="panel-label">Connection</span>
                    <span class="panel-value">${health.connection_status || 'UNKNOWN'}</span>
                </div>
                <div class="panel-row">
                    <span class="panel-label">Critical Alerts</span>
                    <span class="panel-value ${(health.critical_alert_count || 0) > 0 ? 'text-red' : ''}">${health.critical_alert_count ?? 0}</span>
                </div>
            </div>
        </div>

        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">Floors</span>
                <span class="panel-card-badge">${Object.keys(floors).length} active</span>
            </div>
            <div class="panel-card-body" id="health-floors-list">
                ${this._renderComponentList(floors, 'floor')}
            </div>
        </div>

        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">Sides</span>
                <span class="panel-card-badge">${Object.keys(sides).length} active</span>
            </div>
            <div class="panel-card-body" id="health-sides-list">
                ${Object.keys(sides).length === 0 ? '<div class="panel-value text-muted">No sides active</div>' : ''}
                ${this._renderComponentList(sides, 'side')}
            </div>
        </div>

        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">Timeline</span>
                <span class="panel-card-badge refresh-cold">COLD</span>
            </div>
            <div class="panel-card-body">
                <div class="panel-row">
                    <span class="panel-label">Last Updated</span>
                    <span class="panel-value mono">${health.timestamp ? new Date(health.timestamp).toLocaleTimeString() : '--:--:--'}</span>
                </div>
            </div>
        </div>
        `;

        this._container.innerHTML = html;

        // Bind click handlers for component drill-down
        this._container.querySelectorAll('[data-component]').forEach(el => {
            el.addEventListener('click', () => {
                const component = el.dataset.component;
                openRightPanel('health');
                // Could add specific component focus here
            });
        });
    },

    /** @private */
    _renderComponentList(components, prefix) {
        return Object.entries(components).map(([name, comp]) => {
            const stateClass = (comp.state || '').toLowerCase().replace(/[^a-z]/g, '');
            const lifeCycle = (comp.lifecycle || '').toLowerCase();
            const isDegraded = ['degraded', 'error', 'critical', 'unavailable'].includes(stateClass);
            return `
            <div class="panel-row health-component" data-component="${name}" style="cursor:pointer;${isDegraded ? 'border-left:2px solid var(--red-500);padding-left:8px;' : ''}">
                <span class="panel-label">
                    <span class="health-dot health-${stateClass === 'healthy' ? 'good' : isDegraded ? 'critical' : 'unknown'}"></span>
                    ${name}
                </span>
                <span>
                    <span class="status-tag ${stateClass}">${comp.state || 'UNKNOWN'}</span>
                    ${lifeCycle ? `<span class="panel-value text-muted" style="font-size:9px;margin-left:4px;">${lifeCycle}</span>` : ''}
                </span>
            </div>
            `;
        }).join('');
    },

    /** @private */
    _overallClass(status) {
        const s = (status || '').toLowerCase();
        if (s === 'good') return 'good';
        if (['degraded', 'stale'].includes(s)) return 'degraded';
        if (['critical', 'error'].includes(s)) return 'critical';
        return 'unknown';
    }
};

// Register with ComponentManager
ComponentManager.register('health', HealthPanel);
