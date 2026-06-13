/**
 * Junior Aladdin — Operator Terminal
 * execution_panel.js — Execution state component
 *
 * Displays real-time execution state: state, mode, escalation,
 * position (direction/qty/price/PnL), orders, and kill switch.
 * Auto-updates via StateManager.
 *
 * Reference: ROADMAP_SIDE_B Step 8.14
 */

const ExecutionPanel = {
    /** @type {HTMLElement|null} */
    _container: null,

    /**
     * Mount the execution panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._render();

        // Subscribe to execution state changes
        this._unsubscribe = StateManager.subscribe('execution', (execution) => {
            if (execution) this._render();
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
        const exec = StateManager.get('execution', {});

        const state = exec.state || exec.mode || 'IDLE';
        const mode = exec.mode || 'ALERT';
        const escalation = exec.escalation_level || 'NORMAL';
        const isLocked = exec.is_locked || false;
        const unknownReconcile = exec.unknown_reconcile || false;
        const killSwitch = (exec.kill_switch || 'OFF').toUpperCase();
        const position = exec.position || null;
        const orders = exec.orders || [];

        // State badge styling
        const stateLabels = {
            'INITIALIZING': '🔄 Initializing',
            'IDLE': '⚪ Idle',
            'WATCHING': '👁 Watching',
            'ANALYZING': '🔍 Analyzing',
            'READY': '🟢 Ready',
            'ACTIVE': '🟢 Active',
            'PAPER_TRADING': '📋 Paper Trading',
            'BLOCKED': '🔴 Blocked',
            'KILLED': '⛔ Killed',
            'ERROR': '⚠ Error',
            'RECOVERING': '🔄 Recovering',
        };
        const stateDisplay = stateLabels[state] || state;

        // Mode badge styling
        const modeDisplay = mode === 'ALERT' ? '🔍 Alert'
            : mode === 'PAPER' ? '📋 Paper'
            : mode === 'LIVE' ? '🔴 Live'
            : mode === 'SIMULATE' ? '🧪 Simulate'
            : mode;

        // Escalation styling
        const escalationClass = escalation === 'CRITICAL' ? 'text-red'
            : escalation === 'ELEVATED' ? 'text-yellow'
            : '';

        // Kill switch styling
        const killClass = killSwitch === 'CRITICAL' ? 'text-red'
            : killSwitch === 'SOFT' ? 'text-yellow'
            : killSwitch === 'OFF' ? 'text-green'
            : '';

        // Position display
        let positionHtml = '';
        if (position) {
            const pnl = position.pnl ?? null;
            const pnlClass = pnl !== null ? (pnl >= 0 ? 'text-green' : 'text-red') : '';
            positionHtml = `
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;margin-bottom:6px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                        <span style="font-size:10px;color:var(--text-dim);text-transform:uppercase;">Position</span>
                        <span class="status-tag ${(position.direction || '').toLowerCase()}" style="font-size:9px;">
                            ${position.direction || '--'}
                        </span>
                    </div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 12px;">
                        <div class="panel-row" style="padding:1px 0;">
                            <span class="panel-label" style="font-size:10px;">Filled</span>
                            <span class="panel-value mono" style="font-size:11px;">${position.filled_qty ?? 0}</span>
                        </div>
                        <div class="panel-row" style="padding:1px 0;">
                            <span class="panel-label" style="font-size:10px;">Avg Price</span>
                            <span class="panel-value mono" style="font-size:11px;">${position.avg_price ? position.avg_price.toFixed(2) : '--'}</span>
                        </div>
                        <div class="panel-row" style="padding:1px 0;">
                            <span class="panel-label" style="font-size:10px;">Entry</span>
                            <span class="panel-value mono" style="font-size:11px;">${position.entry_price ? position.entry_price.toFixed(2) : '--'}</span>
                        </div>
                        <div class="panel-row" style="padding:1px 0;">
                            <span class="panel-label" style="font-size:10px;">PnL</span>
                            <span class="panel-value mono ${pnlClass}" style="font-size:11px;">${pnl !== null ? (pnl >= 0 ? '+' : '') + pnl.toFixed(2) : '--'}</span>
                        </div>
                    </div>
                </div>
            `;
        } else {
            positionHtml = '<div class="panel-value text-muted" style="padding:4px 0;font-size:11px;">No active position</div>';
        }

        // Orders display
        let ordersHtml = '';
        if (orders.length > 0) {
            const displayOrders = orders.slice(0, 4); // Max 4 rows
            ordersHtml = `
                <div style="border-top:1px solid var(--border-subtle);padding-top:6px;margin-top:4px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                        <span style="font-size:10px;color:var(--text-dim);text-transform:uppercase;">Recent Orders</span>
                        <span class="panel-value" style="font-size:10px;">${orders.length} total</span>
                    </div>
                    ${displayOrders.map(o => {
                        const sideClass = (o.side || '').toLowerCase();
                        const statusClass = (o.status || '').toLowerCase();
                        return `
                        <div class="panel-row" style="padding:2px 0;border-bottom:1px solid var(--border-subtle);">
                            <span class="status-tag ${sideClass}" style="font-size:8px;padding:1px 4px;min-width:30px;">${o.side || '--'}</span>
                            <span class="panel-value mono" style="font-size:10px;flex:1;">${o.qty || 0} @ ${o.price ? o.price.toFixed(2) : '--'}</span>
                            <span class="status-tag ${statusClass}" style="font-size:8px;padding:1px 4px;">${o.status || '--'}</span>
                        </div>
                        `;
                    }).join('')}
                    ${orders.length > 4 ? `<div class="panel-value text-muted" style="font-size:9px;padding:2px 0;text-align:center;">+${orders.length - 4} more</div>` : ''}
                </div>
            `;
        } else {
            ordersHtml = '<div class="panel-value text-muted" style="padding:2px 0;font-size:10px;">No orders</div>';
        }

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">⚡ Execution</span>
                <span class="panel-card-badge refresh-hot">HOT</span>
            </div>
            <div class="panel-card-body">
                <!-- Status Badge -->
                <div style="display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap;">
                    <span class="status-tag" style="font-size:11px;padding:3px 8px;">${stateDisplay}</span>
                    <span class="status-tag" style="font-size:11px;padding:3px 8px;">${modeDisplay}</span>
                </div>

                <!-- Key State -->
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;margin-bottom:6px;">
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Escalation</span>
                        <span class="panel-value ${escalationClass}" style="font-size:11px;">${escalation}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Kill Switch</span>
                        <span class="panel-value ${killClass}" style="font-size:11px;">${killSwitch}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Locked</span>
                        <span class="panel-value" style="font-size:11px;">${isLocked ? '🔒 Yes' : '🔓 No'}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Unknown Recon.</span>
                        <span class="panel-value" style="font-size:11px;">${unknownReconcile ? '⚠ Yes' : 'No'}</span>
                    </div>
                </div>

                <!-- Position -->
                ${positionHtml}

                <!-- Orders -->
                ${ordersHtml}
            </div>
        </div>
        `;

        this._container.innerHTML = html;
    }
};

// Register with ComponentManager
ComponentManager.register('execution', ExecutionPanel);
