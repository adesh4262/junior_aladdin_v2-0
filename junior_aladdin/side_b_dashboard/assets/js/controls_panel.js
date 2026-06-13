/**
 * Junior Aladdin — Operator Terminal
 * controls_panel.js — Operator controls component
 *
 * Interactive panel for operator commands: mode switch, kill switch,
 * capital limit, broker reconnect, override confirmation, and
 * account reset. Subscribes to execution state for current values
 * and calls API endpoints on user action.
 *
 * Reference: ROADMAP_SIDE_B Step 8.17
 */

const ControlsPanel = {
    /** @type {HTMLElement|null} */
    _container: null,
    /** @type {string} */
    _capitalValue: '',
    /** @type {boolean} */
    _capitalSetOnce: false,


    /**
     * Mount the controls panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._render();

        // Subscribe to execution state changes (for mode, kill switch)
        this._unsubscribe = StateManager.subscribe('execution', (execution) => {
            if (execution) {
                // Save capital input value before re-render so it isn't destroyed
                this._saveCapitalInput();
                this._render();
            }
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
        if (state && this._container) {
            this._saveCapitalInput();
            this._render();
        }
    },

    /** @private */
    _render() {
        if (!this._container) return;
        const exec = StateManager.get('execution', {});

        const currentMode = exec.mode || 'ALERT';
        const capitalFromState = exec.capital_limit;
        // Use backend value if available and user hasn't typed a newer value
        if (capitalFromState != null && !this._capitalSetOnce) {
            this._capitalValue = String(capitalFromState);
        }
        const killSwitch = (exec.kill_switch_state || exec.kill_switch || 'OFF').toUpperCase();
        const isLocked = exec.is_locked || false;
        const connected = StateManager.get('connected', false);

        // Mode buttons — backend supports: ALERT, PAPER, REAL
        const modes = ['ALERT', 'PAPER', 'REAL'];
        const modeIcons = { 'ALERT': '🔍', 'PAPER': '📋', 'REAL': '🔴' };
        const modeButtons = modes.map(m => `
            <button class="control-btn ${m === currentMode ? 'active' : ''}"
                    data-action="set-mode" data-mode="${m}"
                    ${isLocked && m === 'REAL' ? 'disabled' : ''}>
                ${modeIcons[m]} ${m}
            </button>
        `).join('');

        // Kill switch buttons
        const ksStates = [
            { state: 'OFF', label: '▶ Resume', cls: '' },
            { state: 'SOFT', label: '🛑 Soft Kill', cls: 'danger' },
            { state: 'CRITICAL', label: '⛔ Critical Kill', cls: 'danger' },
        ];
        const ksButtons = ksStates.map(ks => `
            <button class="control-btn ${ks.cls} ${killSwitch === ks.state ? 'active' : ''}"
                    data-action="kill-switch" data-ks="${ks.state}">
                ${ks.label}
            </button>
        `).join('');

        // Current status display
        const modeClass = currentMode === 'ALERT' ? '' : currentMode === 'PAPER' ? 'paper' : 'live';
        const ksClass = killSwitch === 'CRITICAL' ? 'text-red' : killSwitch === 'SOFT' ? 'text-yellow' : 'text-green';
        const lockedLabel = isLocked ? '🔒 Locked' : '🔓 Unlocked';

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">⚙ Controls</span>
                <span class="panel-card-badge status-tag ${modeClass}" style="font-size:9px;padding:2px 6px;text-transform:none;">${currentMode}</span>
            </div>
            <div class="panel-card-body">

                <!-- Status strip -->
                <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
                    <span class="panel-value" style="font-size:11px;">Mode: <strong class="${modeClass}">${currentMode}</strong></span>
                    <span class="panel-value ${ksClass}" style="font-size:11px;">Kill: <strong>${killSwitch}</strong></span>
                    <span class="panel-value" style="font-size:11px;">${lockedLabel}</span>
                    <span class="panel-value" style="font-size:11px;">🔌 ${connected ? 'Connected' : 'Disconnected'}</span>
                </div>

                <!-- Mode Switch -->
                <div style="margin-bottom:10px;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                        🎯 Mode Switch
                    </div>
                    <div class="controls-row">
                        ${modeButtons}
                    </div>
                </div>

                <!-- Kill Switch -->
                <div style="margin-bottom:10px;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                        ⛔ Kill Switch
                    </div>
                    <div class="controls-row">
                        ${ksButtons}
                    </div>
                </div>

                <!-- Capital Limit -->
                <div style="margin-bottom:10px;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                        💰 Capital Limit
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;">
                        <input type="number" id="controls-capital-input"
                               class="control-input"
                               placeholder="Enter limit..."
                               value="${this._capitalValue}"
                               min="0" step="10000"
                               style="flex:1;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:4px;padding:6px 8px;color:var(--text-primary);font-family:var(--font-mono);font-size:12px;outline:none;" />
                        <button class="control-btn" data-action="set-capital">Set</button>
                    </div>
                </div>

                <!-- Broker Reconnect -->
                <div style="margin-bottom:10px;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                        🔄 Broker Reconnect
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;">
                        <select id="controls-broker-select"
                                style="flex:1;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:4px;padding:6px 8px;color:var(--text-primary);font-family:var(--font-mono);font-size:11px;outline:none;">
                            <option value="primary">Primary Broker</option>
                            <option value="secondary">Secondary Broker</option>
                            <option value="backup">Backup Broker</option>
                        </select>
                        <button class="control-btn" data-action="reconnect">Reconnect</button>
                    </div>
                </div>

                <!-- Advanced Controls -->
                <div style="border-top:1px solid var(--border-subtle);padding-top:8px;margin-top:4px;">
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                        <button class="control-btn" data-action="override-confirm" style="font-size:11px;">
                            🛑 Confirm Override
                        </button>
                        <button class="control-btn danger" data-action="reset-account" style="font-size:11px;">
                            ⚠ Reset Account
                        </button>
                    </div>
                </div>

            </div>
        </div>
        `;

        this._container.innerHTML = html;

        // Restore capital input value after DOM rebuild
        this._restoreCapitalInput();

        // ── Bind event handlers ──
        this._bindEvents();
    },

    /** @private */
    _bindEvents() {
        if (!this._container) return;

        // Mode switch buttons
        this._container.querySelectorAll('[data-action="set-mode"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.mode;
                api.setMode(mode, `Operator requested ${mode} mode`)
                    .then(ack => {
                        console.log('[Controls] Mode change ACK:', ack);
                        // Update local state immediately so UI reflects change without waiting for next poll
                        const exec = StateManager.get('execution', {});
                        StateManager.set('execution', { ...exec, mode });
                        this._showFeedback(btn, '✓', 'var(--green-500)');
                    })
                    .catch(err => {
                        console.warn('[Controls] Mode change failed:', err);
                        this._showFeedback(btn, '✕', 'var(--red-500)');
                    });
            });
        });

        // Kill switch buttons
        this._container.querySelectorAll('[data-action="kill-switch"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const ks = btn.dataset.ks;
                const confirmMsg = ks === 'SOFT'
                    ? 'Activate SOFT kill switch? New orders will be blocked.'
                    : ks === 'CRITICAL'
                        ? '⚠ CRITICAL: This will flatten ALL positions! Continue?'
                        : null;

                const proceed = confirmMsg ? confirm(confirmMsg) : true;
                if (!proceed) return;

                api.setKillSwitch(ks, `Operator ${ks === 'OFF' ? 'deactivated' : 'activated'} kill switch (${ks})`)
                    .then(ack => {
                        console.log('[Controls] Kill switch ACK:', ack);
                        // Update local state immediately
                        const exec = StateManager.get('execution', {});
                        StateManager.set('execution', { ...exec, kill_switch_state: ks });
                        this._showFeedback(btn, '✓', 'var(--green-500)');
                    })
                    .catch(err => {
                        console.warn('[Controls] Kill switch failed:', err);
                        this._showFeedback(btn, '✕', 'var(--red-500)');
                    });
            });
        });

        // Capital limit
        const capitalBtn = this._container.querySelector('[data-action="set-capital"]');
        const capitalInput = this._container.querySelector('#controls-capital-input');
        if (capitalBtn && capitalInput) {
            const handleCapital = () => {
                const limit = parseFloat(capitalInput.value);
                if (isNaN(limit) || limit < 0) {
                    this._showFeedback(capitalBtn, 'Invalid', 'var(--red-500)');
                    return;
                }
                api.setCapital(limit, `Operator set capital limit to ${limit}`)
                    .then(ack => {
                        console.log('[Controls] Capital ACK:', ack);
                        this._capitalValue = capitalInput.value;
                        this._capitalSetOnce = true;
                        // Update local state immediately so UI reflects change everywhere
                        const exec = StateManager.get('execution', {});
                        StateManager.set('execution', { ...exec, capital_limit: limit });
                        this._showFeedback(capitalBtn, '✓', 'var(--green-500)');
                    })
                    .catch(err => {
                        console.warn('[Controls] Capital set failed:', err);
                        this._showFeedback(capitalBtn, '✕', 'var(--red-500)');
                    });
            };
            capitalBtn.addEventListener('click', handleCapital);
            capitalInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') handleCapital();
            });
            // Track input changes so user's typed value survives re-renders
            capitalInput.addEventListener('input', () => {
                this._capitalValue = capitalInput.value;
            });
        }

        // Reconnect
        const reconnectBtn = this._container.querySelector('[data-action="reconnect"]');
        const brokerSelect = this._container.querySelector('#controls-broker-select');
        if (reconnectBtn && brokerSelect) {
            reconnectBtn.addEventListener('click', () => {
                const broker = brokerSelect.value;
                api.requestReconnect(broker, `Operator requested reconnect to ${broker}`)
                    .then(ack => {
                        console.log('[Controls] Reconnect ACK:', ack);
                        this._showFeedback(reconnectBtn, '✓', 'var(--green-500)');
                    })
                    .catch(err => {
                        console.warn('[Controls] Reconnect failed:', err);
                        this._showFeedback(reconnectBtn, '✕', 'var(--red-500)');
                    });
            });
        }

        // Override confirm
        const overrideBtn = this._container.querySelector('[data-action="override-confirm"]');
        if (overrideBtn) {
            overrideBtn.addEventListener('click', () => {
                const reason = prompt('Override reason:');
                if (!reason) return;
                api.confirmOverride(reason)
                    .then(ack => {
                        console.log('[Controls] Override ACK:', ack);
                        this._showFeedback(overrideBtn, '✓', 'var(--green-500)');
                    })
                    .catch(err => {
                        console.warn('[Controls] Override failed:', err);
                        this._showFeedback(overrideBtn, '✕', 'var(--red-500)');
                    });
            });
        }

        // Reset account
        const resetBtn = this._container.querySelector('[data-action="reset-account"]');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                if (!confirm('⚠ Reset paper trading account to default balance? This cannot be undone!')) return;
                const balance = prompt('New balance (default: 100000):', '100000');
                const balNum = parseFloat(balance || '100000');
                if (isNaN(balNum) || balNum <= 0) {
                    this._showFeedback(resetBtn, 'Invalid', 'var(--red-500)');
                    return;
                }
                api.resetAccount(balNum, `Operator reset account to ${balNum}`)
                    .then(ack => {
                        console.log('[Controls] Reset ACK:', ack);
                        this._showFeedback(resetBtn, '✓', 'var(--green-500)');
                    })
                    .catch(err => {
                        console.warn('[Controls] Reset failed:', err);
                        this._showFeedback(resetBtn, '✕', 'var(--red-500)');
                    });
            });
        }
    },

    /**
     * Save the current capital input value before a re-render clears it.
     * @private
     */
    _saveCapitalInput() {
        if (!this._container) return;
        const input = this._container.querySelector('#controls-capital-input');
        if (input) this._capitalValue = input.value;
    },

    /**
     * Restore the capital input value after a re-render.
     * @private
     */
    _restoreCapitalInput() {
        if (!this._container) return;
        const input = this._container.querySelector('#controls-capital-input');
        if (input) {
            input.value = this._capitalValue;
        }
    },

    /**
     * Show temporary feedback on a button.
     * @private
     * @param {HTMLElement} btn
     * @param {string} text
     * @param {string} color
     */
    _showFeedback(btn, text, color) {
        const original = btn.textContent;
        btn.textContent = text;
        btn.style.color = color;
        setTimeout(() => {
            btn.textContent = original;
            btn.style.color = '';
        }, 1500);
    }
};

// Register with ComponentManager
ComponentManager.register('controls', ControlsPanel);
