/**
 * Junior Aladdin — Operator Terminal
 * captain_panel.js — Captain AI decision-making component
 *
 * Displays the captain's current state: mood, decision, conviction
 * band, market story summary, active plans, session phase, and
 * trade status. Auto-updates via StateManager.
 *
 * Reference: ROADMAP_SIDE_B Step 8.15
 */

const CaptainPanel = {
    /** @type {HTMLElement|null} */
    _container: null,

    /**
     * Mount the captain panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._render();

        // Subscribe to captain state changes
        this._unsubscribe = StateManager.subscribe('captain', (captain) => {
            if (captain) this._render();
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
        const captain = StateManager.get('captain', {});

        const mood = captain.mood || 'OBSERVER';
        const decision = captain.decision_state || captain.decision || 'WAIT';
        const convictionBand = captain.conviction_band || 'REJECT';
        const story = captain.market_story_summary || captain.story_summary || '';
        const plans = captain.active_plan_count ?? 0;
        const sessionPhase = captain.session_phase || '';
        const realModeLocked = captain.real_mode_locked || false;
        const activeTrade = captain.active_trade || false;

        // Mood labels with emoji
        const moodLabels = {
            'OBSERVER': '👁 Observer',
            'ANALYTICAL': '🔍 Analytical',
            'CAUTIOUS': '⚡ Cautious',
            'CONFIDENT': '🟢 Confident',
            'AGGRESSIVE': '🔴 Aggressive',
            'PANIC': '⛔ Panic',
            'NEUTRAL': '⚪ Neutral',
            'BULLISH': '📈 Bullish',
            'BEARISH': '📉 Bearish',
        };
        const moodDisplay = moodLabels[mood] || mood;

        // Decision labels with emoji
        const decisionLabels = {
            'WAIT': '⏳ Wait',
            'HOLD': '✋ Hold',
            'ENTER': '📥 Enter',
            'EXIT': '📤 Exit',
            'ADD': '📈 Add',
            'REDUCE': '📉 Reduce',
            'FLATTEN': '🔄 Flatten',
            'ESCALATE': '⚠ Escalate',
            'OVERRIDE': '🛑 Override',
            'KILL': '⛔ Kill',
        };
        const decisionDisplay = decisionLabels[decision] || decision;

        // Conviction band display
        const convictionClass = convictionBand.toLowerCase();
        const convictionPct = this._convictionPercent(convictionBand);

        // Session phase display
        const sessionDisplay = sessionPhase
            ? { 'PRE_MARKET': '🌅 Pre-Market', 'OPEN': '🟢 Open', 'CONTINUOUS': '🟢 Continuous',
                'AUCTION': '🟠 Auction', 'CLOSING': '🔴 Closing', 'CLOSED': '⚫ Closed',
                'POST_CLOSE': '🌙 Post-Close' }[sessionPhase.toUpperCase()] || sessionPhase
            : '';

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">◈ Captain</span>
                <span class="panel-card-badge refresh-warm">WARM</span>
            </div>
            <div class="panel-card-body">
                <!-- Mood + Decision badges -->
                <div style="display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap;">
                    <span class="status-tag" style="font-size:11px;padding:3px 8px;">${moodDisplay}</span>
                    <span class="status-tag" style="font-size:11px;padding:3px 8px;">${decisionDisplay}</span>
                    ${activeTrade ? '<span class="status-tag" style="font-size:11px;padding:3px 8px;background:var(--green-500);color:#fff;">💰 In Trade</span>' : ''}
                </div>

                <!-- Conviction Bar -->
                <div style="margin-bottom:8px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                        <span style="font-size:10px;color:var(--text-dim);text-transform:uppercase;">Conviction</span>
                        <span class="status-tag ${convictionClass}" style="font-size:9px;">${convictionBand}</span>
                    </div>
                    <div class="conviction-bar" style="height:8px;background:var(--bg-elevated);border-radius:4px;overflow:hidden;">
                        <div class="conviction-fill ${convictionClass}" style="width:${convictionPct}%;height:100%;border-radius:4px;transition:width 0.3s ease;"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:2px;">
                        <span style="font-size:8px;color:var(--text-dim);">REJECT</span>
                        <span style="font-size:8px;color:var(--text-dim);">LOW</span>
                        <span style="font-size:8px;color:var(--text-dim);">MED</span>
                        <span style="font-size:8px;color:var(--text-dim);">HIGH</span>
                        <span style="font-size:8px;color:var(--text-dim);">MAX</span>
                    </div>
                </div>

                <!-- Key State Grid -->
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;margin-bottom:6px;">
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Real Mode</span>
                        <span class="panel-value" style="font-size:11px;">${realModeLocked ? '🔒 Locked' : '🔓 Unlocked'}</span>
                    </div>
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Active Trade</span>
                        <span class="panel-value" style="font-size:11px;">${activeTrade ? '🟢 Yes' : '⚪ No'}</span>
                    </div>
                    ${sessionDisplay ? `
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Session</span>
                        <span class="panel-value" style="font-size:11px;">${sessionDisplay}</span>
                    </div>
                    ` : ''}
                    <div class="panel-row" style="padding:2px 0;">
                        <span class="panel-label" style="font-size:10px;">Plans</span>
                        <span class="panel-value mono" style="font-size:11px;">${plans}</span>
                    </div>
                </div>

                <!-- Story Summary -->
                ${story ? `
                <div style="border-top:1px solid var(--border-subtle);padding-top:6px;margin-top:4px;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px;">Market Story</div>
                    <div style="font-size:11px;color:var(--text-secondary);line-height:1.5;font-family:var(--font-mono);">
                        ${this._escapeHtml(story.length > 120 ? story.slice(0, 120) + '...' : story)}
                    </div>
                </div>
                ` : ''}
            </div>
        </div>
        `;

        this._container.innerHTML = html;
    },

    /**
     * Convert conviction band to percentage for bar display.
     * @private
     * @param {string} band
     * @returns {number}
     */
    _convictionPercent(band) {
        const map = {
            'REJECT': 5,
            'LOW': 25,
            'MEDIUM': 50,
            'HIGH': 75,
            'MAX': 95,
        };
        return map[band.toUpperCase()] || 10;
    },

    /** @private */
    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};

// Register with ComponentManager
ComponentManager.register('captain', CaptainPanel);
