/**
 * Junior Aladdin — Operator Terminal
 * utils/colors.js — Centralized color constants and helper functions
 *
 * All color-related logic lives here so panels and components
 * use consistent colors for the same meaning.
 *
 * Reference: ROADMAP_SIDE_B Step 8.13 — Formatters + Colors
 */

const Colors = {
    // ── Semantic Colors (maps to CSS variables) ──
    BULLISH: 'var(--green-500)',
    BEARISH: 'var(--red-500)',
    NEUTRAL: 'var(--text-dim)',
    WARNING: 'var(--yellow-500)',
    INFO: 'var(--blue-500)',
    ACTIVE: 'var(--blue-500)',

    // ── State → Color mapping ──
    state: {
        healthy: 'var(--green-500)',
        connected: 'var(--green-500)',
        good: 'var(--green-500)',
        ready: 'var(--green-500)',
        degraded: 'var(--yellow-500)',
        stale: 'var(--yellow-500)',
        uncertain: 'var(--yellow-500)',
        critical: 'var(--red-500)',
        error: 'var(--red-500)',
        disconnected: 'var(--red-500)',
        unavailable: 'var(--text-dim)',
        unknown: 'var(--text-dim)',
        silent: 'var(--text-dim)',
    },

    // ── State → CSS class mapping for status-tag ──
    stateClass: {
        healthy: 'ready',
        connected: 'ready',
        good: 'ready',
        ready: 'ready',
        degraded: 'uncertain',
        stale: 'stale',
        uncertain: 'uncertain',
        critical: 'error',
        error: 'error',
        disconnected: 'error',
        unavailable: 'disabled',
    },

    // ── State → Health dot class ──
    healthDotClass: {
        healthy: 'health-good',
        connected: 'health-good',
        good: 'health-good',
        ready: 'health-good',
        degraded: 'health-degraded',
        stale: 'health-degraded',
        uncertain: 'health-degraded',
        critical: 'health-critical',
        error: 'health-critical',
        disconnected: 'health-critical',
        unavailable: 'health-unknown',
        unknown: 'health-unknown',
        silent: 'health-unknown',
    },

    // ── Bias Icons ──
    biasIcon(bias) {
        const map = {
            'BULLISH': '📈',
            'BEARISH': '📉',
            'NEUTRAL': '⚪',
            'MIXED': '🔀',
        };
        return map[(bias || 'NEUTRAL').toUpperCase()] || '⚪';
    },

    // ── State Dot Emoji ──
    stateDot(state) {
        const s = (state || '').toUpperCase();
        if (s === 'READY' || s === 'HEALTHY' || s === 'CONNECTED' || s === 'GOOD') return '🟢';
        if (s === 'UNCERTAIN' || s === 'DEGRADED' || s === 'STALE') return '🟡';
        if (s === 'CRITICAL' || s === 'ERROR' || s === 'DISCONNECTED') return '🔴';
        if (s === 'UNAVAILABLE') return '⚫';
        return '⚪';
    },

    // ── Severity color ──
    severity(severity) {
        const s = (severity || '').toUpperCase();
        if (s === 'CRITICAL') return 'var(--red-500)';
        if (s === 'SEVERE') return '#f97316';
        if (s === 'CAUTION' || s === 'WARNING') return 'var(--yellow-500)';
        return 'var(--blue-500)'; // INFO / default
    },

    // ── Freshness color ──
    freshness(freshness) {
        const f = (freshness || '').toUpperCase();
        if (f === 'FRESH') return 'text-green';
        if (f === 'RECENT') return 'text-yellow';
        if (f === 'STALE') return 'text-red';
        return 'text-muted';
    },

    // ── Confidence color (0.0–1.0) ──
    confidence(confidence) {
        if (confidence >= 0.8) return 'var(--green-500)';
        if (confidence >= 0.6) return 'var(--green-400)';
        if (confidence >= 0.4) return 'var(--yellow-500)';
        if (confidence >= 0.2) return 'var(--orange-500)';
        return 'var(--red-500)';
    },

    // ── Confidence CSS class ──
    confidenceClass(confidence) {
        if (confidence >= 0.8) return 'text-green';
        if (confidence >= 0.6) return 'text-green';
        if (confidence >= 0.4) return 'text-yellow';
        if (confidence >= 0.2) return 'text-orange';
        return 'text-red';
    },

    // ── Change color (positive/negative) ──
    change(change) {
        return (change || 0) >= 0 ? 'text-green' : 'text-red';
    },

    // ── Escalation color ──
    escalation(level) {
        const l = (level || '').toUpperCase();
        if (l === 'CRITICAL' || l === 'EMERGENCY') return 'text-red';
        if (l === 'SEVERE' || l === 'ELEVATED') return 'text-yellow';
        if (l === 'CAUTION') return 'text-yellow';
        return 'text-green';
    },

    // ── Kill-switch color ──
    killSwitch(state) {
        const s = (state || '').toUpperCase();
        if (s === 'CRITICAL') return 'text-red';
        if (s === 'SOFT') return 'text-yellow';
        if (s === 'OFF' || s === 'NORMAL') return 'text-green';
        return 'text-muted';
    },

    // ── Conviction band color ──
    convictionBand(band) {
        const b = (band || '').toUpperCase();
        if (b === 'ELITE') return 'var(--green-400)';
        if (b === 'STRONG') return 'var(--green-500)';
        if (b === 'TRADABLE') return 'var(--blue-500)';
        if (b === 'WEAK') return 'var(--yellow-500)';
        return 'var(--text-dim)'; // REJECT / default
    },
};
