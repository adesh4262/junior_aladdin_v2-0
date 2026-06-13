/**
 * Junior Aladdin — Operator Terminal
 * explainability_panel.js — Trade/no-trade explainability component
 *
 * WHY the system did what it did:
 *   - If TRADE: confluence summary, head alignment, conviction breakdown
 *   - If WAIT/BLOCKED: no-trade classification (SETUP_ABSENT / CONFLICT /
 *     HEALTH / ACTIVE_TRADE / GOVERNANCE / MANUAL), structured silence reason
 *   - Head alignment visualization: which heads supported, which opposed
 *   - Market story context for decision
 *
 * Data sources:
 *   - Captain state (mood, decision, conviction, market_story, silence_reason)
 *   - Floor summary (floor_bias, floor_confidence, active_setup_count)
 *   - Head reports (per-head: bias, confidence, setups)
 *
 * Reference: ROADMAP_SIDE_B Step 8.15
 *           SIDE_B_DASHBOARD_V1_2_FINAL Sections 5, 10, 12, 36
 */

const ExplainabilityPanel = {
    /** @type {HTMLElement|null} */
    _container: null,

    /** @type {Function|null} */
    _captainUnsub: null,

    /** @type {Function|null} */
    _headsUnsub: null,

    /**
     * Mount the explainability panel into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        this._container = container;
        this._render();

        // Subscribe to captain state + heads data (WARM refresh tier)
        this._captainUnsub = StateManager.subscribe('captain', () => {
            if (this._container) this._render();
        });
        this._headsUnsub = StateManager.subscribe('heads', () => {
            if (this._container) this._render();
        });
    },

    /** Unmount and clean up */
    unmount() {
        if (this._captainUnsub) this._captainUnsub();
        if (this._headsUnsub) this._headsUnsub();
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
        const heads = StateManager.get('heads', {});
        const floorSummary = heads.floor_summary || {};

        // ── Captain Decision Context ──
        const mood = captain.mood || 'OBSERVER';
        const decision = captain.decision_state || captain.decision || 'WAIT';
        const convictionBand = captain.conviction_band || 'REJECT';
        const story = captain.market_story_summary || captain.story_summary || '';
        const silenceReason = captain.silence_reason || '';
        const activeTrade = captain.active_trade || false;
        const activePlanCount = captain.active_plan_count ?? 0;
        const sessionPhase = captain.session_phase || '';

        // ── Floor Summary Context ──
        const floorBias = floorSummary.floor_bias || 'NEUTRAL';
        const floorConfidence = floorSummary.floor_confidence ?? 0;
        const activeSetupCount = floorSummary.active_setup_count ?? 0;
        const readyHeads = floorSummary.ready_heads ?? 0;
        const uncertainHeads = floorSummary.uncertain_heads ?? 0;
        const staleHeads = floorSummary.stale_heads ?? 0;
        const headReports = heads.heads || [];

        // ── Classify No-Trade Reason ──
        const noTradeClassification = this._classifyNoTrade(decision, captain, floorSummary, headReports);
        const isTrade = activeTrade || decision === 'ENTER' || decision === 'EXIT' || decision === 'ADD' || decision === 'REDUCE';
        const isNoTrade = !isTrade && (decision === 'WAIT' || decision === 'HOLD' || decision === 'FLATTEN');
        const isBlocked = decision === 'BLOCKED' || decision === 'KILL' || decision === 'ESCALATE';

        // ── Head Alignment Analysis ──
        const headAlignment = this._analyzeHeadAlignment(headReports, floorBias);

        // ── Mood descriptor ──
        const moodDescriptions = {
            'OBSERVER': '👁 Passive — watching, no active bias',
            'ANALYTICAL': '🔍 Analyzing — processing data, not yet decided',
            'CAUTIOUS': '⚡ Cautious — risk-aware, conservative stance',
            'CONFIDENT': '🟢 Confident — strong conviction in direction',
            'AGGRESSIVE': '🔴 Aggressive — high conviction, ready to act',
            'PANIC': '⛔ Panic — emergency mode, protecting capital',
            'NEUTRAL': '⚪ Neutral — balanced, no directional bias',
            'BULLISH': '📈 Bullish — positive outlook',
            'BEARISH': '📉 Bearish — negative outlook',
        };
        const moodDisplay = moodDescriptions[mood] || `◈ ${mood}`;

        // ── Conviction color ──
        const convictionClass = convictionBand.toLowerCase();

        // ── Confidence percentage ──
        const confPct = Math.round(floorConfidence * 100);
        const confColor = confPct >= 60 ? 'var(--green-500)' : confPct >= 40 ? 'var(--yellow-500)' : 'var(--red-500)';

        // ── Build HTML ──

        let html = `
        <div class="panel-card">
            <div class="panel-card-header">
                <span class="panel-card-title">💡 Explainability</span>
                <span class="panel-card-badge refresh-warm">WARM</span>
            </div>
            <div class="panel-card-body">
        `;

        // ── Decision Banner ──
        html += this._renderDecisionBanner(decision, isTrade, isNoTrade, isBlocked, noTradeClassification, convictionBand);

        // ── Captain Context Strip ──
        html += `
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;padding:8px 10px;background:var(--bg-elevated);border-radius:6px;">
                <span style="font-size:10px;color:var(--text-dim);">${moodDisplay}</span>
                <span class="bottom-separator">|</span>
                <span style="font-size:10px;color:var(--text-dim);">Session: ${sessionPhase || '--'}</span>
                <span class="bottom-separator">|</span>
                <span style="font-size:10px;color:var(--text-dim);">Plans: ${activePlanCount}</span>
            </div>
        `;

        // ── Market Story ──
        if (story) {
            html += `
            <div style="margin-bottom:10px;">
                <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">📖 Market Story</div>
                <div style="font-size:11px;color:var(--text-secondary);line-height:1.6;font-family:var(--font-mono);padding:8px 10px;background:var(--bg-elevated);border-radius:4px;border-left:2px solid var(--blue-500);">
                    ${this._escapeHtml(story)}
                </div>
            </div>
            `;
        }

        // ── Silence Reason (for no-trade) ──
        if (silenceReason && isNoTrade) {
            html += `
            <div style="margin-bottom:10px;">
                <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">🔇 Silence Reason</div>
                <div style="font-size:11px;color:var(--text-secondary);line-height:1.6;padding:8px 10px;background:var(--bg-elevated);border-radius:4px;border-left:2px solid var(--yellow-500);">
                    ${this._escapeHtml(silenceReason)}
                </div>
            </div>
            `;
        }

        // ── Floor Context Stats ──
        html += `
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px;">
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Bias</div>
                    <div style="font-size:13px;font-weight:600;margin-top:2px;">${this._biasIcon(floorBias)} ${floorBias}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Confidence</div>
                    <div style="font-size:13px;font-weight:600;font-family:var(--font-mono);margin-top:2px;color:${confColor};">${confPct}%</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Setups</div>
                    <div style="font-size:13px;font-weight:600;font-family:var(--font-mono);margin-top:2px;color:${activeSetupCount > 0 ? 'var(--green-500)' : 'var(--text-dim)'};">${activeSetupCount}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;">Ready</div>
                    <div style="font-size:13px;font-weight:600;font-family:var(--font-mono);margin-top:2px;color:${readyHeads > 0 ? 'var(--green-500)' : 'var(--text-dim)'};">${readyHeads}/${readyHeads + uncertainHeads + staleHeads}</div>
                </div>
            </div>
        `;

        // ── Head Alignment ──
        if (headReports.length > 0) {
            html += this._renderHeadAlignment(headAlignment, headReports);
        }

        // ── Conviction Breakdown ──
        html += this._renderConvictionBreakdown(convictionBand, floorConfidence, floorBias);

        // ── No-Trade Actionable Info ──
        if (isNoTrade && noTradeClassification) {
            html += this._renderNoTradeActions(noTradeClassification, staleHeads, uncertainHeads, silenceReason);
        }

        // ── Trade-specific info (if active trade) ──
        if (isTrade) {
            html += this._renderTradeContext(captain, floorSummary);
        }

        html += `
            </div>
        </div>
        `;

        this._container.innerHTML = html;
    },

    /**
     * Classify the no-trade reason into a structured category.
     * @private
     * @param {string} decision
     * @param {object} captain
     * @param {object} floorSummary
     * @param {Array} headReports
     * @returns {{category: string, label: string, description: string}|null}
     */
    _classifyNoTrade(decision, captain, floorSummary, headReports) {
        if (decision !== 'WAIT' && decision !== 'HOLD' && decision !== 'BLOCKED') return null;

        const silence = (captain.silence_reason || '').toLowerCase();
        const story = (captain.market_story_summary || '').toLowerCase();
        const activeSetups = floorSummary.active_setup_count ?? 0;
        const staleCount = floorSummary.stale_heads ?? 0;
        const uncertainCount = floorSummary.uncertain_heads ?? 0;
        const activeTrade = captain.active_trade || false;

        // Check for active trade lock
        if (activeTrade) {
            return {
                category: 'ACTIVE_TRADE',
                label: 'Active Trade Exists',
                description: 'Cannot enter new trade while an active trade is in progress. Current trade must close first.',
            };
        }

        // Check for health restrictions
        if (staleCount > 2 || silence.includes('stale') || silence.includes('degraded')) {
            return {
                category: 'HEALTH',
                label: 'Health Restriction',
                description: silence || 'Data health degradation or stale heads prevent reliable analysis.',
            };
        }

        // Check for no setups
        if (activeSetups === 0 && (silence.includes('setup') || silence.includes('no setup') || silence.includes('opportunity'))) {
            return {
                category: 'SETUP_ABSENT',
                label: 'Setup Absent',
                description: silence || 'No actionable setup detected across active heads.',
            };
        }

        // Check for conflict
        if (uncertainCount > 2 || silence.includes('conflict') || silence.includes('mixed')) {
            return {
                category: 'CONFLICT',
                label: 'Head Conflict',
                description: silence || 'Heads are in conflict — no clear directional consensus across departments.',
            };
        }

        // Check for governance restriction
        if (silence.includes('governance') || silence.includes('permission') || silence.includes('lock')) {
            return {
                category: 'GOVERNANCE',
                label: 'Governance Restriction',
                description: silence || 'Governance rules or permission gate is blocking trade execution.',
            };
        }

        // Check for manual restriction
        if (silence.includes('manual') || silence.includes('operator')) {
            return {
                category: 'MANUAL',
                label: 'Manual Restriction',
                description: silence || 'Operator-imposed restriction or manual override is active.',
            };
        }

        // Default: not enough conviction
        return {
            category: 'CONVICTION',
            label: 'Insufficient Conviction',
            description: silence || `Current conviction (${captain.conviction_band || 'REJECT'}) below trade threshold. Waiting for stronger alignment.`,
        };
    },

    /**
     * Analyze which heads align with the current decision.
     * @private
     * @param {Array} heads - list of head report objects
     * @param {string} floorBias
     * @returns {{aligned: Array, opposed: Array, neutral: Array}}
     */
    _analyzeHeadAlignment(heads, floorBias) {
        const aligned = [];
        const opposed = [];
        const neutral = [];

        heads.forEach(h => {
            const bias = (h.bias || 'NEUTRAL').toUpperCase();
            const confidence = h.confidence ?? 0;
            const state = h.state || 'READY';
            const name = h.head_name || 'Unknown';

            if (state === 'STALE' || state === 'ERROR') {
                neutral.push({ name, reason: `${state} — not considered` });
                return;
            }

            if (bias === floorBias) {
                aligned.push({ name, bias, confidence, state });
            } else if (bias === 'NEUTRAL' || bias === 'MIXED') {
                neutral.push({ name, bias, confidence, state, reason: 'Neutral/mixed stance' });
            } else {
                opposed.push({ name, bias, confidence, state });
            }
        });

        return { aligned, opposed, neutral };
    },

    /**
     * Render the decision banner (top of panel).
     * @private
     */
    _renderDecisionBanner(decision, isTrade, isNoTrade, isBlocked, noTradeClassification, convictionBand) {
        let bannerClass = 'bg-elevated';
        let bannerIcon = '⏳';
        let bannerTitle = 'No Decision';
        let bannerDesc = 'Captain has not yet reached a decision.';

        if (isTrade) {
            bannerClass = 'var(--green-bg)';
            bannerIcon = '🟢';
            bannerTitle = 'Trade Decision';
            bannerDesc = `Captain decided to ${decision.toLowerCase()}.`;
        } else if (isBlocked) {
            bannerClass = 'var(--red-bg)';
            bannerIcon = '🔴';
            bannerTitle = 'Action Blocked';
            bannerDesc = 'Trade is blocked by governance or risk controls.';
        } else if (isNoTrade && noTradeClassification) {
            const nc = noTradeClassification;
            const bannerColors = {
                'SETUP_ABSENT': { bg: 'rgba(107,114,128,0.08)', icon: '⚪', title: 'No Setup Available' },
                'CONFLICT': { bg: 'var(--yellow-bg)', icon: '🟡', title: 'Head Conflict Detected' },
                'HEALTH': { bg: 'var(--yellow-bg)', icon: '🟡', title: 'Health Restriction' },
                'ACTIVE_TRADE': { bg: 'var(--blue-bg)', icon: '🔵', title: 'Active Trade in Progress' },
                'GOVERNANCE': { bg: 'var(--yellow-bg)', icon: '🛡', title: 'Governance Restriction' },
                'MANUAL': { bg: 'var(--red-bg)', icon: '🔴', title: 'Manual Restriction' },
                'CONVICTION': { bg: 'rgba(107,114,128,0.08)', icon: '⚪', title: 'Insufficient Conviction' },
            };
            const bc = bannerColors[nc.category] || { bg: 'rgba(107,114,128,0.08)', icon: '⚪', title: 'Waiting' };
            bannerClass = bc.bg;
            bannerIcon = bc.icon;
            bannerTitle = bc.title;
            bannerDesc = nc.description || 'Captain is waiting.';
        } else {
            bannerTitle = 'Waiting';
            bannerDesc = 'Captain is analyzing market conditions.';
        }

        return `
        <div style="background:${bannerClass};border-radius:6px;padding:10px 12px;margin-bottom:10px;border:1px solid var(--border-subtle);">
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-size:24px;">${bannerIcon}</span>
                <div style="flex:1;">
                    <div style="font-size:13px;font-weight:600;color:var(--text-primary);">${bannerTitle}</div>
                    <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">${bannerDesc}</div>
                </div>
                <span class="status-tag ${convictionBand.toLowerCase()}" style="font-size:10px;">${convictionBand}</span>
            </div>
        </div>
        `;
    },

    /**
     * Render head alignment visualization.
     * @private
     */
    _renderHeadAlignment(alignment, allHeads) {
        const { aligned, opposed, neutral } = alignment;
        const total = allHeads.length;
        const alignedPct = total > 0 ? Math.round((aligned.length / total) * 100) : 0;
        const opposedPct = total > 0 ? Math.round((opposed.length / total) * 100) : 0;

        let html = `
        <div style="margin-bottom:10px;">
            <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">🎯 Head Alignment (${total})</div>

            <!-- Visual bar -->
            <div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin-bottom:6px;background:var(--bg-surface);">
                ${aligned.length > 0 ? `<div style="width:${alignedPct}%;background:var(--green-500);transition:width 0.3s;" title="Aligned: ${aligned.length}"></div>` : ''}
                ${neutral.length > 0 ? `<div style="width:${neutral.length > 0 ? Math.round((neutral.length / total) * 100) : 0}%;background:var(--text-dim);transition:width 0.3s;" title="Neutral: ${neutral.length}"></div>` : ''}
                ${opposed.length > 0 ? `<div style="width:${opposedPct}%;background:var(--red-500);transition:width 0.3s;" title="Opposed: ${opposed.length}"></div>` : ''}
            </div>

            <!-- Legend -->
            <div style="display:flex;gap:12px;font-size:10px;color:var(--text-muted);">
                <span><span class="health-dot health-good" style="width:6px;height:6px;display:inline-block;margin-right:3px;"></span> ${aligned.length} Aligned</span>
                <span><span style="width:6px;height:6px;border-radius:50%;background:var(--text-dim);display:inline-block;margin-right:3px;"></span> ${neutral.length} Neutral</span>
                <span><span class="health-dot health-critical" style="width:6px;height:6px;display:inline-block;margin-right:3px;"></span> ${opposed.length} Opposed</span>
            </div>
        </div>
        `;

        // Head list (compact)
        html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:10px;">';

        allHeads.forEach(h => {
            const name = h.head_name || 'Unknown';
            const bias = h.bias || 'NEUTRAL';
            const confidence = h.confidence ?? 0;
            const state = h.state || 'READY';

            const isAligned = aligned.some(a => a.name === name);
            const isOpposed = opposed.some(a => a.name === name);
            const dotColor = isAligned ? 'var(--green-500)' : isOpposed ? 'var(--red-500)' : 'var(--text-dim)';
            const borderColor = isAligned ? 'var(--green-500)' : isOpposed ? 'var(--red-500)' : 'transparent';

            const confColor = confidence >= 0.7 ? 'var(--green-500)' : confidence >= 0.4 ? 'var(--yellow-500)' : 'var(--red-500)';

            html += `
            <div style="display:flex;align-items:center;gap:6px;padding:5px 8px;background:var(--bg-elevated);border-radius:4px;border-left:2px solid ${borderColor};">
                <span style="width:6px;height:6px;border-radius:50%;background:${dotColor};flex-shrink:0;"></span>
                <span style="font-size:10px;font-weight:500;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</span>
                <span style="font-size:9px;color:${confColor};font-family:var(--font-mono);">${Math.round(confidence * 100)}%</span>
                <span style="font-size:9px;color:var(--text-dim);font-family:var(--font-mono);">${this._biasIcon(bias)}</span>
            </div>
            `;
        });

        html += '</div>';

        return html;
    },

    /**
     * Render conviction score breakdown.
     * @private
     */
    _renderConvictionBreakdown(convictionBand, floorConfidence, floorBias) {
        const band = convictionBand.toUpperCase();
        const bands = ['REJECT', 'WEAK', 'TRADABLE', 'STRONG', 'ELITE'];
        const bandIndex = bands.indexOf(band);
        const confPct = Math.round(floorConfidence * 100);

        // Conviction thresholds
        const thresholds = {
            'REJECT': { color: 'var(--text-dim)', pct: 10, desc: 'Rejected — conditions not met' },
            'WEAK': { color: 'var(--yellow-500)', pct: 25, desc: 'Weak signs — monitoring only' },
            'TRADABLE': { color: 'var(--blue-500)', pct: 50, desc: 'Tradable — conditions acceptable' },
            'STRONG': { color: 'var(--green-500)', pct: 75, desc: 'Strong alignment — high confidence' },
            'ELITE': { color: 'var(--green-400)', pct: 95, desc: 'Elite alignment — maximum conviction' },
        };
        const t = thresholds[band] || thresholds['REJECT'];

        let html = `
        <div style="margin-bottom:8px;">
            <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">📊 Conviction Analysis</div>
            <div style="background:var(--bg-elevated);border-radius:6px;padding:8px 10px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                    <span style="font-size:11px;font-weight:600;color:${t.color};">${convictionBand}</span>
                    <span style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);">${confPct}% floor confidence</span>
                </div>
                <div class="conviction-bar" style="height:6px;margin-bottom:4px;">
                    <div class="conviction-fill ${band.toLowerCase()}" style="width:${t.pct}%;height:100%;"></div>
                </div>
                <div style="font-size:10px;color:var(--text-secondary);">${t.desc}${floorBias !== 'NEUTRAL' ? ` | Floor bias: ${floorBias}` : ''}</div>
                <!-- Band indicator dots -->
                <div style="display:flex;gap:4px;margin-top:6px;">
                    ${bands.map((b, i) => `
                        <div style="flex:1;height:3px;border-radius:2px;background:${i <= bandIndex ? (thresholds[b]?.color || 'var(--text-dim)') : 'var(--bg-surface)'};"></div>
                    `).join('')}
                </div>
                <div style="display:flex;justify-content:space-between;margin-top:2px;font-size:8px;color:var(--text-dim);">
                    <span>Reject</span><span>Weak</span><span>Tradable</span><span>Strong</span><span>Elite</span>
                </div>
            </div>
        </div>
        `;

        return html;
    },

    /**
     * Render no-trade actionable information.
     * @private
     */
    _renderNoTradeActions(classification, staleHeads, uncertainHeads, silenceReason) {
        const suggestions = {
            'SETUP_ABSENT': [
                'Wait for price to reach key levels',
                'Check if any head has a pending setup opportunity',
                'Monitor for new signal formation in next candle',
            ],
            'CONFLICT': [
                `Resolve ${uncertainHeads} uncertain head(s) — wait for convergence`,
                'Check individual head reports for detailed bias reasons',
                'Look for invalidation patterns that may break the conflict',
            ],
            'HEALTH': [
                `Address ${staleHeads} stale head(s) — may need data refresh`,
                'Check Floor 2 data health signal for degradation source',
                'Wait for system health to normalize',
            ],
            'ACTIVE_TRADE': [
                'Focus on current trade management — SL/TGT/protection',
                'New entry will be considered after current trade resolves',
                'Monitor current trade for early exit or add opportunities',
            ],
            'GOVERNANCE': [
                'Check permission gate for specific blocked check',
                'Review escalation level — may need operator intervention',
                'Override available if conditions warrant',
            ],
            'MANUAL': [
                'Check if operator restriction is still intentional',
                'Review override or kill switch state',
                'Manual restrictions must be lifted by operator',
            ],
            'CONVICTION': [
                'Wait for stronger head alignment',
                'Monitor for market structure shift (BOS/CHoCH)',
                'Watch for increasing confidence in individual heads',
            ],
        };

        const cat = classification.category;
        const tips = suggestions[cat] || ['Monitor market conditions for change'];

        let html = `
        <div style="margin-bottom:8px;">
            <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">💡 Suggested Actions</div>
            <div style="background:var(--bg-elevated);border-radius:6px;padding:8px 10px;">
                <ul style="margin:0;padding:0 0 0 16px;font-size:10px;color:var(--text-secondary);line-height:1.8;">
                    ${tips.map(t => `<li>${this._escapeHtml(t)}</li>`).join('')}
                </ul>
            </div>
        </div>
        `;

        return html;
    },

    /**
     * Render trade-specific context (when trade is active).
     * @private
     */
    _renderTradeContext(captain, floorSummary) {
        const convictionBand = captain.conviction_band || 'REJECT';
        const convictionClass = convictionBand.toLowerCase();

        let html = `
        <div style="margin-top:4px;">
            <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">💰 Trade Context</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);">Conviction</div>
                    <div class="status-tag ${convictionClass}" style="font-size:10px;margin-top:2px;">${convictionBand}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:4px;padding:6px 8px;text-align:center;">
                    <div style="font-size:9px;color:var(--text-dim);">Session</div>
                    <div style="font-size:11px;font-weight:600;font-family:var(--font-mono);margin-top:2px;">${captain.session_phase || '--'}</div>
                </div>
            </div>
        </div>
        `;

        return html;
    },

    /**
     * Get bias icon.
     * @private
     * @param {string} bias
     * @returns {string}
     */
    _biasIcon(bias) {
        const icons = {
            'NEUTRAL': '⚪',
            'BULLISH': '📈',
            'BEARISH': '📉',
            'MIXED': '🔀',
        };
        return icons[bias.toUpperCase()] || '⚪';
    },

    /** @private */
    _escapeHtml(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    },
};

// Register with ComponentManager
ComponentManager.register('explainability', ExplainabilityPanel);
