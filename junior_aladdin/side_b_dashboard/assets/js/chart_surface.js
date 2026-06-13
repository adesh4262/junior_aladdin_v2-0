/**
 * Junior Aladdin — Operator Terminal
 * chart_surface.js — Chart rendering surface
 *
 * Uses TradingView's Lightweight-Charts library for OHLCV candlestick
 * rendering with technical overlays (EMA, VWAP), SMC/ICT zones,
 * session markers, and timeframe switching.
 *
 * Chart ownership:
 *   - Floor 3 provides base render truth (OHLCV + indicators)
 *   - Floor 4 overlays contextual annotations (SMC zones)
 *   - Captain provides optional decision markers
 *
 * Reference: ROADMAP_SIDE_B Step 8.16
 * Library: https://www.tradingview.com/lightweight-charts/
 */

/* ── Import Lightweight-Charts (loaded via CDN in index.html) ── */
const LC = (typeof LightweightCharts !== 'undefined') ? LightweightCharts : null;

/* ── ChartSurface Component ── */

const ChartSurface = {
    /** @type {HTMLElement|null} */
    _container: null,

    /** @type {object|null} Chart instance */
    _chart: null,

    /** @type {object|null} Candlestick series */
    _candleSeries: null,

    /** @type {object|null} Line series for EMA 9 */
    _ema9Series: null,

    /** @type {object|null} Line series for EMA 21 */
    _ema21Series: null,

    /** @type {object|null} Line series for EMA 50 */
    _ema50Series: null,

    /** @type {object|null} Line series for VWAP */
    _vwapSeries: null,

    /** @type {object|null} Area series for premium/discount */
    _premiumSeries: null,

    /** @type {string} Current timeframe */
    _timeframe: '1m',

    /** @type {Array} Cached candle data */
    _candleData: [],

    /** @type {Array} Cached marker data */
    _markers: [],

    /** @type {object|null} Cached state for SMC zones */
    _smcZones: null,

    /** @type {boolean} Whether to show SMC overlays */
    _showSMC: true,

    /** @type {number} Resize observer handle */
    _resizeObserver: null,

    /** @type {Function|null} */
    _unsubscribe: null,

    /** @type {number|null} Animation frame handle */
    _rafHandle: null,

    /**
     * Mount the chart into a container.
     * @param {HTMLElement} container
     */
    mount(container) {
        if (!LC) {
            console.warn('[Chart] Lightweight-Charts library not loaded');
            container.innerHTML = `<div class="placeholder-message"><div class="placeholder-icon">📊</div><div class="placeholder-title">Chart Library Not Loaded</div><div class="placeholder-text">Lightweight-Charts library is unavailable. Check network connectivity.</div></div>`;
            return;
        }

        // Verify library API shape
        if (typeof LC.createChart !== 'function' || typeof LC.CandlestickSeries !== 'undefined' && typeof LC.CandlestickSeries !== 'function') {
            console.warn('[Chart] Lightweight-Charts API mismatch — expected v4.x');
        }

        this._container = container;

        try {
            this._createChart();
            this._createSeries();
        } catch (e) {
            console.error('[Chart] Failed to initialize chart:', e);
            container.innerHTML = `<div class="placeholder-message"><div class="placeholder-icon">📊</div><div class="placeholder-title">Chart Initialization Error</div><div class="placeholder-text">${e.message || 'Unknown error'}</div></div>`;
            return;
        }

        // Subscribe to market data (LTP) updates for real-time tick streaming
        this._unsubscribe = StateManager.subscribe('market', (market) => {
            if (market) this._onMarketUpdate(market);
        });

        // Subscribe to chart-specific data (candles + overlays)
        this._chartUnsub = StateManager.subscribe('chartData', (data) => {
            if (data) this._onChartData(data);
        });

        // Handle resize
        this._setupResizeObserver();

        // Fetch initial chart data from backend
        this._fetchInitialData();
    },

    /** @private */
    async _fetchInitialData() {
        try {
            const chartData = await api.getMarketChart();
            if (chartData && (chartData.candles || chartData.ohlcv || chartData.chart)) {
                this._onChartData(chartData);
            } else {
                // No real data — generate sample for visual testing
                console.log('[Chart] No backend chart data, using sample data');
                this._generateSampleData();
            }
        } catch (e) {
            console.warn('[Chart] Failed to fetch initial data:', e);
            // Generate sample data for visual testing
            this._generateSampleData();
        }
    },

    /**
     * Generate sample OHLCV data for visual testing when backend data is unavailable.
     * @private
     */
    _generateSampleData() {
        const now = Math.floor(Date.now() / 1000);
        const interval = 60; // 1 minute
        const count = 120; // 120 candles = 2 hours
        const basePrice = 17500;
        const candles = [];
        const ema9 = [];
        const ema21 = [];

        let price = basePrice;
        for (let i = count - 1; i >= 0; i--) {
            const time = now - i * interval;
            const change = (Math.random() - 0.5) * 30;
            const open = price;
            const close = price + change;
            const high = Math.max(open, close) + Math.random() * 15;
            const low = Math.min(open, close) - Math.random() * 15;
            const volume = Math.floor(Math.random() * 100000) + 10000;

            candles.push({ time, open, high, low, close, volume });
            price = close;

            // Simple SMA as EMA proxy for sample data
            if (i <= count - 9) {
                const slice = candles.slice(-9);
                ema9.push({ time, value: slice.reduce((s, c) => s + c.close, 0) / slice.length });
            }
            if (i <= count - 21) {
                const slice = candles.slice(-21);
                ema21.push({ time, value: slice.reduce((s, c) => s + c.close, 0) / slice.length });
            }
        }

        this.setCandleData(candles, {
            ema9: ema9,
            ema21: ema21,
        });
    },

    /** Unmount and clean up */
    unmount() {
        if (this._unsubscribe) this._unsubscribe();
        if (this._chartUnsub) this._chartUnsub();
        if (this._resizeObserver) this._resizeObserver.disconnect();
        if (this._chart) {
            this._chart.remove();
            this._chart = null;
        }
        this._container = null;
    },

    /**
     * Update with new data.
     * @param {object} state
     */
    update(state) {
        if (state && this._chart) {
            // Handle partial data updates
            if (state.ltp) this._updatePrice(state);
        }
    },

    // ── Chart Creation ──

    /** @private */
    _createChart() {
        const container = this._container;
        const rect = container.getBoundingClientRect();
        const width = rect.width || 600;
        const height = Math.max(400, Math.min(600, window.innerHeight * 0.45));

        // Dark terminal theme colors
        const bgColor = '#0a0e17';
        const textColor = '#9ca3af';
        const gridColor = '#1a1f2e';
        const borderColor = '#1f2937';
        const crosshairColor = '#3b82f6';

        this._chart = LC.createChart(container, {
            width: width,
            height: height,
            layout: {
                background: { type: 'solid', color: bgColor },
                textColor: textColor,
                fontFamily: "'JetBrains Mono', 'Inter', monospace",
                fontSize: 10,
            },
            grid: {
                vertLines: { color: gridColor, style: 1 },
                horzLines: { color: gridColor, style: 1 },
            },
            crosshair: {
                mode: 0,
                vertLine: {
                    color: crosshairColor,
                    width: 1,
                    style: 2,
                    labelBackgroundColor: crosshairColor,
                },
                horzLine: {
                    color: crosshairColor,
                    width: 1,
                    style: 2,
                    labelBackgroundColor: crosshairColor,
                },
            },
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: borderColor,
                borderVisible: true,
                tickMarkFormatter: (time) => {
                    const date = new Date(time * 1000);
                    const h = String(date.getHours()).padStart(2, '0');
                    const m = String(date.getMinutes()).padStart(2, '0');
                    return `${h}:${m}`;
                },
            },
            rightPriceScale: {
                borderColor: borderColor,
                borderVisible: true,
                scaleMargins: { top: 0.05, bottom: 0.1 },
            },
            leftPriceScale: {
                visible: false,
            },
            handleScroll: { vertTouchDrag: true, horzTouchDrag: true },
            handleScale: { axisPressedMouseMove: true },
        });

        // Apply initial timeframe
        this._chart.timeScale().applyOptions({
            barSpacing: this._timeframe === '1m' ? 6 : this._timeframe === '5m' ? 10 : 15,
        });
    },

    /** @private */
    _createSeries() {
        if (!this._chart) return;

        // ── Candlestick series ──
        this._candleSeries = this._chart.addCandlestickSeries({
            upColor: '#22c55e',
            downColor: '#ef4444',
            borderUpColor: '#22c55e',
            borderDownColor: '#ef4444',
            wickUpColor: '#22c55e',
            wickDownColor: '#ef4444',
            priceFormat: {
                type: 'price',
                precision: 2,
                minMove: 0.05,
            },
        });

        // ── EMA 9 (fast) ──
        this._ema9Series = this._chart.addLineSeries({
            color: '#3b82f6',
            lineWidth: 1,
            title: 'EMA 9',
            priceLineVisible: false,
            lastValueVisible: true,
            priceFormat: { type: 'price', precision: 2, minMove: 0.05 },
        });

        // ── EMA 21 (medium) ──
        this._ema21Series = this._chart.addLineSeries({
            color: '#f59e0b',
            lineWidth: 1,
            title: 'EMA 21',
            priceLineVisible: false,
            lastValueVisible: true,
            priceFormat: { type: 'price', precision: 2, minMove: 0.05 },
        });

        // ── EMA 50 (slow) ──
        this._ema50Series = this._chart.addLineSeries({
            color: '#8b5cf6',
            lineWidth: 1,
            lineStyle: 2, // Dashed
            title: 'EMA 50',
            priceLineVisible: false,
            lastValueVisible: true,
            priceFormat: { type: 'price', precision: 2, minMove: 0.05 },
        });

        // ── VWAP ──
        this._vwapSeries = this._chart.addLineSeries({
            color: '#06b6d4',
            lineWidth: 1,
            title: 'VWAP',
            priceLineVisible: false,
            lastValueVisible: true,
            priceFormat: { type: 'price', precision: 2, minMove: 0.05 },
        });
    },

    // ── Data Pipeline ──

    /**
     * Set full OHLCV candle data.
     * @param {Array} candles - Array of { time, open, high, low, close, volume }
     * @param {object} [overlays] - { ema9?, ema21?, ema50?, vwap? }
     * @param {Array} [markers] - Chart markers
     */
    setCandleData(candles, overlays, markers) {
        if (!this._candleSeries) return;

        this._candleData = candles || [];

        // Set candlestick data
        if (candles && candles.length > 0) {
            this._candleSeries.setData(candles);
        }

        // Set overlays
        if (overlays) {
            // Convert EMA/VWAP data points to { time, value } format
            const toLineData = (arr) => (arr || []).map(p => ({
                time: p.time,
                value: p.value,
            }));

            if (overlays.ema9 && this._ema9Series) {
                this._ema9Series.setData(toLineData(overlays.ema9));
            }
            if (overlays.ema21 && this._ema21Series) {
                this._ema21Series.setData(toLineData(overlays.ema21));
            }
            if (overlays.ema50 && this._ema50Series) {
                this._ema50Series.setData(toLineData(overlays.ema50));
            }
            if (overlays.vwap && this._vwapSeries) {
                this._vwapSeries.setData(toLineData(overlays.vwap));
            }
        }

        // Set markers (entry, exit, SL, TGT)
        if (markers && markers.length > 0 && this._candleSeries) {
            this._candleSeries.setMarkers(markers);
        }

        // Fit content to show all data
        this._chart.timeScale().fitContent();
    },

    /**
     * Update the last candle with new tick data (real-time streaming).
     * @param {number} time - Unix timestamp (seconds)
     * @param {number} price - Current price
     */
    updateTick(time, price) {
        if (!this._candleSeries || !this._candleData || this._candleData.length === 0) return;

        const lastCandle = this._candleData[this._candleData.length - 1];
        if (!lastCandle) return;

        // Update last candle
        const updatedCandle = {
            ...lastCandle,
            time: time,
            close: price,
            high: Math.max(lastCandle.high, price),
            low: Math.min(lastCandle.low, price),
        };

        this._candleSeries.update(updatedCandle);
        this._candleData[this._candleData.length - 1] = updatedCandle;
    },

    /** @private */
    _onMarketUpdate(market) {
        if (!market.ltp || !this._chart) return;

        // Update last candle with current LTP
        const now = Math.floor(Date.now() / 1000);
        this.updateTick(now, market.ltp);
    },

    /** @private */
    _onChartData(data) {
        if (!data) return;

        const candles = data.candles || data.ohlcv || data.chart || null;
        const overlays = data.overlays || data.indicators || null;
        const markers = data.markers || null;
        const smcZones = data.smc_zones || data.orderBlocks || null;

        if (candles) {
            this.setCandleData(candles, overlays, markers);
        }

        if (smcZones && this._showSMC) {
            this._smcZones = smcZones;
            this._renderSMCZones(smcZones);
        }
    },

    /** @private */
    _updatePrice(market) {
        // Price update only — called from HOT poll
        const now = Math.floor(Date.now() / 1000);
        this.updateTick(now, market.ltp || 0);
    },

    // ── SMC/ICT Zone Rendering ──

    /** @private */
    _renderSMCZones(zones) {
        if (!this._chart || !zones) return;

        // SMC zones are rendered as price markers / horizontal lines
        // using chart.addLineSeries or price line markers

        const orderBlocks = zones.orderBlocks || [];
        const fvgs = zones.fvgs || [];
        const liquidity = zones.liquidity || [];

        // Clear previous zone markers by re-creating series
        // (we use a single series for zones for simplicity)
        if (this._zoneSeries) {
            this._chart.removeSeries(this._zoneSeries);
        }

        // Collect zone levels as markers
        const zoneMarkers = [];

        // Order blocks
        orderBlocks.forEach((ob, i) => {
            zoneMarkers.push({
                time: ob.time || 0,
                position: ob.type === 'bullish' ? 'belowBar' : 'aboveBar',
                color: ob.type === 'bullish' ? '#22c55e' : '#ef4444',
                shape: ob.type === 'bullish' ? 'arrowUp' : 'arrowDown',
                text: `OB ${i + 1}`,
                size: 0.5,
            });
        });

        // FVGs
        fvgs.forEach((fvg, i) => {
            zoneMarkers.push({
                time: fvg.time || 0,
                position: 'inBar',
                color: '#8b5cf6',
                shape: 'circle',
                text: `FVG ${i + 1}`,
                size: 0.5,
            });
        });

        // Liquidity levels
        liquidity.forEach((liq, i) => {
            zoneMarkers.push({
                time: liq.time || 0,
                position: liq.type === 'buy' ? 'belowBar' : 'aboveBar',
                color: '#f59e0b',
                shape: liq.type === 'buy' ? 'arrowUp' : 'arrowDown',
                text: `Liq ${i + 1}`,
                size: 0.5,
            });
        });

        // Apply zone markers
        if (zoneMarkers.length > 0 && this._candleSeries) {
            const existing = [];
            try { existing = this._candleSeries._markers || []; } catch(e) {}
            this._candleSeries.setMarkers([...existing, ...zoneMarkers]);
        }
    },

    // ── Price Axis Markers ──

    // ── Timeframe Switching ──

    /**
     * Switch the chart timeframe.
     * @param {'1m'|'5m'|'15m'|'1h'|'1d'} timeframe
     */
    setTimeframe(timeframe) {
        const allowed = ['1m', '5m', '15m', '1h', '1d'];
        if (!allowed.includes(timeframe)) {
            console.warn(`[Chart] Invalid timeframe: ${timeframe}`);
            return;
        }

        this._timeframe = timeframe;

        // Adjust bar spacing based on timeframe
        const spacingMap = { '1m': 6, '5m': 10, '15m': 15, '1h': 25, '1d': 40 };
        if (this._chart) {
            this._chart.timeScale().applyOptions({
                barSpacing: spacingMap[timeframe] || 10,
            });
        }

        // Emit timeframe change (data source can reload)
        StateManager.set('chartTimeframe', timeframe);
    },

    /** Get current timeframe */
    getTimeframe() {
        return this._timeframe;
    },

    /** Toggle SMC overlay visibility */
    toggleSMC() {
        this._showSMC = !this._showSMC;
        if (this._showSMC && this._smcZones) {
            this._renderSMCZones(this._smcZones);
        }
        return this._showSMC;
    },

    // ── Resize Handling ──

    /** @private */
    _setupResizeObserver() {
        if (!this._container || !this._chart) return;

        this._resizeObserver = new ResizeObserver((entries) => {
            if (this._rafHandle) cancelAnimationFrame(this._rafHandle);
            this._rafHandle = requestAnimationFrame(() => {
                for (const entry of entries) {
                    const { width, height } = entry.contentRect;
                    if (this._chart) {
                        this._chart.applyOptions({
                            width: Math.floor(width),
                            height: Math.max(350, Math.min(550, height)),
                        });
                    }
                }
            });
        });

        this._resizeObserver.observe(this._container);
    },

    // ── Price Axis Markers ──

    /**
     * Add a horizontal price line (e.g., for SL, TGT, key levels).
     * @param {number} price
     * @param {string} color
     * @param {string} title
     * @param {string} position - 'left' or 'right'
     */
    addPriceLine(price, color = '#9ca3af', title = '', position = 'right') {
        if (!this._candleSeries) return;
        this._candleSeries.createPriceLine({
            price: price,
            color: color,
            lineWidth: 1,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: title,
        });
    },

    /**
     * Clear all price lines.
     * Lightweight-Charts doesn't expose a bulk-remove API for price lines.
     * Store references on add and remove individually in future iterations.
     */
    clearPriceLines() {
        // Not implemented — Lightweight-Charts has no bulk price line removal API
    },
};

// Register with ComponentManager
ComponentManager.register('chart', ChartSurface);
