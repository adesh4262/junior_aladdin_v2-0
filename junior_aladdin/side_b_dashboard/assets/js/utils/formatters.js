/**
 * Junior Aladdin — Operator Terminal
 * utils/formatters.js — Centralized formatting functions
 *
 * All display formatting logic lives here to avoid inline duplication
 * across panels and components.
 *
 * Reference: ROADMAP_SIDE_B Step 8.13 — Formatters + Colors
 */

const Formatters = {
    // ── Price ──

    /**
     * Format a price value to 2 decimal places.
     * @param {number|null|undefined} price
     * @param {string} placeholder - fallback when price is null/undefined
     * @returns {string}
     */
    price(price, placeholder = '--') {
        if (price == null || isNaN(price)) return placeholder;
        return Number(price).toFixed(2);
    },

    /**
     * Format a price with ₹ prefix.
     * @param {number|null|undefined} price
     * @param {string} placeholder
     * @returns {string}
     */
    priceInr(price, placeholder = '--') {
        if (price == null || isNaN(price)) return placeholder;
        return `₹${Number(price).toFixed(2)}`;
    },

    // ── PnL ──

    /**
     * Format PnL with sign (+/-).
     * @param {number|null|undefined} pnl
     * @param {string} placeholder
     * @returns {string}
     */
    pnl(pnl, placeholder = '--') {
        if (pnl == null || isNaN(pnl)) return placeholder;
        const prefix = pnl >= 0 ? '+' : '';
        return `${prefix}${Number(pnl).toFixed(2)}`;
    },

    /**
     * Format PnL with ₹ prefix and sign.
     * @param {number|null|undefined} pnl
     * @param {string} placeholder
     * @returns {string}
     */
    pnlInr(pnl, placeholder = '--') {
        if (pnl == null || isNaN(pnl)) return placeholder;
        const prefix = pnl >= 0 ? '+' : '';
        return `${prefix}₹${Number(pnl).toFixed(2)}`;
    },

    // ── Percentage ──

    /**
     * Format a percentage value with 2 decimal places and % sign.
     * @param {number|null|undefined} pct
     * @param {string} placeholder
     * @returns {string}
     */
    percent(pct, placeholder = '--') {
        if (pct == null || isNaN(pct)) return placeholder;
        const prefix = pct >= 0 ? '+' : '';
        return `${prefix}${Number(pct).toFixed(2)}%`;
    },

    /**
     * Format a 0–1 ratio as percentage.
     * @param {number|null|undefined} ratio - 0.0 to 1.0
     * @param {number} decimals
     * @param {string} placeholder
     * @returns {string}
     */
    ratioAsPercent(ratio, decimals = 1, placeholder = '--') {
        if (ratio == null || isNaN(ratio)) return placeholder;
        return `${(Number(ratio) * 100).toFixed(decimals)}%`;
    },

    // ── Volume ──

    /**
     * Format volume in human-readable format (Cr/L/short).
     * @param {number|null|undefined} volume
     * @param {string} placeholder
     * @returns {string}
     */
    volume(volume, placeholder = '--') {
        if (volume == null || isNaN(volume)) return placeholder;
        const v = Number(volume);
        if (v >= 1e7) return (v / 1e7).toFixed(2) + 'Cr';
        if (v >= 1e5) return (v / 1e5).toFixed(2) + 'L';
        return v.toLocaleString('en-IN');
    },

    // ── Capital ──

    /**
     * Format capital with ₹ and Indian locale.
     * @param {number|null|undefined} amount
     * @param {string} placeholder
     * @returns {string}
     */
    capital(amount, placeholder = '--') {
        if (amount == null || isNaN(amount)) return placeholder;
        return `₹${Number(amount).toLocaleString('en-IN')}`;
    },

    // ── Timestamp ──

    /**
     * Format an ISO timestamp or Date to locale time string.
     * @param {string|Date|null|undefined} ts
     * @param {object} [options]
     * @param {boolean} [options.showSeconds=true]
     * @param {boolean} [options.showDate=false]
     * @param {string} [placeholder='--:--:--']
     * @returns {string}
     */
    time(ts, options = {}) {
        const { showSeconds = true, showDate = false, placeholder = '--:--:--' } = options;
        if (!ts) return placeholder;
        try {
            const d = typeof ts === 'string' ? new Date(ts) : ts;
            if (isNaN(d.getTime())) return placeholder;
            if (showDate) {
                return d.toLocaleDateString('en-IN', {
                    day: '2-digit',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: showSeconds ? '2-digit' : undefined,
                });
            }
            return d.toLocaleTimeString('en-IN', {
                hour: '2-digit',
                minute: '2-digit',
                second: showSeconds ? '2-digit' : undefined,
            });
        } catch (e) {
            return placeholder;
        }
    },

    /**
     * Format a date for session display.
     * @param {string|Date|null|undefined} date
     * @returns {string}
     */
    sessionDate(date) {
        if (!date) return new Date().toLocaleDateString('en-IN');
        try {
            const d = typeof date === 'string' ? new Date(date) : date;
            return d.toLocaleDateString('en-IN');
        } catch (e) {
            return new Date().toLocaleDateString('en-IN');
        }
    },

    /**
     * Format elapsed seconds to HH:MM:SS.
     * @param {number} totalSeconds
     * @returns {string}
     */
    duration(totalSeconds) {
        const h = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
        const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
        const s = String(Math.floor(totalSeconds % 60)).padStart(2, '0');
        return `${h}:${m}:${s}`;
    },

    // ── Quantity ──

    /**
     * Format a quantity/lot size number.
     * @param {number|null|undefined} qty
     * @param {string} placeholder
     * @returns {string}
     */
    qty(qty, placeholder = '--') {
        if (qty == null || isNaN(qty)) return placeholder;
        return Number(qty).toLocaleString('en-IN');
    },

    // ── Spread ──

    /**
     * Format Bid/Ask spread.
     * @param {number|null|undefined} bid
     * @param {number|null|undefined} ask
     * @param {string} placeholder
     * @returns {string}
     */
    spread(bid, ask, placeholder = '--') {
        if (bid == null || ask == null) return placeholder;
        return (ask - bid).toFixed(2);
    },

    // ── Change + Percent combined ──

    /**
     * Format change as "±X.XX (±X.XX%)"
     * @param {number|null|undefined} change
     * @param {number|null|undefined} changePercent
     * @param {string} placeholder
     * @returns {string}
     */
    changeWithPercent(change, changePercent, placeholder = '--') {
        if (change == null || isNaN(change)) return placeholder;
        const prefix = change >= 0 ? '+' : '';
        const pctStr = changePercent != null ? ` (${prefix}${Number(changePercent).toFixed(2)}%)` : '';
        return `${prefix}${Number(change).toFixed(2)}${pctStr}`;
    },

    // ── Escalation level label ──

    /**
     * Format escalation level with emoji prefix.
     * @param {string} level
     * @returns {string}
     */
    escalationLabel(level) {
        const l = (level || '').toUpperCase();
        if (l === 'NORMAL') return '🟢 Normal';
        if (l === 'CAUTION') return '🟡 Caution';
        if (l === 'SEVERE') return '🟠 Severe';
        if (l === 'CRITICAL' || l === 'EMERGENCY') return '🔴 Critical';
        return '⚪ Unknown';
    },

    // ── Capital truncated display ──

    /**
     * Short capital display for status bars (compact).
     * @param {number|null|undefined} amount
     * @returns {string}
     */
    capitalShort(amount) {
        if (amount == null || isNaN(amount)) return '--';
        const v = Number(amount);
        if (v >= 1e7) return `₹${(v / 1e7).toFixed(1)}Cr`;
        if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)}L`;
        return `₹${v.toLocaleString('en-IN')}`;
    },

    // ── Escape HTML (moved from inline helpers) ──

    /**
     * Escape HTML special characters for safe innerHTML usage.
     * @param {*} str
     * @returns {string}
     */
    escapeHtml(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    },
};
