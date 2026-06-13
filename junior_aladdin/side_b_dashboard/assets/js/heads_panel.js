/**
 * Junior Aladdin — Operator Terminal
 * heads_panel.js — Floor summary + head reports component
 *
 * Displays the aggregated FloorSummary (floor bias, confidence, setup
 * counts) and per-department head reports (state, bias, confidence,
 * freshness, setup info). Auto-updates via StateManager.
 *
 * Reference: ROADMAP_SIDE_B Step 8.16
 */

const HeadsPanel = {
    /** @type {HTMLElement|null} */
    _container: null,

    /**
     * Mount the heads panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._render();

        // Subscribe to heads state changes
        this._unsubscribe = StateManager.subscribe('heads', (heads) => {
            if (heads) this._render();
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
        const data = StateManager.get('heads', {});
        const fs = data.floor_summary || {};
        const heads = data.heads || [];

        // ── Floor Summary ──
        const floorBias = fs.floor_bias || 'NEUTRAL';
        const floorConfidence = fs.floor_confidence ?? 0;
        const activeSetups = fs.active_setup_count ?? 0;
        const readyHeads = fs.ready_heads ?? 0;
        const uncertainHeads = fs.uncertain_heads ?? 0;
        const staleHeads = fs.stale_heads ?? 0;
        const dataHealth = fs.data_health_signal || 'GOOD';

        // Bias labels
        const biasLabels = {
            'NEUTRAL': '⚪ Neutral',
            'BULLISH': '📈 Bullish',
            'BEARISH': '📉 Bearish',
            'MIXED': '🔀 Mixed',
        };
        const biasDisplay = biasLabels[floorBias] || floorBias;

        // Data health dot
        const healthLower = dataHealth.toLowerCase();
        const healthDotClass = healthLower === 'good' ? 'health-good'
            : healthLower === 'degraded' ? 'health-degraded'
            : healthLower === 'critical' ? 'health-critical'
            : healthLower === 'stale' ? 'health-stale'
            : 'health-unknown';

        // Confidence percentage
        const confPct = Math.round(floorConfidence * 100);

        // Count display helpers
        const readyClass = readyHeads > 0 ? 'text-green' : 'text-muted';
        const uncertainClass = uncertainHeads > 0 ? 'text-yellow' : 'text-muted';
        const staleClass = staleHeads > 0 ? 'text-red' : 'text-muted';

        // ── Per-Head Reports ──
        let headsHtml = '';
        if (heads.length > 0) {
            headsHtml = `
                <div style="border-top:1px solid var(--border-subtle);padding-top:8px;margin-top:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <span style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">
                            ◆ Head Reports
                        </span>
                        <span class="panel-value" style="font-size:10px;">${heads.length} active</span>
                    </div>
                    <div style="display:flex;flex-direction:column;gap:4px;">
                        ${heads.map(h => this._renderHeadCard(h)).join('')}
                    </div>
                </div>
            `;
        } else {
            headsHtml = '<div class="panel-value text-muted" style="padding:4px 0;font-size:11px;">No head reports available</div>';
        }

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">◆ Heads</span>
                <span class="panel-card-badge refresh-warm">WARM</span>
            </div>
            <div class="panel-card-body">
                <!-- Floor Summary Strip -->
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:6px;">
                    <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Bias</div>
                        <div style="font-size:12px;font-weight:600;margin-top:1px;">${biasDisplay}</div>
                    </div>
                    <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Confidence</div>
                        <div style="font-size:12px;font-weight:600;font-family:var(--font-mono);margin-top:1px;">${confPct}%</div>
                    </div>
                    <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Setups</div>
                        <div style="font-size:12px;font-weight:600;font-family:var(--font-mono);margin-top:1px;">${activeSetups}</div>
                    </div>
                </div>

                <!-- Confidence Bar -->
                <div style="margin-bottom:6px;">
                    <div class="conviction-bar" style="height:6px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;">
                        <div style="width:${confPct}%;height:100%;border-radius:3px;background:${this._confidenceColor(floorConfidence)};transition:width 0.3s ease;"></div>
                    </div>
                </div>

                <!-- Head Counts Row -->
                <div style="display:flex;gap:10px;margin-bottom:6px;">
                    <div style="display:flex;align-items:center;gap:4px;">
                        <span class="health-dot health-good" style="width:6px;height:6px;"></span>
                        <span class="${readyClass}" style="font-size:11px;font-family:var(--font-mono);">${readyHeads} Ready</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:4px;">
                        <span class="health-dot health-degraded" style="width:6px;height:6px;"></span>
                        <span class="${uncertainClass}" style="font-size:11px;font-family:var(--font-mono);">${uncertainHeads} Uncertain</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:4px;">
                        <span class="health-dot health-critical" style="width:6px;height:6px;"></span>
                        <span class="${staleClass}" style="font-size:11px;font-family:var(--font-mono);">${staleHeads} Stale</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:4px;margin-left:auto;">
                        <span class="health-dot ${healthDotClass}" style="width:6px;height:6px;"></span>
                        <span style="font-size:10px;color:var(--text-dim);">${dataHealth}</span>
                    </div>
                </div>

                <!-- Per-Head Reports -->
                ${headsHtml}
            </div>
        </div>
        `;

        this._container.innerHTML = html;
    },

    /**
     * Render a single head report card.
     * @private
     * @param {object} head
     * @returns {string}
     */
    _renderHeadCard(head) {
        const name = head.head_name || 'Unknown Head';
        const state = head.state || 'READY';
        const bias = head.bias || 'NEUTRAL';
        const confidence = head.confidence ?? 0;
        const freshness = head.freshness_tag || 'FRESH';
        const cqs = head.context_quality_score;
        const primarySetup = head.primary_setup;
        const backupSetup = head.backup_setup;
        const noSetup = head.no_setup_flag || false;

        // State badge
        const stateClass = state.toLowerCase();
        const stateDisplay = state === 'READY' ? '🟢 Ready'
            : state === 'UNCERTAIN' ? '🟡 Uncertain'
            : state === 'STALE' ? '🔴 Stale'
            : state === 'ERROR' ? '⛔ Error'
            : state;

        // Bias badge
        const biasDisplay = bias === 'NEUTRAL' ? '⚪'
            : bias === 'BULLISH' ? '📈'
            : bias === 'BEARISH' ? '📉'
            : bias;

        // Freshness tag
        const freshnessClass = freshness === 'FRESH' ? 'text-green'
            : freshness === 'STALE' ? 'text-red'
            : freshness === 'RECENT' ? 'text-yellow'
            : 'text-muted';

        // Confidence % and color
        const confPct = Math.round(confidence * 100);
        const confColor = this._confidenceColor(confidence);

        // Setup info
        let setupHtml = '';
        if (noSetup) {
            setupHtml = '<span class="panel-value text-muted" style="font-size:9px;">No setup (flag)</span>';
        } else if (primarySetup) {
            setupHtml = `<span class="panel-value mono" style="font-size:9px;color:var(--text-secondary);">${this._escapeHtml(primarySetup)}</span>`;
            if (backupSetup) {
                setupHtml += ` <span class="panel-value text-muted" style="font-size:9px;">+ backup</span>`;
            }
        } else {
            setupHtml = '<span class="panel-value text-muted" style="font-size:9px;">No setup</span>';
        }

        // Context quality score
        let cqsHtml = '';
        if (cqs !== null && cqs !== undefined) {
            cqsHtml = `
                <span class="panel-value mono" style="font-size:9px;color:var(--text-dim);" title="Context Quality">
                    CQ:${cqs.toFixed(2)}
                </span>
            `;
        }

        return `
            <div style="background:var(--bg-elevated);border-radius:4px;padding:5px 8px;border-left:3px solid ${confColor};">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <span style="font-size:11px;font-weight:600;color:var(--text-primary);">${this._escapeHtml(name)}</span>
                        <span class="status-tag ${stateClass}" style="font-size:8px;padding:1px 4px;">${stateDisplay}</span>
                        <span style="font-size:10px;">${biasDisplay}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:6px;">
                        ${cqsHtml}
                        <span class="${freshnessClass}" style="font-size:9px;font-family:var(--font-mono);">${freshness}</span>
                    </div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <!-- Confidence mini-bar -->
                    <div style="flex:1;max-width:80px;">
                        <div class="conviction-bar" style="height:4px;background:var(--bg-surface);border-radius:2px;overflow:hidden;">
                            <div style="width:${confPct}%;height:100%;border-radius:2px;background:${confColor};"></div>
                        </div>
                    </div>
                    <span class="panel-value mono" style="font-size:9px;color:var(--text-secondary);min-width:28px;">${confPct}%</span>
                    ${setupHtml}
                </div>
            </div>
        `;
    },

    /**
     * Map a confidence value (0-1) to a hex color.
     * @private
     * @param {number} confidence
     * @returns {string}
     */
    _confidenceColor(confidence) {
        if (confidence >= 0.8) return 'var(--green-500)';
        if (confidence >= 0.6) return 'var(--green-400)';
        if (confidence >= 0.4) return 'var(--yellow-500)';
        if (confidence >= 0.2) return 'var(--orange-500)';
        return 'var(--red-500)';
    },

    /** @private */
    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};

// Register with ComponentManager
ComponentManager.register('heads', HeadsPanel);
