/**
 * Junior Aladdin — Operator Terminal
 * session_cache_display.js — Session Cache Display Workspace
 *
 * Three-tier (HOT/WARM/COLD) cache viewer with:
 *   - Cache summary stats (entries, hit ratio, tier counts)
 *   - Live entry list grouped by tier with search/filter
 *   - Entry detail inspection (click to expand full value)
 *   - Manual invalidation (single key, tier, or full clear)
 *   - Auto-refresh polling (5s) + manual refresh
 *
 * Reference: ROADMAP_SIDE_B Step 8.19 — Cache Viewer
 */

const SessionCacheDisplay = {
    /** @type {HTMLElement|null} */
    _container: null,

    /** @type {boolean} */
    _polling: false,

    /** @type {number|null} */
    _pollTimer: null,

    /** @type {object} Cached data */
    _data: {
        stats: null,
        entries: [],
        entryCount: 0,
        selectedEntry: null,
        filterTier: 'ALL',
        searchQuery: '',
    },

    /**
     * Render the cache display into a container.
     * @param {HTMLElement} container
     */
    render(container) {
        this._container = container;
        this._renderLayout();
        this._loadAllData();
        this._startPolling();
    },

    /** Unmount and clean up */
    unmount() {
        this._stopPolling();
        this._container = null;
    },

    // ── Layout ──

    /** @private */
    _renderLayout() {
        if (!this._container) return;

        this._container.innerHTML = `
            <div class="review-layout">
                <!-- Left: Main Panel -->
                <div class="review-main">
                    <!-- Cache Summary -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">💾 Cache Summary</span>
                            <span class="panel-card-badge refresh-hot">LIVE</span>
                        </div>
                        <div class="panel-card-body" id="cache-summary">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line-sm"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Cache Entries List -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">📋 Cache Entries</span>
                            <span class="panel-card-badge" id="cache-entry-count">0 entries</span>
                        </div>
                        <div class="panel-card-body" style="padding-bottom:4px;">
                            <!-- Filter bar -->
                            <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
                                <div style="display:flex;gap:4px;" id="cache-tier-filters">
                                    <button class="tier-filter active" data-tier="ALL" style="font-size:10px;padding:3px 8px;border-radius:4px;border:1px solid var(--border-default);background:var(--bg-surface);cursor:pointer;color:var(--text-primary);">All</button>
                                    <button class="tier-filter" data-tier="HOT" style="font-size:10px;padding:3px 8px;border-radius:4px;border:1px solid var(--border-default);background:var(--bg-surface);cursor:pointer;color:var(--red-500);">🔥 HOT</button>
                                    <button class="tier-filter" data-tier="WARM" style="font-size:10px;padding:3px 8px;border-radius:4px;border:1px solid var(--border-default);background:var(--bg-surface);cursor:pointer;color:var(--yellow-500);">☀ WARM</button>
                                    <button class="tier-filter" data-tier="COLD" style="font-size:10px;padding:3px 8px;border-radius:4px;border:1px solid var(--border-default);background:var(--bg-surface);cursor:pointer;color:var(--blue-500);">❄ COLD</button>
                                </div>
                                <input type="text" id="cache-search-input" placeholder="Search keys..." style="flex:1;min-width:120px;font-size:10px;padding:3px 8px;border-radius:4px;border:1px solid var(--border-default);background:var(--bg-surface);color:var(--text-primary);outline:none;" />
                            </div>
                        </div>
                        <div class="panel-card-body review-data-stream" id="cache-entry-list" style="max-height:400px;overflow-y:auto;">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line-sm"></div>
                                <div class="skeleton skeleton-line"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Right: Sidebar -->
                <div class="review-sidebar">
                    <!-- Entry Detail -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">🔍 Entry Detail</span>
                        </div>
                        <div class="panel-card-body" id="cache-entry-detail">
                            <div class="placeholder-message small" style="min-height:80px;">
                                <div class="placeholder-text">Click an entry to inspect</div>
                            </div>
                        </div>
                    </div>

                    <!-- Tier Breakdown -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">📊 Tier Breakdown</span>
                            <span class="panel-card-badge refresh-cold">COLD</span>
                        </div>
                        <div class="panel-card-body" id="cache-tier-breakdown">
                            <div class="skeleton-loading">
                                <div class="skeleton skeleton-line"></div>
                                <div class="skeleton skeleton-line"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Actions -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⚡ Actions</span>
                        </div>
                        <div class="panel-card-body" style="display:flex;flex-direction:column;gap:6px;">
                            <button class="control-btn" style="width:100%;font-size:11px;padding:5px 10px;" id="cache-refresh-btn">
                                ↻ Refresh Cache Data
                            </button>
                            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;">
                                <button class="control-btn inv-tier-btn" data-tier="HOT" style="font-size:9px;padding:4px 6px;border-color:var(--red-500);color:var(--red-500);">🔥 Clear HOT</button>
                                <button class="control-btn inv-tier-btn" data-tier="WARM" style="font-size:9px;padding:4px 6px;border-color:var(--yellow-500);color:var(--yellow-500);">☀ Clear WARM</button>
                                <button class="control-btn inv-tier-btn" data-tier="COLD" style="font-size:9px;padding:4px 6px;border-color:var(--blue-500);color:var(--blue-500);">❄ Clear COLD</button>
                            </div>
                            <button class="control-btn" style="width:100%;font-size:10px;padding:4px 10px;border-color:var(--red-500);color:var(--red-500);" id="cache-clear-all-btn">
                                ⚠ Clear Entire Cache
                            </button>
                        </div>
                    </div>

                    <!-- Quick Stats -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">📈 Performance</span>
                        </div>
                        <div class="panel-card-body" id="cache-performance">
                            <div class="placeholder-message small">
                                <div class="placeholder-text">Loading stats...</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this._wireEvents();
    },

    // ── Event Wiring ──

    /** @private */
    _wireEvents() {
        // Refresh button
        const refreshBtn = document.getElementById('cache-refresh-btn');
        if (refreshBtn) refreshBtn.addEventListener('click', () => this._loadAllData());

        // Tier filter buttons
        const filterBtns = document.querySelectorAll('.tier-filter');
        filterBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                filterBtns.forEach(b => {
                    b.classList.remove('active');
                    b.style.background = 'var(--bg-surface)';
                });
                btn.classList.add('active');
                btn.style.background = 'var(--bg-elevated)';
                this._data.filterTier = btn.dataset.tier;
                this._renderEntryList();
            });
        });
        // Set initial active state
        const activeBtn = document.querySelector('.tier-filter.active');
        if (activeBtn) activeBtn.style.background = 'var(--bg-elevated)';

        // Search input
        const searchInput = document.getElementById('cache-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this._data.searchQuery = e.target.value.toLowerCase();
                this._renderEntryList();
            });
        }

        // Invalidate tier buttons
        const invTierBtns = document.querySelectorAll('.inv-tier-btn');
        invTierBtns.forEach(btn => {
            btn.addEventListener('click', async () => {
                const tier = btn.dataset.tier;
                await this._invalidateTier(tier);
            });
        });

        // Clear all button
        const clearAllBtn = document.getElementById('cache-clear-all-btn');
        if (clearAllBtn) clearAllBtn.addEventListener('click', () => this._clearAll());
    },

    // ── Data Loading ──

    /** @private */
    async _loadAllData() {
        await Promise.all([
            this._loadStats(),
            this._loadEntries(),
        ]);
    },

    /** @private */
    async _loadStats() {
        try {
            const stats = await api.getCacheStats();
            this._data.stats = stats;
            this._renderSummary(stats);
            this._renderTierBreakdown(stats);
            this._renderPerformance(stats);

            // Update badge
            const badge = document.getElementById('cache-entry-count');
            if (badge) badge.textContent = `${stats.total_entries ?? 0} entries`;
        } catch (e) {
            const el = document.getElementById('cache-summary');
            if (el) {
                el.innerHTML = `
                    <div class="panel-row">
                        <span class="panel-label">Status</span>
                        <span class="panel-value text-red">Failed to load cache stats</span>
                    </div>
                    <div class="panel-row">
                        <span class="panel-label">Error</span>
                        <span class="panel-value text-muted" style="font-size:10px;">${escapeHtml(e.message || 'Unknown error')}</span>
                    </div>
                `;
            }
        }
    },

    /** @private */
    async _loadEntries() {
        try {
            const result = await api.get('/api/debug/cache-keys');
            this._data.entries = result.entries || [];
            this._data.entryCount = result.count || 0;
            this._renderEntryList();
        } catch (e) {
            const el = document.getElementById('cache-entry-list');
            if (el) {
                el.innerHTML = `
                    <div class="panel-row">
                        <span class="panel-label">Error</span>
                        <span class="panel-value text-red">${escapeHtml(e.message || 'Failed to load entries')}</span>
                    </div>
                `;
            }
        }
    },

    /** @private */
    async _loadEntryDetail(key) {
        const detailEl = document.getElementById('cache-entry-detail');
        if (!detailEl) return;

        detailEl.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-dim);font-size:11px;">Loading detail...</div>';

        try {
            const detail = await api.get(`/api/debug/cache-entry/${encodeURIComponent(key)}`);
            this._renderEntryDetail(detail, detailEl);
        } catch (e) {
            detailEl.innerHTML = `
                <div class="panel-row">
                    <span class="panel-label">Error</span>
                    <span class="panel-value text-red">${escapeHtml(e.message || 'Failed to load entry')}</span>
                </div>
            `;
        }
    },

    // ── Renderers ──

    /** @private */
    _renderSummary(stats) {
        const el = document.getElementById('cache-summary');
        if (!el) return;

        const hitPct = stats.hit_ratio != null ? (stats.hit_ratio * 100).toFixed(1) + '%' : '—';
        const hitColor = stats.hit_ratio > 0.8 ? 'text-green' : stats.hit_ratio > 0.5 ? 'text-yellow' : 'text-red';

        el.innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:8px;">
                <div style="background:var(--bg-elevated);border-radius:6px;padding:10px 12px;text-align:center;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Total</div>
                    <div class="mono" style="font-size:22px;font-weight:700;margin-top:2px;">${stats.total_entries ?? 0}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:6px;padding:10px 12px;text-align:center;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Max</div>
                    <div class="mono" style="font-size:22px;font-weight:700;margin-top:2px;">${stats.max_entries ?? '—'}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:6px;padding:10px 12px;text-align:center;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Hit Ratio</div>
                    <div class="mono" style="font-size:22px;font-weight:700;margin-top:2px;color:var(--${hitColor.includes('green') ? 'green' : hitColor.includes('yellow') ? 'yellow' : 'red'}-500);">${hitPct}</div>
                </div>
                <div style="background:var(--bg-elevated);border-radius:6px;padding:10px 12px;text-align:center;">
                    <div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Misses</div>
                    <div class="mono" style="font-size:22px;font-weight:700;margin-top:2px;">${stats.total_misses ?? 0}</div>
                </div>
            </div>
            <div class="panel-row" style="border-top:1px solid var(--border-subtle);padding-top:6px;">
                <span class="panel-label">Usage</span>
                <span class="panel-value mono" style="font-size:11px;">
                    ${(stats.total_entries ?? 0)} / ${stats.max_entries ?? '—'} entries
                    (${stats.max_entries ? Math.round((stats.total_entries / stats.max_entries) * 100) : 0}%)
                </span>
            </div>
        `;
    },

    /** @private */
    _renderTierBreakdown(stats) {
        const el = document.getElementById('cache-tier-breakdown');
        if (!el) return;

        const tiers = stats.tier_counts || {};
        const total = stats.total_entries || 1;

        const tierConfig = [
            { key: 'HOT', label: '🔥 HOT', color: 'var(--red-500)', bg: 'rgba(239,68,68,0.1)' },
            { key: 'WARM', label: '☀ WARM', color: 'var(--yellow-500)', bg: 'rgba(234,179,8,0.1)' },
            { key: 'COLD', label: '❄ COLD', color: 'var(--blue-500)', bg: 'rgba(59,130,246,0.1)' },
        ];

        el.innerHTML = tierConfig.map(tc => {
            const count = tiers[tc.key] || 0;
            const pct = Math.round((count / total) * 100);
            return `
                <div style="margin-bottom:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                        <span style="font-size:11px;font-weight:600;color:${tc.color};">${tc.label}</span>
                        <span class="mono" style="font-size:13px;font-weight:700;">${count}</span>
                    </div>
                    <div style="height:8px;background:var(--bg-surface);border-radius:4px;overflow:hidden;">
                        <div style="width:${pct}%;height:100%;border-radius:4px;background:${tc.color};transition:width 0.3s;"></div>
                    </div>
                    <div style="font-size:9px;color:var(--text-dim);margin-top:2px;">${pct}% of total</div>
                </div>
            `;
        }).join('');
    },

    /** @private */
    _renderPerformance(stats) {
        const el = document.getElementById('cache-performance');
        if (!el) return;

        const hitPct = stats.hit_ratio != null ? (stats.hit_ratio * 100).toFixed(1) + '%' : '—';
        const tierMisses = stats.tier_misses || {};
        const unknownMisses = stats.unknown_misses ?? 0;

        el.innerHTML = `
            <div class="panel-row">
                <span class="panel-label">Total Hits</span>
                <span class="panel-value mono">${stats.total_hits ?? 0}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Total Misses</span>
                <span class="panel-value mono text-yellow">${stats.total_misses ?? 0}</span>
            </div>
            <div class="panel-row">
                <span class="panel-label">Hit Ratio</span>
                <span class="panel-value mono ${hitPct !== '—' && parseFloat(hitPct) > 80 ? 'text-green' : 'text-yellow'}">${hitPct}</span>
            </div>
            <div style="border-top:1px solid var(--border-subtle);padding-top:6px;margin-top:4px;">
                <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Per-Tier Misses</div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px;">
                    <div style="background:var(--bg-elevated);border-radius:4px;padding:4px 6px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);">HOT</div>
                        <div class="mono" style="font-size:12px;font-weight:600;">${tierMisses.HOT ?? 0}</div>
                    </div>
                    <div style="background:var(--bg-elevated);border-radius:4px;padding:4px 6px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);">WARM</div>
                        <div class="mono" style="font-size:12px;font-weight:600;">${tierMisses.WARM ?? 0}</div>
                    </div>
                    <div style="background:var(--bg-elevated);border-radius:4px;padding:4px 6px;text-align:center;">
                        <div style="font-size:9px;color:var(--text-dim);">COLD</div>
                        <div class="mono" style="font-size:12px;font-weight:600;">${tierMisses.COLD ?? 0}</div>
                    </div>
                </div>
                ${unknownMisses > 0 ? `<div class="panel-row" style="margin-top:4px;"><span class="panel-label">Unknown Key Misses</span><span class="panel-value mono text-yellow">${unknownMisses}</span></div>` : ''}
            </div>
        `;
    },

    /** @private */
    _renderEntryList() {
        const el = document.getElementById('cache-entry-list');
        if (!el) return;

        let entries = this._data.entries || [];

        // Apply tier filter
        const filter = this._data.filterTier;
        if (filter !== 'ALL') {
            entries = entries.filter(e => e.tier === filter);
        }

        // Apply search
        const query = this._data.searchQuery;
        if (query) {
            entries = entries.filter(e => e.key.toLowerCase().includes(query));
        }

        if (entries.length === 0) {
            el.innerHTML = `
                <div class="placeholder-message small" style="padding:20px 0;">
                    <div class="placeholder-text">${this._data.entryCount > 0 ? 'No entries match filter' : 'No cache entries available'}</div>
                </div>
            `;
            return;
        }

        // Group by tier for display
        const grouped = { HOT: [], WARM: [], COLD: [] };
        entries.forEach(e => {
            const t = e.tier || 'COLD';
            if (grouped[t]) grouped[t].push(e);
        });

        const tierColor = { HOT: 'var(--red-500)', WARM: 'var(--yellow-500)', COLD: 'var(--blue-500)' };
        const tierIcon = { HOT: '🔥', WARM: '☀', COLD: '❄' };

        let html = '<div class="review-entry-list">';

        ['HOT', 'WARM', 'COLD'].forEach(tier => {
            const group = grouped[tier] || [];
            if (group.length === 0) return;

            html += `
                <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;padding:6px 0 3px 6px;border-bottom:1px solid var(--border-subtle);margin-bottom:4px;">
                    ${tierIcon[tier]} ${tier} (${group.length})
                </div>
            `;

            group.forEach(entry => {
                const ageStr = entry.age_s < 60
                    ? Math.round(entry.age_s) + 's'
                    : Math.round(entry.age_s / 60) + 'm';

                const borderColor = tierColor[entry.tier] || 'var(--border-default)';
                const expiredClass = entry.is_expired ? 'opacity:0.5;' : '';

                html += `
                    <div class="review-entry cache-entry-item" data-key="${escapeHtml(entry.key)}" style="border-left:3px solid ${borderColor};cursor:pointer;${expiredClass}">
                        <div class="review-entry-header">
                            <span style="display:flex;align-items:center;gap:6px;flex:1;min-width:0;">
                                <span class="mono" style="font-size:10px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(entry.key)}</span>
                                <span class="status-tag" style="font-size:8px;padding:1px 4px;background:${borderColor}20;color:${borderColor};">${entry.tier}</span>
                                ${entry.is_expired ? '<span style="font-size:8px;color:var(--text-red);">EXPIRED</span>' : ''}
                            </span>
                            <span style="display:flex;align-items:center;gap:8px;">
                                <span style="font-size:9px;color:var(--text-dim);font-family:var(--font-mono);">${ageStr}</span>
                                <span style="font-size:9px;color:var(--text-muted);">👁 ${entry.hits}</span>
                            </span>
                        </div>
                        <div class="review-entry-detail" style="font-size:9px;padding:2px 6px;color:var(--text-muted);font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                            ${escapeHtml(entry.value_preview || '—')}
                        </div>
                    </div>
                `;
            });
        });

        html += '</div>';
        el.innerHTML = html;

        // Wire up click handlers for entry inspection
        el.querySelectorAll('.cache-entry-item').forEach(item => {
            item.addEventListener('click', () => {
                const key = item.dataset.key;
                if (key) {
                    // Highlight selected
                    el.querySelectorAll('.cache-entry-item').forEach(i => i.style.background = '');
                    item.style.background = 'var(--bg-elevated)';
                    this._loadEntryDetail(key);
                }
            });
        });
    },

    /** @private */
    _renderEntryDetail(detail, container) {
        if (!container) return;

        const tierColors = {
            HOT: 'var(--red-500)',
            WARM: 'var(--yellow-500)',
            COLD: 'var(--blue-500)',
        };
        const color = tierColors[detail.tier] || 'var(--text-primary)';
        const expiredLabel = detail.is_expired
            ? '<span class="status-tag" style="background:var(--red-500);color:white;">EXPIRED</span>'
            : '<span class="status-tag" style="background:var(--green-500);color:white;">ACTIVE</span>';

        const createdDate = new Date(detail.created_at).toLocaleTimeString();
        const expiresDate = new Date(detail.expires_at).toLocaleTimeString();
        const ageMin = Math.round(detail.age_s / 60);
        const ageSec = Math.round(detail.age_s % 60);

        // Format value display
        let valueHtml = '';
        try {
            const formatted = JSON.stringify(detail.value, null, 2);
            const lines = formatted.split('\n');
            const truncated = lines.length > 30
                ? lines.slice(0, 30).join('\n') + '\n... (truncated)'
                : formatted;
            valueHtml = `<pre style="font-size:9px;line-height:1.4;max-height:200px;overflow:auto;background:var(--bg-surface);border-radius:4px;padding:6px;margin:0;color:var(--text-secondary);white-space:pre-wrap;word-break:break-all;">${escapeHtml(truncated)}</pre>`;
        } catch (e) {
            valueHtml = `<div style="font-size:10px;color:var(--text-muted);">${escapeHtml(String(detail.value))}</div>`;
        }

        container.innerHTML = `
            <div style="border-left:3px solid ${color};padding-left:8px;margin-bottom:8px;">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                    <span class="mono" style="font-size:12px;font-weight:600;word-break:break-all;">${escapeHtml(detail.key)}</span>
                    ${expiredLabel}
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;">
                    <span class="status-tag" style="font-size:9px;background:${color}20;color:${color};">${detail.tier}</span>
                    <span style="font-size:9px;color:var(--text-dim);font-family:var(--font-mono);">🕐 ${ageMin}m ${ageSec}s old</span>
                    <span style="font-size:9px;color:var(--text-dim);font-family:var(--font-mono);">👁 ${detail.hits} hits</span>
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:8px;">
                <div class="panel-row" style="padding:2px 0;">
                    <span class="panel-label" style="font-size:9px;">Created</span>
                    <span class="panel-value mono" style="font-size:9px;">${createdDate}</span>
                </div>
                <div class="panel-row" style="padding:2px 0;">
                    <span class="panel-label" style="font-size:9px;">Expires</span>
                    <span class="panel-value mono" style="font-size:9px;">${expiresDate}</span>
                </div>
            </div>

            <div style="margin-bottom:6px;">
                <div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Value</div>
                ${valueHtml}
            </div>

            <button class="control-btn inv-key-btn" data-key="${escapeHtml(detail.key)}" style="width:100%;font-size:10px;padding:4px 10px;border-color:var(--red-500);color:var(--red-500);">
                🗑 Invalidate This Entry
            </button>
        `;

        // Wire up invalidation button
        const invBtn = container.querySelector('.inv-key-btn');
        if (invBtn) {
            invBtn.addEventListener('click', async () => {
                const key = invBtn.dataset.key;
                if (key) {
                    await this._invalidateKey(key);
                }
            });
        }
    },

    // ── Invalidation Actions ──

    /** @private */
    async _invalidateKey(key) {
        try {
            const result = await api.post('/api/debug/cache/invalidate', { key });
            if (result.removed) {
                this._logAction('Cache entry removed', key);
                // Reload data
                await this._loadAllData();
                // Reset detail view
                const detailEl = document.getElementById('cache-entry-detail');
                if (detailEl) {
                    detailEl.innerHTML = `
                        <div class="placeholder-message small" style="min-height:80px;">
                            <div class="placeholder-text">Entry invalidated — click another to inspect</div>
                        </div>
                    `;
                }
            }
        } catch (e) {
            this._logAction('Invalidation failed', e.message);
        }
    },

    /** @private */
    async _invalidateTier(tier) {
        try {
            const result = await api.post('/api/debug/cache/invalidate-tier', { tier });
            if (result.removed > 0) {
                this._logAction(`Cleared ${tier} tier`, `${result.removed} entries removed`);
            } else {
                this._logAction(`Cleared ${tier} tier`, 'No entries to remove');
            }
            await this._loadAllData();
        } catch (e) {
            this._logAction('Tier invalidation failed', e.message);
        }
    },

    /** @private */
    async _clearAll() {
        if (!confirm('⚠ Clear the entire session cache? This cannot be undone.')) return;

        try {
            const result = await api.post('/api/debug/cache/clear', {});
            this._logAction('Cache cleared', `${result.removed} entries removed`);
            await this._loadAllData();

            const detailEl = document.getElementById('cache-entry-detail');
            if (detailEl) {
                detailEl.innerHTML = `
                    <div class="placeholder-message small" style="min-height:80px;">
                        <div class="placeholder-text">Cache cleared — click an entry to inspect</div>
                    </div>
                `;
            }
        } catch (e) {
            this._logAction('Clear failed', e.message);
        }
    },

    // ── Action Log ──

    /** @private */
    _logAction(context, message) {
        // Show a brief toast-like feedback in the detail panel header
        const detailEl = document.getElementById('cache-entry-detail');
        if (detailEl) {        const toast = document.createElement('div');
        toast.style.cssText = `
                position:absolute;top:-4px;left:4px;right:4px;padding:5px 10px;
                background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:4px;
                font-size:10px;color:var(--text-secondary);z-index:10;
                animation: fadeIn 0.2s ease-out;
            `;
        toast.textContent = `✓ ${context}: ${message}`;
        const parent = detailEl.parentElement;
        if (parent) {
            parent.style.position = 'relative';
            parent.style.overflow = 'visible';
            parent.appendChild(toast);
            setTimeout(() => {
                if (toast.parentElement) toast.remove();
            }, 2500);
        }
        }
        console.log(`[SessionCache] ${context}:`, message);
    },

    // ── Polling ──

    /** @private */
    _startPolling() {
        if (this._polling) return;
        this._polling = true;
        this._pollLoop();
    },

    /** @private */
    _stopPolling() {
        this._polling = false;
        if (this._pollTimer) {
            clearTimeout(this._pollTimer);
            this._pollTimer = null;
        }
    },

    /** @private */
    async _pollLoop() {
        if (!this._polling || !this._container) return;

        await this._loadAllData();

        this._pollTimer = setTimeout(() => this._pollLoop(), 5000);
    },
};
