/**
 * Junior Aladdin — Operator Terminal
 * alert_panel.js — Alert feed component
 *
 * Shows active alerts sorted by severity, with acknowledge buttons,
 * filter by severity/category, and scrollable history.
 *
 * Alert severity: INFO / CAUTION / SEVERE / CRITICAL (color-coded)
 * Alert categories: EXECUTION / HEALTH / RISK / DATA / GOVERNANCE / OPERATOR / SYSTEM
 *
 * Reference: ROADMAP_SIDE_B Step 8.12
 */

const AlertPanel = {
    /** @type {HTMLElement|null} */
    _container: null,
    _filterSeverity: null,
    _filterCategory: null,
    _showHistory: false,

    /**
     * Mount the alert panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._filterSeverity = null;
        this._filterCategory = null;
        this._showHistory = false;
        this._render();

        // Subscribe to alerts state
        this._unsubscribe = StateManager.subscribe('alerts', (alerts) => {
            if (alerts) this._render();
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
        const alerts = StateManager.get('alerts', { alerts: [], count: 0 });
        const allAlerts = alerts.alerts || [];

        // Apply filters
        let filtered = allAlerts;
        if (this._filterSeverity) {
            filtered = filtered.filter(a => (a.severity || '').toUpperCase() === this._filterSeverity);
        }
        if (this._filterCategory) {
            filtered = filtered.filter(a => (a.category || '').toUpperCase() === this._filterCategory);
        }

        // Separate active vs acknowledged
        const active = filtered.filter(a => !a.acknowledged);
        const acknowledged = filtered.filter(a => a.acknowledged);

        // Sort active by severity (critical first)
        const severityOrder = { 'CRITICAL': 0, 'SEVERE': 1, 'CAUTION': 2, 'INFO': 3 };
        active.sort((a, b) => (severityOrder[a.severity] ?? 99) - (severityOrder[b.severity] ?? 99));

        const totalCount = allAlerts.length;
        const activeCount = active.length;

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">⚠ Alerts</span>
                <span class="panel-card-badge refresh-hot">HOT</span>
            </div>
            <div class="panel-card-body">
                <div class="panel-row">
                    <span class="panel-label">Active</span>
                    <span class="panel-value ${activeCount > 0 ? (active.some(a => a.severity === 'CRITICAL') ? 'text-red' : 'text-yellow') : ''}">
                        ${activeCount} / ${totalCount}
                    </span>
                </div>

                <!-- Filters -->
                <div class="alert-filters" style="display:flex;gap:4px;margin:6px 0;flex-wrap:wrap;">
                    <select id="alert-filter-severity" class="alert-filter-select" style="background:var(--bg-elevated);color:var(--text-secondary);border:1px solid var(--border-subtle);border-radius:3px;padding:2px 6px;font-size:10px;font-family:var(--font-mono);">
                        <option value="">All Severities</option>
                        <option value="CRITICAL" ${this._filterSeverity === 'CRITICAL' ? 'selected' : ''}>CRITICAL</option>
                        <option value="SEVERE" ${this._filterSeverity === 'SEVERE' ? 'selected' : ''}>SEVERE</option>
                        <option value="CAUTION" ${this._filterSeverity === 'CAUTION' ? 'selected' : ''}>CAUTION</option>
                        <option value="INFO" ${this._filterSeverity === 'INFO' ? 'selected' : ''}>INFO</option>
                    </select>
                    <button class="alert-filter-btn ${this._showHistory ? 'active' : ''}" id="alert-toggle-history" style="background:${this._showHistory ? 'var(--bg-active)' : 'var(--bg-elevated)'};color:var(--text-secondary);border:1px solid var(--border-subtle);border-radius:3px;padding:2px 8px;font-size:10px;cursor:pointer;font-family:var(--font-mono);">
                        ${this._showHistory ? '▼ Active' : '▶ History'}
                    </button>
                    ${activeCount > 0 ? `<span class="alert-clear-btn" id="alert-clear-all" style="color:var(--text-dim);font-size:10px;cursor:pointer;padding:2px 6px;border-radius:3px;">✕ Clear All</span>` : ''}
                </div>

                <!-- Active Alerts -->
                <div id="alert-active-list" style="max-height:180px;overflow-y:auto;">
                    ${active.length === 0 ? '<div class="panel-value text-muted" style="padding:4px 0;">No active alerts</div>' : ''}
                    ${active.map(a => this._renderAlertRow(a)).join('')}
                </div>

                <!-- History -->
                ${this._showHistory && acknowledged.length > 0 ? `
                <div style="border-top:1px solid var(--border-subtle);margin-top:6px;padding-top:6px;">
                    <div class="panel-label" style="margin-bottom:4px;">Acknowledged (${acknowledged.length})</div>
                    <div id="alert-history-list" style="max-height:120px;overflow-y:auto;">
                        ${acknowledged.map(a => this._renderAlertRow(a, true)).join('')}
                    </div>
                </div>
                ` : ''}
            </div>
        </div>
        `;

        this._container.innerHTML = html;

        // Bind filter events
        const severitySelect = document.getElementById('alert-filter-severity');
        if (severitySelect) {
            severitySelect.addEventListener('change', () => {
                this._filterSeverity = severitySelect.value || null;
                this._render();
            });
        }

        const toggleBtn = document.getElementById('alert-toggle-history');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                this._showHistory = !this._showHistory;
                this._render();
            });
        }

        const clearBtn = document.getElementById('alert-clear-all');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                active.forEach(a => {
                    if (a.alert_id) {
                        api.acknowledgeAlert(a.alert_id).catch(() => {});
                    }
                });
                clearBtn.textContent = '✓ Clearing...';
                setTimeout(() => this._render(), 1000);
            });
        }

        // Bind acknowledge buttons
        this._container.querySelectorAll('.ack-alert-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const alertId = btn.dataset.id;
                if (!alertId) return;
                btn.disabled = true;
                btn.textContent = '...';
                try {
                    await api.acknowledgeAlert(alertId);
                    btn.textContent = '✓';
                    btn.style.color = 'var(--green-500)';
                    setTimeout(() => this._render(), 500);
                } catch (e) {
                    btn.textContent = '✕';
                    btn.style.color = 'var(--red-500)';
                    console.warn('[AlertPanel] Acknowledge failed:', e);
                }
            });
        });
    },

    /** @private */
    _renderAlertRow(alert, isHistory = false) {
        const severity = (alert.severity || 'INFO').toLowerCase();
        const sevIcon = {
            critical: '⛔',
            severe: '⚠',
            caution: '▲',
            info: '●'
        };
        const time = alert.timestamp ? new Date(alert.timestamp).toLocaleTimeString() : '';

        return `
        <div class="panel-row alert-row" style="${isHistory ? 'opacity:0.6;' : ''}border-bottom:1px solid var(--border-subtle);padding:4px 0;">
            <span class="status-tag ${severity}" style="min-width:55px;justify-content:center;">
                ${sevIcon[severity] || '●'} ${alert.severity || 'INFO'}
            </span>
            <span class="panel-value" style="flex:1;font-size:10px;margin:0 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${this._escapeHtml(alert.message || '')}">
                ${this._escapeHtml(alert.message || '')}
            </span>
            <span class="panel-value text-muted" style="font-size:9px;flex-shrink:0;width:50px;">${time}</span>
            ${!isHistory ? `<button class="icon-btn ack-alert-btn" data-id="${alert.alert_id || ''}" title="Acknowledge" style="flex-shrink:0;">✓</button>` : ''}
        </div>
        `;
    },

    /** @private */
    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};

// Register with ComponentManager
ComponentManager.register('alerts', AlertPanel);
