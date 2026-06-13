/**
 * Junior Aladdin — Operator Terminal
 * workspace_replay.js — Replay Workspace
 *
 * READ-ONLY replay workspace with playback controls, timeline,
 * session selector, and live data stream viewer.
 *
 * Reference: ROADMAP_SIDE_B Step 8.19
 */

const WorkspaceReplay = {
    /** @type {HTMLElement|null} */
    _container: null,

    /** @type {object} Current replay state */
    _state: {
        active: false,
        session_id: null,
        status: 'STOPPED',
        speed: 1.0,
        sessions: [],
        data: [],
    },

    /** @type {boolean} Polling active */
    _polling: false,

    /** @type {number} Poll timer ID */
    _pollTimer: null,

    /** Allowed speeds */
    _speeds: [0.5, 1.0, 2.0, 5.0, 10.0],

    /** @type {Function|null} State subscription */
    _stateUnsub: null,

    /** @type {number|null} Progress simulation timer */
    _progressTimer: null,

    /** @type {number} Simulated progress 0.0–1.0 */
    _progress: 0,

    /**
     * Render the replay workspace into a container.
     * @param {HTMLElement} container
     */
    render(container) {
        this._container = container;
        this._renderLayout();
        this._loadSessions();
        this._pollState(); // immediate first poll
        this._startPolling();

        // Subscribe to state changes for reactive updates
        this._stateUnsub = StateManager.subscribe('replay', (replay) => {
            if (replay && this._container) {
                this._updateFromState(replay);
            }
        });
    },

    /** Unmount and clean up */
    unmount() {
        this._stopPolling();
        this._stopProgressSim();
        if (this._stateUnsub) {
            this._stateUnsub();
            this._stateUnsub = null;
        }
        if (this._keyboardHandler) {
            document.removeEventListener('keydown', this._keyboardHandler);
            this._keyboardHandler = null;
        }
        this._container = null;
    },

    // ── Layout ──

    /** @private */
    _renderLayout() {
        if (!this._container) return;

        this._container.innerHTML = `
            <!-- ═══ READ-ONLY Banner ═══ -->
            <div class="replay-readonly-banner" id="replay-readonly-banner">
                <span class="replay-readonly-icon">🔒</span>
                <span class="replay-readonly-text">REPLAY MODE — READ-ONLY. No execution commands accepted.</span>
            </div>

            <div class="replay-layout">
                <!-- Left: Controls + Timeline -->
                <div class="replay-main">
                    <!-- Session Selector -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">↺ Replay Session</span>
                            <span class="panel-card-badge refresh-cold">COLD</span>
                        </div>
                        <div class="panel-card-body">
                            <div class="replay-session-selector">
                                <select class="replay-select" id="replay-session-select">
                                    <option value="">— Select a session —</option>
                                </select>
                                <button class="replay-btn replay-btn-primary" id="replay-start-btn" disabled>
                                    ▶ Start
                                </button>
                                <button class="replay-btn replay-btn-danger" id="replay-stop-btn" disabled>
                                    ⏹ Stop
                                </button>
                            </div>
                            <div class="replay-session-info" id="replay-session-info">
                                <span class="panel-label">No session selected</span>
                            </div>
                        </div>
                    </div>

                    <!-- Playback Controls -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">▶ Playback Controls</span>
                            <span class="panel-card-badge" id="replay-status-badge">STOPPED</span>
                        </div>
                        <div class="panel-card-body">
                            <div class="replay-controls">
                                <button class="replay-btn replay-btn-play" id="replay-play-btn" disabled title="Play / Pause">
                                    ▶
                                </button>
                                <button class="replay-btn" id="replay-stop-btn2" disabled title="Stop">
                                    ⏹
                                </button>
                                <div class="replay-speed-group">
                                    <span class="panel-label" style="font-size:10px;">Speed</span>
                                    <div class="replay-speed-btns" id="replay-speed-btns">
                                        ${this._speeds.map(s => `
                                            <button class="replay-speed-btn ${s === 1.0 ? 'active' : ''}"
                                                    data-speed="${s}">${s}×</button>
                                        `).join('')}
                                    </div>
                                </div>
                            </div>

                            <!-- Timeline -->
                            <div class="replay-timeline" id="replay-timeline">
                                <div class="replay-timeline-track">
                                    <div class="replay-timeline-fill" id="replay-timeline-fill" style="width:0%"></div>
                                    <div class="replay-timeline-thumb" id="replay-timeline-thumb" style="left:0%"></div>
                                </div>
                                <div class="replay-timeline-labels">
                                    <span class="panel-label" id="replay-time-elapsed">00:00:00</span>
                                    <span class="panel-label" id="replay-time-remaining">00:00:00</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Data Stream -->
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">📡 Data Stream</span>
                            <span class="panel-card-badge" id="replay-data-count">0 events</span>
                        </div>
                        <div class="panel-card-body replay-data-stream" id="replay-data-stream">
                            <div class="placeholder-message small">
                                <div class="placeholder-text">Start a replay session to view data</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Right: Session Details -->
                <div class="replay-sidebar">
                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">ℹ Session Details</span>
                        </div>
                        <div class="panel-card-body" id="replay-details">
                            <div class="replay-detail-row">
                                <span class="panel-label">Status</span>
                                <span class="panel-value" id="replay-detail-status">STOPPED</span>
                            </div>
                            <div class="replay-detail-row">
                                <span class="panel-label">Session ID</span>
                                <span class="panel-value mono" id="replay-detail-session">—</span>
                            </div>
                            <div class="replay-detail-row">
                                <span class="panel-label">Speed</span>
                                <span class="panel-value mono" id="replay-detail-speed">1.0×</span>
                            </div>
                            <div class="replay-detail-row">
                                <span class="panel-label">Start Time</span>
                                <span class="panel-value" id="replay-detail-start">—</span>
                            </div>
                            <div class="replay-detail-row">
                                <span class="panel-label">End Time</span>
                                <span class="panel-value" id="replay-detail-end">—</span>
                            </div>
                            <div class="replay-detail-row">
                                <span class="panel-label">Data Points</span>
                                <span class="panel-value mono" id="replay-detail-points">0</span>
                            </div>
                            <div class="replay-detail-row" style="border-top:1px solid var(--border-subtle);padding-top:6px;margin-top:4px;">
                                <span class="panel-label">Read-Only</span>
                                <span class="panel-value" style="color:var(--yellow-500);font-weight:600;">🔒 Yes</span>
                            </div>
                        </div>
                    </div>

                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⚡ Quick Actions</span>
                        </div>
                        <div class="panel-card-body">
                            <button class="replay-btn replay-btn-primary" style="width:100%;margin-bottom:6px;" id="replay-quick-start">
                                ▶ Quick Start Latest
                            </button>
                            <button class="replay-btn replay-btn-danger" style="width:100%;" id="replay-quick-stop">
                                ⏹ Stop Replay
                            </button>
                        </div>
                    </div>

                    <div class="panel-card">
                        <div class="panel-card-header">
                            <span class="panel-card-title">⌨ Shortcuts</span>
                        </div>
                        <div class="panel-card-body">
                            <div class="replay-shortcut"><kbd>Space</kbd> Play / Pause</div>
                            <div class="replay-shortcut"><kbd>←</kbd> <kbd>→</kbd> Step backward / forward</div>
                            <div class="replay-shortcut"><kbd>S</kbd> Stop</div>
                            <div class="replay-shortcut"><kbd>1</kbd> 0.5×  <kbd>2</kbd> 1×  <kbd>3</kbd> 2×  <kbd>4</kbd> 5×  <kbd>5</kbd> 10×</div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this._wireEvents();
        this._wireKeyboard();
    },

    // ── Event Wiring ──

    /** @private */
    _wireEvents() {
        // Session select
        const select = document.getElementById('replay-session-select');
        if (select) {
            select.addEventListener('change', () => this._onSessionSelect(select.value));
        }

        // Start/Stop buttons
        const startBtn = document.getElementById('replay-start-btn');
        if (startBtn) startBtn.addEventListener('click', () => this._startReplay());

        const stopBtn = document.getElementById('replay-stop-btn');
        if (stopBtn) stopBtn.addEventListener('click', () => this._stopReplay());

        // Playback
        const playBtn = document.getElementById('replay-play-btn');
        if (playBtn) playBtn.addEventListener('click', () => this._togglePlayback());

        const stopBtn2 = document.getElementById('replay-stop-btn2');
        if (stopBtn2) stopBtn2.addEventListener('click', () => this._stopReplay());

        // Speed buttons
        const speedBtns = document.getElementById('replay-speed-btns');
        if (speedBtns) {
            speedBtns.addEventListener('click', (e) => {
                const btn = e.target.closest('.replay-speed-btn');
                if (btn) {
                    const speed = parseFloat(btn.dataset.speed);
                    this._setSpeed(speed);
                }
            });
        }

        // Quick actions
        const quickStart = document.getElementById('replay-quick-start');
        if (quickStart) quickStart.addEventListener('click', () => this._quickStart());

        const quickStop = document.getElementById('replay-quick-stop');
        if (quickStop) quickStop.addEventListener('click', () => this._stopReplay());
    },

    /** @private */
    _wireKeyboard() {
        const handler = (e) => {
            // Only handle if replay workspace is visible and container exists
            if (!this._container || !this._container.isConnected) return;

            // Don't handle if user is typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;

            switch (e.key) {
                case ' ':
                    e.preventDefault();
                    this._togglePlayback();
                    break;
                case 's':
                case 'S':
                    this._stopReplay();
                    break;
                case '1': this._setSpeed(0.5); break;
                case '2': this._setSpeed(1.0); break;
                case '3': this._setSpeed(2.0); break;
                case '4': this._setSpeed(5.0); break;
                case '5': this._setSpeed(10.0); break;
            }
        };

        // Store for cleanup — use same reference for add/remove
        this._keyboardHandler = handler;
        document.addEventListener('keydown', handler);
    },

    // ── Session Loading ──

    /** @private */
    async _loadSessions() {
        const select = document.getElementById('replay-session-select');
        if (!select) return;

        try {
            select.innerHTML = '<option value="">— Loading sessions... —</option>';
            const result = await api.getReplaySessions();
            const sessions = result.sessions || [];

            select.innerHTML = '<option value="">— Select a session —</option>';
            sessions.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s.session_id || 'unknown';
                opt.textContent = `${s.session_id || 'Unknown'} (${s.status || 'AVAILABLE'})`;
                select.appendChild(opt);
            });

            // Enable start if sessions available
            const startBtn = document.getElementById('replay-start-btn');
            if (startBtn) startBtn.disabled = sessions.length === 0;

            // Update session info
            const info = document.getElementById('replay-session-info');
            if (info) {
                info.innerHTML = `
                    <span class="panel-label">Available Sessions</span>
                    <span class="panel-value mono">${result.count || sessions.length}</span>
                `;
            }

            this._state.sessions = sessions;

            // If there's an active session from the server, show it
            if (result.active_session) {
                select.value = result.active_session;
                this._state.session_id = result.active_session;
                this._updateControls(true);
            }
        } catch (e) {
            console.warn('[Replay] Failed to load sessions:', e);
            select.innerHTML = '<option value="">— Failed to load —</option>';
            // Show retry in session info
            const info = document.getElementById('replay-session-info');
            if (info) {
                info.innerHTML = `
                    <span class="panel-label" style="color:var(--red-500);">⚠ Failed to load</span>
                    <button class="replay-btn" onclick="WorkspaceReplay._loadSessions()" style="font-size:10px;padding:2px 8px;">↻ Retry</button>
                `;
            }
        }
    },

    /** @private */
    _onSessionSelect(sessionId) {
        const startBtn = document.getElementById('replay-start-btn');
        if (startBtn) startBtn.disabled = !sessionId;

        const info = document.getElementById('replay-session-info');
        if (info && sessionId) {
            const session = this._state.sessions.find(s => s.session_id === sessionId);
            if (session) {
                info.innerHTML = `
                    <span class="panel-label">Session</span>
                    <span class="panel-value mono">${this._escapeHtml(sessionId)}</span>
                    <span class="status-tag ${(session.source || '').toLowerCase().replace(/\s/g, '-')}">${this._escapeHtml(session.source || '—')}</span>
                `;
            }
        }
    },

    // ── Playback Controls ──

    /** @private */
    async _startReplay() {
        const select = document.getElementById('replay-session-select');
        const sessionId = select ? select.value : null;
        if (!sessionId) {
            this._showError('Please select a session first');
            return;
        }

        try {
            const result = await api.startReplay({ session_id: sessionId, speed: this._state.speed });
            this._updateFromState(result);
            this._updateControls(true);
            this._updatePlayBtn(true);
            this._updateTimeline(0);
            this._startProgressSim();
            this._pollState(); // immediate poll
        } catch (e) {
            console.warn('[Replay] Start failed:', e);
            this._showError('Failed to start replay: ' + (e.message || 'Unknown error'));
        }
    },

    /** @private */
    async _stopReplay() {
        try {
            const result = await api.stopReplay();
            this._updateFromState(result);
            this._updateControls(false);
            this._updatePlayBtn(false);
            this._stopProgressSim();
        } catch (e) {
            console.warn('[Replay] Stop failed:', e);
        }
    },

    /** @private */
    async _togglePlayback() {
        const status = this._state.status;
        if (status === 'PLAYING') {
            // Stop replay (no dedicated pause API)
            await this._stopReplay();
        } else if (status === 'STOPPED' && this._state.session_id) {
            // Start from stopped
            await this._startReplay();
        }
    },

    /** @private */
    async _setSpeed(speed) {
        // Update UI immediately
        document.querySelectorAll('.replay-speed-btn').forEach(btn => {
            btn.classList.toggle('active', parseFloat(btn.dataset.speed) === speed);
        });
        this._state.speed = speed;

        // If active, send to server
        if (this._state.active) {
            try {
                await api.setReplaySpeed(speed);
            } catch (e) {
                console.warn('[Replay] Speed set failed:', e);
            }
        }
    },

    /** @private */
    async _quickStart() {
        try {
            const result = await api.getReplaySessions();
            const sessions = result.sessions || [];
            if (sessions.length === 0) {
                this._showError('No replay sessions available');
                return;
            }

            const latest = sessions[0];
            const result2 = await api.startReplay({
                session_id: latest.session_id,
                speed: this._state.speed,
            });
            this._updateFromState(result2);
            this._updateControls(true);
            this._updatePlayBtn(true);

            // Select in dropdown
            const select = document.getElementById('replay-session-select');
            if (select) {
                select.value = latest.session_id;
                this._onSessionSelect(latest.session_id);
            }
        } catch (e) {
            console.warn('[Replay] Quick start failed:', e);
            this._showError('Quick start failed: ' + (e.message || 'Unknown error'));
        }
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

        await this._pollState();
        await this._pollData();

        this._pollTimer = setTimeout(() => this._pollLoop(), 3000);
    },

    /** @private */
    async _pollState() {
        try {
            const state = await api.getReplayState();
            StateManager.set('replay', state);
            this._updateFromState(state);
        } catch (e) {
            // Silently retry next cycle
        }
    },

    /** @private */
    async _pollData() {
        if (!this._state.active) return;

        try {
            const data = await api.getReplayData();
            if (data && data.data) {
                this._state.data = data.data || [];
                this._renderDataStream();
            }
        } catch (e) {
            // Silently retry next cycle
        }
    },

    // ── UI Updates ──

    /** @private */
    _updateFromState(state) {
        if (!state) return;

        this._state.active = state.active || false;
        this._state.status = state.status || 'STOPPED';
        this._state.session_id = state.session_id || this._state.session_id;
        this._state.speed = state.speed ?? this._state.speed;

        // Status badge
        const badge = document.getElementById('replay-status-badge');
        if (badge) {
            badge.textContent = state.status || 'STOPPED';
            const statusClass = (state.status || '').toLowerCase();
            badge.className = `panel-card-badge replay-status-${statusClass}`;
        }

        // Update speed buttons to match server state
        this._updateSpeedButtons(this._state.speed);

        // Detail panel
        this._updateDetails(state);

        // Controls state
        const isActive = state.active && state.status === 'PLAYING';
        this._updateControls(state.active);
        this._updatePlayBtn(isActive);

        // Sync progress simulation with active state
        if (isActive && !this._progressTimer) {
            this._startProgressSim();
        } else if (!isActive && this._progressTimer) {
            this._stopProgressSim();
        }
    },

    /** @private */
    _updateDetails(state) {
        const setText = (id, text) => {
            const el = document.getElementById(id);
            if (el) el.textContent = text;
        };

        setText('replay-detail-status', state.status || 'STOPPED');
        setText('replay-detail-session', state.session_id || '—');
        setText('replay-detail-speed', (state.speed ?? 1.0) + '×');
        setText('replay-detail-start', state.start_time ? this._formatTime(state.start_time) : '—');
        setText('replay-detail-end', state.end_time ? this._formatTime(state.end_time) : '—');
        setText('replay-detail-points', this._state.data.length.toString());
    },

    /** @private */
    _updateControls(active) {
        const startBtn = document.getElementById('replay-start-btn');
        const stopBtn = document.getElementById('replay-stop-btn');
        const stopBtn2 = document.getElementById('replay-stop-btn2');
        const playBtn = document.getElementById('replay-play-btn');

        if (startBtn) startBtn.disabled = active;
        if (stopBtn) stopBtn.disabled = !active;
        if (stopBtn2) stopBtn2.disabled = !active;
        if (playBtn) playBtn.disabled = !active;
    },

    /** @private */
    _updatePlayBtn(playing) {
        const playBtn = document.getElementById('replay-play-btn');
        if (playBtn) {
            playBtn.textContent = playing ? '⏸' : '▶';
            playBtn.title = playing ? 'Pause' : 'Play';
        }
    },

    // ── Timeline & Progress ──

    /** @private */
    _updateTimeline(progress) {
        // Clamp 0..1
        const p = Math.max(0, Math.min(1, progress));
        this._progress = p;

        const fill = document.getElementById('replay-timeline-fill');
        const thumb = document.getElementById('replay-timeline-thumb');
        const elapsed = document.getElementById('replay-time-elapsed');
        const remaining = document.getElementById('replay-time-remaining');

        if (fill) fill.style.width = (p * 100) + '%';
        if (thumb) thumb.style.left = (p * 100) + '%';

        // Format timestamps (simulate 60-min session for display)
        const totalSec = 3600; // 1 hour virtual session
        const elapsedSec = Math.round(p * totalSec);
        const remainingSec = Math.round((1 - p) * totalSec);

        const fmt = (s) => {
            const h = String(Math.floor(s / 3600)).padStart(2, '0');
            const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
            const sec = String(s % 60).padStart(2, '0');
            return `${h}:${m}:${sec}`;
        };

        if (elapsed) elapsed.textContent = fmt(elapsedSec);
        if (remaining) remaining.textContent = '-' + fmt(remainingSec);

        // Add status pulse when active
        const badge = document.getElementById('replay-status-badge');
        if (badge) {
            badge.classList.toggle('status-pulse', this._state.active);
        }
    },

    /** @private */
    _startProgressSim() {
        if (this._progressTimer) return;

        this._progressTimer = setInterval(() => {
            if (!this._state.active || this._state.status !== 'PLAYING') {
                this._stopProgressSim();
                return;
            }

            // Advance progress: ~0.5% per tick at 1× speed, scaled by actual speed
            const increment = (0.005 * this._state.speed);
            const newProgress = Math.min(1, this._progress + increment);
            this._updateTimeline(newProgress);

            // Loop when complete
            if (newProgress >= 1) {
                this._updateTimeline(0);
            }
        }, 100);
    },

    /** @private */
    _stopProgressSim() {
        if (this._progressTimer) {
            clearInterval(this._progressTimer);
            this._progressTimer = null;
        }
        this._updateTimeline(0);
    },

    // ── Speed Button Highlight ──

    /** @private */
    _updateSpeedButtons(speed) {
        document.querySelectorAll('.replay-speed-btn').forEach(btn => {
            btn.classList.toggle('active', parseFloat(btn.dataset.speed) === speed);
        });
    },

    // ── Data Stream ──

    /** @private */
    _renderDataStream() {
        const stream = document.getElementById('replay-data-stream');
        const countEl = document.getElementById('replay-data-count');
        if (!stream) return;

        const data = this._state.data;
        if (countEl) countEl.textContent = `${data.length} events`;

        if (data.length === 0) {
            stream.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text">No data received yet</div>
                </div>
            `;
            return;
        }

        let html = '<div class="replay-data-list">';
        data.forEach((item, idx) => {
            const timestamp = item.timestamp || item.time || '—';
            const label = item.label || item.type || item.event || `Event ${idx + 1}`;
            const value = item.value != null ? item.value : '';
            const severity = (item.severity || '').toLowerCase();

            html += `
                <div class="replay-data-item ${severity ? `severity-${severity}` : ''} entry-enter">
                    <span class="replay-data-idx">#${idx + 1}</span>
                    <span class="replay-data-label">${this._escapeHtml(label)}</span>
                    <span class="replay-data-value mono">${this._escapeHtml(String(value))}</span>
                    <span class="replay-data-time">${this._escapeHtml(timestamp)}</span>
                </div>
            `;
        });
        html += '</div>';

        stream.innerHTML = html;

        // Auto-scroll to bottom
        stream.scrollTop = stream.scrollHeight;
    },

    /** @private */
    _showError(msg) {
        const stream = document.getElementById('replay-data-stream');
        if (stream) {
            stream.innerHTML = `
                <div class="placeholder-message small">
                    <div class="placeholder-text" style="color:var(--red-500);">⚠ ${this._escapeHtml(msg)}</div>
                </div>
            `;
        }
    },

    // ── Helpers ──

    /** @private */
    _formatTime(isoStr) {
        if (!isoStr) return '—';
        try {
            const d = new Date(isoStr);
            return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch (e) {
            return isoStr;
        }
    },

    /** @private */
    _escapeHtml(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    },
};
