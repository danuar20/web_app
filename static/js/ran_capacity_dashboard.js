/**
 * RAN Capacity Dashboard JavaScript
 * OKR RAN Capacity Monitoring Dashboard (RCI & Unbalance):
 *   1. Dual-metric architecture with independent per-section and global toggles
 *   2. ECharts Macro Combo Charts, Transition Flows, Behavioral Donut, Version Breakdown
 *   3. 1D Benchmark Slider Track with Anti-Collision Branch Markers & Companion Stat Row
 *   4. Multi-tab Navigation (Achievement, Trend & Regional, Sector/Kabupaten Table)
 *   5. Data Import & Template Download
 */

(function () {
    'use strict';

    // Global ECharts Instances
    let chartMacroTrendInstance = null;
    let chartTransitionInstance = null;
    let chartBehaviorDonutInstance = null;
    let chartVersionBarInstance = null;
    let chartNopTrendInstance = null;
    let chartTopContributorsInstance = null;
    let chartKabTrendInstance = null;
    let chartDomainTrajectoryInstance = null;
    let chartEnlargedInstance = null;
    let currentEnlargedType = null;

    // Modes & State
    let globalMode = 'rci'; // 'rci' or 'unbalance'
    let bannerMode = 'rci';
    let trendMode = 'rci';
    let transMode = 'rci';
    let breakdownMode = 'rci';
    let gaugeMode = 'rci';
    let bulletinMode = 'rci';
    let regTableMode = 'rci';
    let nopTrendMode = 'rci';
    let topKabMode = 'rci';
    let kabTrendMode = 'rci';
    let trajMode = 'rci';
    let tab3Mode = 'rci';
    let selectedTrendKab = '';

    let activeTab = 'achievement';
    let summaryData = null;
    let trendData = null;
    let comparisonData = null;
    let rawComparisonKabRows = [];
    const _CLIENT_COMP_CACHE = {};

    let sortColumn = 'primary_count';
    let sortDirection = 'desc';

    // ── Theme Resolver for ECharts ──────────────────────────────────────────
    function getEChartsTheme() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            isDark: isDark,
            textColor: isDark ? '#f8fafc' : '#0f172a',
            textMuted: isDark ? '#94a3b8' : '#64748b',
            legendColor: isDark ? '#e2e8f0' : '#1e293b',
            axisLineColor: isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(0, 0, 0, 0.12)',
            splitLineColor: isDark ? 'rgba(255, 255, 255, 0.07)' : 'rgba(0, 0, 0, 0.07)',
            targetLineColor: isDark ? '#ffffff' : '#000000',
            labelBg: isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)',
            labelBorder: isDark ? '#475569' : '#cbd5e1',
            tooltipBg: isDark ? 'rgba(15, 23, 42, 0.96)' : 'rgba(255, 255, 255, 0.98)',
            tooltipBorder: isDark ? '#334155' : '#cbd5e1',
            tooltipText: isDark ? '#f8fafc' : '#0f172a'
        };
    }

    const TOOLTIP_STYLE = {
        backgroundColor: 'rgba(15, 23, 42, 0.96)',
        borderColor: '#334155',
        borderWidth: 1,
        borderRadius: 8,
        padding: [8, 12],
        textStyle: { color: '#f8fafc', fontSize: 11.5 }
    };

    // ── Data Fetchers ────────────────────────────────────────────────────────
    function showLoading() {
        let loader = document.getElementById('ranLoadingOverlay');
        if (!loader) {
            const pane = document.getElementById('pane-achievement');
            if (pane) {
                loader = document.createElement('div');
                loader.id = 'ranLoadingOverlay';
                loader.className = 'ran-loading-overlay';
                loader.innerHTML = '<i class="fas fa-circle-notch fa-spin fa-2x"></i> <span>Loading RAN Capacity Data...</span>';
                pane.style.position = 'relative';
                pane.appendChild(loader);
            }
        }
        if (loader) loader.style.display = 'flex';
    }

    function hideLoading() {
        const loader = document.getElementById('ranLoadingOverlay');
        if (loader) loader.style.display = 'none';
    }

    function fetchSummaryData(callback) {
        const reg = document.getElementById('filterRegion').value;
        const br = document.getElementById('filterBranch').value;
        const wk = document.getElementById('filterWeek').value;

        return fetch(`/api/sow/ran_capacity/summary?region=${encodeURIComponent(reg)}&branch=${encodeURIComponent(br)}&week=${encodeURIComponent(wk)}`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    summaryData = data;
                    renderBanner();
                    renderGaugeSection();
                    renderBreakdownSection();
                    renderBulletins();
                    renderRegionalTable();
                    if (callback) callback();
                } else {
                    console.error('Summary API Error:', data.message);
                }
            })
            .catch(err => console.error('Fetch Summary Error:', err));
    }

    function fetchTrendData(callback) {
        const reg = document.getElementById('filterRegion').value;
        const br = document.getElementById('filterBranch').value;
        const startWk = document.getElementById('filterTrendStart').value;
        const endWk = document.getElementById('filterWeek').value;

        return fetch(`/api/sow/ran_capacity/trend?region=${encodeURIComponent(reg)}&branch=${encodeURIComponent(br)}&start_week=${encodeURIComponent(startWk)}&end_week=${encodeURIComponent(endWk)}`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    trendData = data;
                    renderMacroTrendChart();
                    renderTransitionChart();
                    renderNopTrendChart();
                    renderTopContributorsChart();
                    renderKabTrendChart();
                    renderDomainTrajectoryChart();
                    if (callback) callback();
                } else {
                    console.error('Trend API Error:', data.message);
                }
            })
            .catch(err => console.error('Fetch Trend Error:', err));
    }

    function fetchComparisonData(callback) {
        const reg = document.getElementById('filterRegion').value;
        const br = document.getElementById('filterBranch').value;
        const wk = document.getElementById('filterWeek').value;
        const cacheKey = `${reg}_${br}_${wk}_${tab3Mode}`;

        if (_CLIENT_COMP_CACHE[cacheKey]) {
            comparisonData = _CLIENT_COMP_CACHE[cacheKey];
            rawComparisonKabRows = comparisonData.table_kab ? comparisonData.table_kab.slice() : [];
            renderComparisonTables();
            if (callback) callback();
            return Promise.resolve();
        }

        showLoading();
        return fetch(`/api/sow/ran_capacity/comparison?region=${encodeURIComponent(reg)}&branch=${encodeURIComponent(br)}&week=${encodeURIComponent(wk)}&mode=${encodeURIComponent(tab3Mode)}`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    _CLIENT_COMP_CACHE[cacheKey] = data;
                    comparisonData = data;
                    rawComparisonKabRows = data.table_kab ? data.table_kab.slice() : [];
                    renderComparisonTables();
                    if (callback) callback();
                } else {
                    console.error('Comparison API Error:', data.message);
                }
            })
            .catch(err => console.error('Fetch Comparison Error:', err))
            .finally(() => {
                hideLoading();
            });
    }

    // ── Global Mode Switcher ────────────────────────────────────────────────
    window.setGlobalMode = function (mode) {
        globalMode = mode;
        bannerMode = mode;
        trendMode = mode;
        transMode = mode;
        breakdownMode = mode;
        gaugeMode = mode;
        bulletinMode = mode;
        regTableMode = mode;
        nopTrendMode = mode;
        topKabMode = mode;
        kabTrendMode = mode;
        trajMode = mode;
        tab3Mode = mode;

        // Sync button classes
        document.getElementById('btnGlobalRci').classList.toggle('active', mode === 'rci');
        document.getElementById('btnGlobalUnbalance').classList.toggle('active', mode === 'unbalance');

        syncAllSectionButtonClasses();

        // Re-render components
        renderBanner();
        renderMacroTrendChart();
        renderTransitionChart();
        renderBreakdownSection();
        renderGaugeSection();
        renderBulletins();
        renderRegionalTable();
        renderNopTrendChart();
        renderTopContributorsChart();
        renderKabTrendChart();
        renderDomainTrajectoryChart();
        if (activeTab === 'comparison') {
            fetchComparisonData();
        }
    };

    function syncAllSectionButtonClasses() {
        const pairs = [
            ['bannerToggleRci', 'bannerToggleUnb', bannerMode],
            ['trendToggleRci', 'trendToggleUnb', trendMode],
            ['transToggleRci', 'transToggleUnb', transMode],
            ['breakdownToggleRci', 'breakdownToggleUnb', breakdownMode],
            ['gaugeToggleRci', 'gaugeToggleUnb', gaugeMode],
            ['bulletinToggleRci', 'bulletinToggleUnb', bulletinMode],
            ['regTableToggleRci', 'regTableToggleUnb', regTableMode],
            ['nopTrendToggleRci', 'nopTrendToggleUnb', nopTrendMode],
            ['topKabToggleRci', 'topKabToggleUnb', topKabMode],
            ['kabTrendToggleRci', 'kabTrendToggleUnb', kabTrendMode],
            ['trajToggleRci', 'trajToggleUnb', trajMode],
            ['tab3NopToggleRci', 'tab3NopToggleUnb', tab3Mode]
        ];
        pairs.forEach(([rciId, unbId, curr]) => {
            const rEl = document.getElementById(rciId);
            const uEl = document.getElementById(unbId);
            if (rEl) rEl.classList.toggle('active', curr === 'rci');
            if (uEl) uEl.classList.toggle('active', curr === 'unbalance');
        });
    }

    // Individual Section Toggles
    window.setBannerSectionMode = function (mode) {
        bannerMode = mode;
        syncAllSectionButtonClasses();
        renderBanner();
    };

    window.setTrendSectionMode = function (mode) {
        trendMode = mode;
        syncAllSectionButtonClasses();
        renderMacroTrendChart();
    };

    window.setTransSectionMode = function (mode) {
        transMode = mode;
        syncAllSectionButtonClasses();
        renderTransitionChart();
    };

    window.setBreakdownSectionMode = function (mode) {
        breakdownMode = mode;
        syncAllSectionButtonClasses();
        renderBreakdownSection();
    };

    window.setGaugeSectionMode = function (mode) {
        gaugeMode = mode;
        syncAllSectionButtonClasses();
        renderGaugeSection();
    };

    window.setBulletinSectionMode = function (mode) {
        bulletinMode = mode;
        syncAllSectionButtonClasses();
        renderBulletins();
    };

    window.setRegTableSectionMode = function (mode) {
        regTableMode = mode;
        syncAllSectionButtonClasses();
        renderRegionalTable();
    };

    window.setNopTrendSectionMode = function (mode) {
        nopTrendMode = mode;
        syncAllSectionButtonClasses();
        renderNopTrendChart();
    };

    window.setTopKabSectionMode = function (mode) {
        topKabMode = mode;
        syncAllSectionButtonClasses();
        renderTopContributorsChart();
    };

    window.setKabTrendSectionMode = function (mode) {
        kabTrendMode = mode;
        syncAllSectionButtonClasses();
        renderKabTrendChart();
    };

    window.setTrajSectionMode = function (mode) {
        trajMode = mode;
        syncAllSectionButtonClasses();
        renderDomainTrajectoryChart();
    };

    window.onTrendKabChange = function () {
        const select = document.getElementById('trendKabSelect');
        if (select) {
            selectedTrendKab = select.value;
            renderKabTrendChart();
        }
    };

    window.setTab3Mode = function (mode) {
        tab3Mode = mode;
        syncAllSectionButtonClasses();
        fetchComparisonData();
    };

    // ── Render 1: Executive Scorecard Banner ────────────────────────────────
    function renderBanner() {
        if (!summaryData) return;
        const d = bannerMode === 'rci' ? summaryData.rci : summaryData.unbalance;
        const titleEl = document.getElementById('bannerMetricTitle');
        const subtitleEl = document.getElementById('bannerSubtitle');

        if (titleEl) {
            titleEl.textContent = bannerMode === 'rci'
                ? 'RAN CAPACITY | RCI Direct Optim'
                : 'RAN CAPACITY | UNBALANCE';
        }
        if (subtitleEl) {
            subtitleEl.textContent = `Telkomsel & TelkomInfra · Regional ${summaryData.region} · Focus Week W${String(summaryData.yearweek).slice(-2)}`;
        }

        document.getElementById('cardBaseline').textContent = `${d.baseline.toFixed(2)}%`;
        document.getElementById('cardTargetLabel').textContent = d.target_label || 'Target';
        document.getElementById('cardTarget').textContent = `${d.target.toFixed(2)}%`;

        const achVal = bannerMode === 'rci' ? d.optim_pct : d.p1_pct;
        document.getElementById('cardAch').textContent = `${achVal.toFixed(2)}%`;

        const stBadge = document.getElementById('cardStatusBadge');
        if (stBadge) {
            stBadge.className = `ran-score-badge ${d.is_pass ? 'ran-badge-pass' : 'ran-badge-breach'}`;
            stBadge.textContent = d.is_pass ? 'PASS' : 'BREACH';
        }

        document.getElementById('cardGap').textContent = `${d.ach_gap >= 0 ? '+' : ''}${d.ach_gap.toFixed(2)} pp`;

        const excessBadge = document.getElementById('cardExcessBadge');
        if (excessBadge) {
            if (d.excess_sectors > 0) {
                excessBadge.textContent = `Need to solve ${d.excess_sectors} sec`;
                excessBadge.style.background = 'rgba(220, 38, 38, 0.4)';
            } else {
                excessBadge.textContent = '0 sec (On Track)';
                excessBadge.style.background = 'rgba(22, 163, 74, 0.4)';
            }
        }
    }

    // ── Render 2: Macro Trend Combination Chart ─────────────────────────────
    function renderMacroTrendChart() {
        if (!trendData) return;
        const container = document.getElementById('chartMacroTrend');
        if (!container) return;

        if (!chartMacroTrendInstance) {
            chartMacroTrendInstance = echarts.init(container);
        }

        const th = getEChartsTheme();
        const titleEl = document.getElementById('trendChartTitle');
        const isRci = trendMode === 'rci';

        if (titleEl) {
            titleEl.textContent = isRci ? 'Trend RCI PUMA' : 'Trend Unbalance PUMA';
        }

        const weeks = trendData.week_labels;
        let series = [];
        let legendData = [];
        let yAxisConfig = [];

        if (isRci) {
            const r = trendData.rci_trend;
            legendData = ['Capacity Expansion', 'Optimization Part', 'Operation Part', 'Escalation to Vendor', 'RCI Optim [%]', 'RCI Red (All) [%]', 'Target (RCI)'];

            yAxisConfig = [
                {
                    type: 'value',
                    name: '# Sectors',
                    position: 'left',
                    nameTextStyle: { fontSize: 9.5, color: th.textMuted },
                    axisLabel: { color: th.textMuted, fontSize: 9.5 },
                    splitLine: { lineStyle: { color: th.splitLineColor } }
                },
                {
                    type: 'value',
                    name: 'Rate (%)',
                    position: 'right',
                    min: 0,
                    nameTextStyle: { fontSize: 9.5, color: th.textMuted },
                    axisLabel: {
                        color: th.textMuted,
                        fontSize: 9.5,
                        formatter: '{value}%'
                    },
                    splitLine: { show: false }
                }
            ];

            series = [
                {
                    name: 'Capacity Expansion',
                    type: 'bar',
                    stack: 'rci_stack',
                    itemStyle: { color: '#38bdf8' },
                    data: r.engineering
                },
                {
                    name: 'Optimization Part',
                    type: 'bar',
                    stack: 'rci_stack',
                    itemStyle: { color: '#f97316' },
                    data: r.optimization
                },
                {
                    name: 'Operation Part',
                    type: 'bar',
                    stack: 'rci_stack',
                    itemStyle: { color: '#94a3b8' },
                    data: r.operation
                },
                {
                    name: 'Escalation to Vendor',
                    type: 'bar',
                    stack: 'rci_stack',
                    itemStyle: { color: '#06b6d4', borderRadius: [3, 3, 0, 0] },
                    data: r.ran_vendor
                },
                {
                    name: 'RCI Optim [%]',
                    type: 'line',
                    yAxisIndex: 1,
                    itemStyle: { color: '#ea580c' },
                    lineStyle: { width: 2.8, color: '#ea580c' },
                    symbol: 'circle',
                    symbolSize: 5,
                    data: (r.optim_pct || []).map((val, idx) => {
                        const v = Number(val);
                        const tgt = r.target_series ? Number(r.target_series[idx]) : 0.42;
                        const meets = !isNaN(v) && v <= tgt;
                        return {
                            value: val,
                            label: {
                                show: true,
                                position: 'top',
                                fontSize: 9,
                                fontWeight: 'bold',
                                color: meets ? '#10b981' : '#ef4444',
                                backgroundColor: th.labelBg,
                                borderColor: meets ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
                                borderWidth: 1,
                                borderRadius: 3,
                                padding: [1, 3],
                                formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                            }
                        };
                    })
                },
                {
                    name: 'RCI Red (All) [%]',
                    type: 'line',
                    yAxisIndex: 1,
                    itemStyle: { color: '#8B0000' },
                    lineStyle: { width: 2, color: '#8B0000' },
                    symbol: 'circle',
                    symbolSize: 4.5,
                    data: r.red_all_pct
                },
                {
                    name: 'Target (RCI)',
                    type: 'line',
                    step: 'end',
                    yAxisIndex: 1,
                    itemStyle: { color: th.targetLineColor },
                    lineStyle: { type: 'dashed', width: 2, color: th.targetLineColor },
                    symbol: 'none',
                    data: r.target_series
                }
            ];

        } else {
            // Unbalance Mode
            const u = trendData.unbalance_trend;
            legendData = ['Balance', 'P3', 'P2', 'P1', 'P1 Percentage', 'Target (Unbalance)'];

            yAxisConfig = [
                {
                    type: 'value',
                    name: '# Sectors',
                    position: 'left',
                    nameTextStyle: { fontSize: 9.5, color: th.textMuted },
                    axisLabel: { color: th.textMuted, fontSize: 9.5 },
                    splitLine: { lineStyle: { color: th.splitLineColor } }
                },
                {
                    type: 'value',
                    name: 'Rate (%)',
                    position: 'right',
                    min: 0,
                    nameTextStyle: { fontSize: 9.5, color: th.textMuted },
                    axisLabel: {
                        color: th.textMuted,
                        fontSize: 9.5,
                        formatter: '{value}%'
                    },
                    splitLine: { show: false }
                }
            ];

            series = [
                {
                    name: 'Balance',
                    type: 'bar',
                    stack: 'unb_stack',
                    itemStyle: { color: '#1e3a8a' },
                    data: u.balanced
                },
                {
                    name: 'P3',
                    type: 'bar',
                    stack: 'unb_stack',
                    itemStyle: { color: '#7c3aed' },
                    data: u.p3
                },
                {
                    name: 'P2',
                    type: 'bar',
                    stack: 'unb_stack',
                    itemStyle: { color: '#0d9488' },
                    data: u.p2
                },
                {
                    name: 'P1',
                    type: 'bar',
                    stack: 'unb_stack',
                    itemStyle: { color: '#f97316', borderRadius: [3, 3, 0, 0] },
                    data: u.p1
                },
                {
                    name: 'P1 Percentage',
                    type: 'line',
                    yAxisIndex: 1,
                    itemStyle: { color: '#eab308' },
                    lineStyle: { width: 2.8, color: '#eab308' },
                    symbol: 'circle',
                    symbolSize: 5,
                    data: (u.p1_pct || []).map((val, idx) => {
                        const v = Number(val);
                        const tgt = u.target_series ? Number(u.target_series[idx]) : 1.85;
                        const meets = !isNaN(v) && v <= tgt;
                        return {
                            value: val,
                            label: {
                                show: true,
                                position: 'top',
                                fontSize: 9,
                                fontWeight: 'bold',
                                color: meets ? '#10b981' : '#ef4444',
                                backgroundColor: th.labelBg,
                                borderColor: meets ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
                                borderWidth: 1,
                                borderRadius: 3,
                                padding: [1, 3],
                                formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                            }
                        };
                    })
                },
                {
                    name: 'Target (Unbalance)',
                    type: 'line',
                    step: 'end',
                    yAxisIndex: 1,
                    itemStyle: { color: th.targetLineColor },
                    lineStyle: { type: 'dashed', width: 2, color: th.targetLineColor },
                    symbol: 'none',
                    data: u.target_series
                }
            ];
        }

        const option = {
            tooltip: {
                trigger: 'axis',
                confine: true,
                ...TOOLTIP_STYLE
            },
            legend: {
                data: legendData,
                textStyle: { color: th.legendColor, fontSize: 10 },
                icon: 'roundRect',
                itemWidth: 10,
                itemHeight: 6,
                top: 0
            },
            grid: {
                top: 42,
                right: 48,
                bottom: 28,
                left: 54
            },
            xAxis: {
                type: 'category',
                data: weeks,
                axisLabel: { color: th.textMuted, fontSize: 9.5 },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: yAxisConfig,
            series: series
        };

        chartMacroTrendInstance.setOption(option, true);
    }

    // ── Render 3: Transition & Moving Dynamics Chart ────────────────────────
    function renderTransitionChart() {
        const container = document.getElementById('chartTransition');
        if (!container) return;

        if (!chartTransitionInstance) {
            chartTransitionInstance = echarts.init(container);
        }

        const th = getEChartsTheme();
        const titleEl = document.getElementById('transChartTitle');
        const infoBannerEl = document.getElementById('transInfoBanner');
        const isRci = transMode === 'rci';

        if (titleEl) {
            titleEl.textContent = isRci ? 'Moving Trend (Other to Optim)' : 'Sector Transition & State Dynamics';
        }

        if (isRci) {
            if (!trendData || !trendData.rci_trend || !trendData.rci_trend.moving_series) return;
            const mv = trendData.rci_trend.moving_series;
            const lastIdx = mv.weeks.length - 1;
            const lastWk = mv.weeks[lastIdx] || '';
            const lastOpt = mv.optimization[lastIdx] || 0;
            const lastGrn = mv.green_sector[lastIdx] || 0;
            const lastOp = mv.operation[lastIdx] || 0;
            const lastEng = mv.capacity_expansion[lastIdx] || 0;
            const totMoving = lastOpt + lastGrn + lastOp + lastEng;

            if (infoBannerEl) {
                infoBannerEl.innerHTML = `
                    <div style="display:flex; justify-content:space-between; gap:8px; width:100%; margin-bottom:6px;">
                        <div style="flex:1; background:rgba(125,125,125,0.06); border-radius:6px; padding:6px 9px; border-left:3px solid #ea580c;">
                            <div style="font-size:9.5px; font-weight:700; color:var(--ran-text-muted); text-transform:uppercase;">Moving to Direct Optim (${lastWk})</div>
                            <div style="font-size:12px; font-weight:800; color:#ea580c;">${totMoving} Sectors Transitioned</div>
                            <div style="font-size:9.5px; color:var(--ran-text-muted); margin-top:2px;">
                                From Green: <b>${lastGrn}</b> · Maintain Optim: <b>${lastOpt}</b> · From Op: <b>${lastOp}</b> · From Capex: <b>${lastEng}</b>
                            </div>
                        </div>
                        <div style="flex:1; background:rgba(125,125,125,0.06); border-radius:6px; padding:6px 9px; border-left:3px solid #0284c7;">
                            <div style="font-size:9.5px; font-weight:700; color:var(--ran-text-muted); text-transform:uppercase;">Moving Dynamics Insight</div>
                            <div style="font-size:10px; font-weight:700; color:var(--ran-text-main); margin-top:2px;">
                                Most moving contributor to direct optim is moving status from green sector
                            </div>
                            <div style="font-size:9px; color:var(--ran-text-muted); margin-top:2px;">
                                4-Week progression trajectory across network operational domains
                            </div>
                        </div>
                    </div>
                `;
            }

            const option = {
                tooltip: {
                    trigger: 'axis',
                    confine: true,
                    ...TOOLTIP_STYLE
                },
                legend: {
                    data: ['capacity expansion', 'green sector', 'operation part', 'optimization part'],
                    textStyle: { color: th.legendColor, fontSize: 9.5 },
                    icon: 'roundRect',
                    top: 0
                },
                grid: {
                    top: 36,
                    right: 24,
                    bottom: 24,
                    left: 42
                },
                xAxis: {
                    type: 'category',
                    data: mv.weeks,
                    axisLabel: { color: th.textMuted, fontSize: 9.5 }
                },
                yAxis: {
                    type: 'value',
                    name: '# Sectors',
                    nameTextStyle: { fontSize: 9, color: th.textMuted },
                    axisLabel: { color: th.textMuted, fontSize: 9.5 },
                    splitLine: { lineStyle: { color: th.splitLineColor } }
                },
                series: [
                    {
                        name: 'capacity expansion',
                        type: 'bar',
                        stack: 'mv_stack',
                        itemStyle: { color: '#991b1b' },
                        data: mv.capacity_expansion,
                        label: { show: true, position: 'inside', fontSize: 8.5 }
                    },
                    {
                        name: 'green sector',
                        type: 'bar',
                        stack: 'mv_stack',
                        itemStyle: { color: '#16a34a' },
                        data: mv.green_sector,
                        label: { show: true, position: 'inside', fontSize: 8.5 }
                    },
                    {
                        name: 'operation part',
                        type: 'bar',
                        stack: 'mv_stack',
                        itemStyle: { color: '#64748b' },
                        data: mv.operation,
                        label: { show: true, position: 'inside', fontSize: 8.5 }
                    },
                    {
                        name: 'optimization part',
                        type: 'bar',
                        stack: 'mv_stack',
                        itemStyle: { color: '#f97316', borderRadius: [3, 3, 0, 0] },
                        data: mv.optimization,
                        label: { show: true, position: 'inside', fontSize: 8.5 }
                    }
                ]
            };
            chartTransitionInstance.setOption(option, true);

        } else {
            // Unbalance: Dynamics between previous week and current week
            if (!summaryData || !summaryData.unbalance) return;
            const tr = summaryData.unbalance;
            const cl = tr.transitions_closed || {};
            const cur = tr.transitions_current_p1 || {};

            const totClosed = (cl.p1_to_bal || 0) + (cl.p2_to_bal || 0) + (cl.p3_to_bal || 0) + (cl.new_bal || 0);
            const totP1 = tr.p1_sectors || 0;

            if (infoBannerEl) {
                infoBannerEl.innerHTML = `
                    <div style="display:flex; justify-content:space-between; gap:8px; width:100%; margin-bottom:6px;">
                        <div style="flex:1; background:rgba(125,125,125,0.06); border-radius:6px; padding:6px 9px; border-left:3px solid #10b981;">
                            <div style="font-size:9.5px; font-weight:700; color:var(--ran-text-muted); text-transform:uppercase;">Closed Previous Week</div>
                            <div style="font-size:12px; font-weight:800; color:#10b981;">${totClosed} Sectors to Balanced</div>
                            <div style="font-size:9.5px; color:var(--ran-text-muted); margin-top:2px;">
                                P1 to Bal: <b>${cl.p1_to_bal || 0}</b> · P2 to Bal: <b>${cl.p2_to_bal || 0}</b> · P3 to Bal: <b>${cl.p3_to_bal || 0}</b> · New: <b>${cl.new_bal || 0}</b>
                            </div>
                        </div>
                        <div style="flex:1; background:rgba(125,125,125,0.06); border-radius:6px; padding:6px 9px; border-left:3px solid #ea580c;">
                            <div style="font-size:9.5px; font-weight:700; color:var(--ran-text-muted); text-transform:uppercase;">Current Week P1 Contributors</div>
                            <div style="font-size:12px; font-weight:800; color:#ea580c;">${totP1} Sectors in P1 Unbalance</div>
                            <div style="font-size:9.5px; color:var(--ran-text-muted); margin-top:2px;">
                                Maintain P1: <b>${cur.maintain_p1 || 0}</b> · Balanced to P1: <b>${cur.balanced_to_p1 || 0}</b> · P2 to P1: <b>${cur.p2_to_p1 || 0}</b>
                            </div>
                        </div>
                    </div>
                `;
            }

            const categories = [
                'P1 to balanced', 'P2 to balanced', 'P3 to balanced', 'New balanced',
                'Maintain P1', 'Balanced to P1', 'P2 to P1'
            ];
            const values = [
                cl.p1_to_bal || 0,
                cl.p2_to_bal || 0,
                cl.p3_to_bal || 0,
                cl.new_bal || 0,
                cur.maintain_p1 || 0,
                cur.balanced_to_p1 || 0,
                cur.p2_to_p1 || 0
            ];
            const colors = [
                '#10b981', '#14b8a6', '#06b6d4', '#3b82f6',
                '#f97316', '#ea580c', '#c2410c'
            ];

            const option = {
                tooltip: {
                    trigger: 'item',
                    confine: true,
                    ...TOOLTIP_STYLE,
                    formatter: '{b}: <b>{c} sectors</b>'
                },
                grid: {
                    top: 20,
                    right: 24,
                    bottom: 20,
                    left: 120
                },
                xAxis: {
                    type: 'value',
                    axisLabel: { color: th.textMuted, fontSize: 9.5 },
                    splitLine: { lineStyle: { color: th.splitLineColor } }
                },
                yAxis: {
                    type: 'category',
                    data: categories,
                    axisLabel: { color: th.textMuted, fontSize: 9.5 }
                },
                series: [
                    {
                        type: 'bar',
                        data: values.map((val, idx) => ({
                            value: val,
                            itemStyle: { color: colors[idx], borderRadius: [0, 4, 4, 0] }
                        })),
                        label: {
                            show: true,
                            position: 'right',
                            color: th.textColor,
                            fontWeight: 'bold',
                            fontSize: 9
                        }
                    }
                ]
            };
            chartTransitionInstance.setOption(option, true);
        }
    }

    // ── Render 4: Behavioral & Methodology Breakdown ────────────────────────
    function renderBreakdownSection() {
        if (!summaryData) return;
        const isRci = breakdownMode === 'rci';
        const titleEl = document.getElementById('breakdownCardTitle');
        const rciWrap = document.getElementById('breakdownContentRci');
        const unbWrap = document.getElementById('breakdownContentUnb');

        if (titleEl) {
            titleEl.textContent = isRci
                ? 'Aging & Contributor Behavior'
                : 'Methodology Version Breakdown (V1, V2, V3)';
        }

        if (isRci) {
            if (rciWrap) rciWrap.style.display = 'flex';
            if (unbWrap) unbWrap.style.display = 'none';

            const d = summaryData.rci;
            const donutContainer = document.getElementById('chartBehaviorDonut');
            if (donutContainer) {
                if (!chartBehaviorDonutInstance) {
                    chartBehaviorDonutInstance = echarts.init(donutContainer);
                }
                const th = getEChartsTheme();
                const beh = d.behavior || {};
                const totOptim = d.optim_sectors || 0;

                const behData = [
                    { name: 'Consecutive', value: beh.consecutive || 0, itemStyle: { color: '#fef08a' } },
                    { name: 'Flipflop', value: beh.flipflop || 0, itemStyle: { color: '#fed7aa' } },
                    { name: 'New Comer', value: beh.new_comer || 0, itemStyle: { color: '#ea580c' } }
                ];
                const behMap = {};
                behData.forEach(item => { behMap[item.name] = item.value; });

                chartBehaviorDonutInstance.setOption({
                    tooltip: {
                        trigger: 'item',
                        confine: true,
                        ...TOOLTIP_STYLE,
                        formatter: '{b}: <b>{c} sectors ({d}%)</b>'
                    },
                    legend: {
                        bottom: 0,
                        left: 'center',
                        orient: 'horizontal',
                        textStyle: { color: th.legendColor, fontSize: 10 },
                        icon: 'circle',
                        itemWidth: 8,
                        itemHeight: 8,
                        itemGap: 16
                    },
                    title: {
                        text: String(totOptim),
                        subtext: 'Sectors',
                        left: 'center',
                        top: 'center',
                        textAlign: 'center',
                        itemGap: 1,
                        textStyle: {
                            fontSize: 16,
                            fontWeight: 'bold',
                            color: th.textColor,
                            lineHeight: 18
                        },
                        subtextStyle: {
                            fontSize: 10,
                            fontWeight: '600',
                            color: th.textMuted,
                            lineHeight: 12
                        }
                    },
                    series: [
                        {
                            type: 'pie',
                            radius: ['48%', '72%'],
                            center: ['50%', '50%'],
                            avoidLabelOverlap: true,
                            label: { show: false },
                            labelLine: { show: false },
                            emphasis: { label: { show: false } },
                            data: [
                                { name: 'Consecutive', value: beh.consecutive || 0, itemStyle: { color: '#fef08a' } },
                                { name: 'Flipflop', value: beh.flipflop || 0, itemStyle: { color: '#fed7aa' } },
                                { name: 'New Comer', value: beh.new_comer || 0, itemStyle: { color: '#ea580c' } }
                            ]
                        }
                    ]
                }, true);
            }

            // Populate Aging Table
            const tbody = document.getElementById('agingTableBody');
            if (tbody) {
                const ag = d.aging_counts || {};
                const items = [
                    { key: '>3 month', label: '>3 Month' },
                    { key: '3 month', label: '3 Month' },
                    { key: '2 month', label: '2 Month' },
                    { key: '1 month', label: '1 Month' },
                    { key: 'new comer', label: 'New Comer' }
                ];
                let tot = 0;
                let html = '';
                items.forEach(it => {
                    const cnt = ag[it.key] || 0;
                    tot += cnt;
                    html += `<tr><td><strong>${it.label}</strong></td><td style="text-align: right; font-weight: 700;">${cnt}</td></tr>`;
                });
                html += `<tr style="border-top: 2px solid var(--ran-border); font-weight: 800;"><td>TOTAL</td><td style="text-align: right; color: #ea580c;">${tot}</td></tr>`;
                tbody.innerHTML = html;
            }

        } else {
            // Unbalance View: V1, V2, V3 Breakdown
            if (rciWrap) rciWrap.style.display = 'none';
            if (unbWrap) unbWrap.style.display = 'flex';

            const d = summaryData.unbalance;
            const barContainer = document.getElementById('chartVersionBar');
            if (barContainer) {
                if (!chartVersionBarInstance) {
                    chartVersionBarInstance = echarts.init(barContainer);
                }
                const th = getEChartsTheme();
                const v1 = d.v1_p1 || {};
                const v2 = d.v2_p1 || {};
                const v3 = d.v3_p1 || {};

                chartVersionBarInstance.setOption({
                    tooltip: {
                        trigger: 'axis',
                        confine: true,
                        ...TOOLTIP_STYLE
                    },
                    legend: {
                        top: 0,
                        textStyle: { color: th.legendColor, fontSize: 10 }
                    },
                    grid: {
                        top: 36,
                        right: 16,
                        bottom: 24,
                        left: 36
                    },
                    xAxis: {
                        type: 'category',
                        data: ['V1', 'V2', 'V3'],
                        axisLabel: { color: th.textMuted }
                    },
                    yAxis: {
                        type: 'value',
                        axisLabel: { color: th.textMuted },
                        splitLine: { lineStyle: { color: th.splitLineColor } }
                    },
                    series: [
                        {
                            name: 'Balanced',
                            type: 'bar',
                            itemStyle: { color: '#64748b' },
                            data: [v1.balanced || 0, v2.balanced || 0, v3.balanced_thp || 0],
                            label: { show: true, position: 'top', fontSize: 9 }
                        },
                        {
                            name: 'Unbalanced',
                            type: 'bar',
                            itemStyle: { color: '#ea580c' },
                            data: [v1.unbalanced || 0, v2.unbalanced || 0, v3.unbalanced_thp || 0],
                            label: { show: true, position: 'top', fontSize: 9 }
                        }
                    ]
                }, true);
            }

            // Populate Version Table
            const tbody = document.getElementById('versionTableBody');
            if (tbody) {
                const v1 = d.v1_p1 || {};
                const v2 = d.v2_p1 || {};
                const v3 = d.v3_p1 || {};
                const b1 = v1.balanced || 0;
                const u1 = v1.unbalanced || 0;
                const b2 = v2.balanced || 0;
                const u2 = v2.unbalanced || 0;
                const b3 = v3.balanced_thp || 0;
                const u3 = v3.unbalanced_thp || 0;
                const totB = b1 + b2 + b3;
                const totU = u1 + u2 + u3;
                tbody.innerHTML = `
                    <tr><td><strong>V1</strong></td><td style="text-align: right;">${b1}</td><td style="text-align: right; color: #ea580c; font-weight: 700;">${u1}</td></tr>
                    <tr><td><strong>V2</strong></td><td style="text-align: right;">${b2}</td><td style="text-align: right; color: #ea580c; font-weight: 700;">${u2}</td></tr>
                    <tr><td><strong>V3</strong></td><td style="text-align: right;">${b3}</td><td style="text-align: right; color: #ea580c; font-weight: 700;">${u3}</td></tr>
                    <tr style="border-top: 2px solid var(--ran-border); font-weight: 800;">
                        <td>TOTAL</td>
                        <td style="text-align: right;">${totB}</td>
                        <td style="text-align: right; color: #ea580c;">${totU}</td>
                    </tr>
                `;
            }
        }
    }

    // ── Render 5: 1D Benchmark Slider Track vs Target ───────────────────────
    function renderGaugeSection() {
        if (!summaryData) return;
        const d = gaugeMode === 'rci' ? summaryData.rci : summaryData.unbalance;
        const trackWrap = document.getElementById('branchDistribWrap');
        const statRow = document.getElementById('branchStatRow');
        const titleEl = document.getElementById('gaugeCardTitle');

        if (titleEl) {
            titleEl.textContent = gaugeMode === 'rci'
                ? 'Branch Performance vs Target (RCI)'
                : 'Branch Performance vs Target (Unbalance)';
        }

        const branches = d.regional_gauge || [];
        const puma = d.regional_puma || { value: 0 };
        const target = d.target || (gaugeMode === 'rci' ? 0.42 : 1.85);

        // Calculate dynamic domain bounds
        const allVals = branches.map(b => b.value).concat([puma.value, target]);
        const minVal = Math.max(0, Math.min(...allVals) * 0.8);
        const maxVal = Math.max(...allVals) * 1.25;
        const span = maxVal - minVal || 1;

        function pctToLeft(v) {
            const clamp = Math.max(minVal, Math.min(maxVal, v));
            return ((clamp - minVal) / span) * 100;
        }

        const targetLeft = pctToLeft(target);
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const targetLineColor = isDark ? '#ffffff' : '#0f172a';

        // Build HTML for track
        let html = `
            <!-- Target Line Marker (Taller on top) -->
            <div style="position: absolute; left: ${targetLeft}%; top: 0px; transform: translateX(-50%); z-index: 5; text-align: center;">
                <span style="font-size: 11px; font-weight: 800; color: ${targetLineColor};">Target ${target.toFixed(2)}%</span>
            </div>
            <div style="position: absolute; left: ${targetLeft}%; top: 16px; bottom: 52px; border-left: 2px dashed ${targetLineColor}; z-index: 4;"></div>

            <!-- Track Bar (Lower is better: Green on left, Red on right) -->
            <div class="ran-track-bar">
                <div class="ran-track-pass" style="width: ${targetLeft}%;"></div>
                <div class="ran-track-fail"></div>
            </div>
        `;

        // Anti-collision branch pin grouping & placement
        const sortedBranches = branches.slice().sort((a, b) => a.value - b.value);
        const pinGroups = [];
        sortedBranches.forEach(b => {
            const existing = pinGroups.find(g => Math.abs(g.value - b.value) < 0.005);
            if (existing) {
                existing.items.push(b);
            } else {
                pinGroups.push({ value: b.value, items: [b] });
            }
        });

        pinGroups.forEach((g, idx) => {
            const gLeft = pctToLeft(g.value);
            const isPass = g.value <= target;
            const dotColor = isPass ? '#16a34a' : '#dc2626';

            let labelName = g.items.map(b => b.name).join(' & ');
            let labelVal = `${g.value.toFixed(2)}%`;

            let topOffset = '6px';
            if (idx > 0) {
                const prevLeft = pctToLeft(pinGroups[idx - 1].value);
                if (Math.abs(gLeft - prevLeft) < 9.0) {
                    topOffset = (idx % 2 === 1) ? '24px' : '6px';
                }
            }

            html += `
                <div style="position: absolute; left: ${gLeft}%; top: ${topOffset}; transform: translateX(-50%); z-index: 3; text-align: center; pointer-events: none;">
                    <div style="font-size: 10px; font-weight: 700; color: ${dotColor}; white-space: nowrap;">${labelName}</div>
                    <div style="font-size: 10.5px; font-weight: 800; color: ${dotColor};">${labelVal}</div>
                </div>
                <div style="position: absolute; left: ${gLeft}%; top: 60px; transform: translate(-50%, -50%); width: 10px; height: 10px; border-radius: 50%; background: ${dotColor}; border: 2px solid #ffffff; z-index: 3;"></div>
            `;
        });

        // Regional PUMA marker on bottom
        const pumaLeft = pctToLeft(puma.value);
        const pumaPass = puma.value <= target;
        const pumaColor = pumaPass ? '#16a34a' : '#dc2626';

        html += `
            <div style="position: absolute; left: ${pumaLeft}%; top: 70px; transform: translateX(-50%); z-index: 3; text-align: center;">
                <span style="font-size: 10.5px; font-weight: 800; color: ${pumaColor}; background: rgba(125, 125, 125, 0.12); padding: 2px 6px; border-radius: 4px; border: 1px solid ${pumaColor};">
                    ▲ PUMA ${puma.value.toFixed(2)}%
                </span>
            </div>
        `;

        trackWrap.innerHTML = html;

        // Render Companion Branch Chips Row
        if (statRow) {
            let chipHtml = '';
            branches.forEach(b => {
                const isPass = b.value <= target;
                const statusBadge = isPass
                    ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                    : '<span class="ran-pill ran-pill-breach">BREACH</span>';

                const subDetail = gaugeMode === 'rci'
                    ? `Optim: ${(b.optim || 0)} · Eng: ${(b.engineering || 0)}`
                    : `P1: ${(b.p1 || 0)} · Bal: ${(b.bal || 0)}`;

                chipHtml += `
                    <div class="ran-branch-chip">
                        <div class="ran-chip-head">
                            <span>${b.name}</span>
                            ${statusBadge}
                        </div>
                        <div class="ran-chip-val">${b.value.toFixed(2)}%</div>
                        <div class="ran-chip-sub">Total: ${(b.total || 0).toLocaleString()}</div>
                        <div class="ran-chip-sub" style="font-weight: 600;">${subDetail}</div>
                    </div>
                `;
            });
            statRow.innerHTML = chipHtml;
        }
    }

    // ── Render 6: Executive Bulletins ───────────────────────────────────────
    function renderBulletins() {
        if (!summaryData) return;
        const d = bulletinMode === 'rci' ? summaryData.rci : summaryData.unbalance;
        const ul = document.getElementById('bulletinsList');
        if (!ul) return;

        const bullets = d.bulletins || [];
        ul.innerHTML = bullets.map(b => `
            <li class="ran-bulletin-item">
                <i class="fas fa-check-circle"></i>
                <span>${b}</span>
            </li>
        `).join('');
    }

    // ── Render 7: Regional Table ────────────────────────────────────────────
    function renderRegionalTable() {
        if (!summaryData) return;
        const isRci = regTableMode === 'rci';
        const thead = document.getElementById('regionalNopThead');
        const tbody = document.getElementById('regionalNopTbody');
        const titleEl = document.getElementById('regionalTableTitle');

        if (titleEl) {
            titleEl.textContent = isRci
                ? 'Regional NOP Breakdown Table (RCI)'
                : 'Regional NOP Breakdown Table (Unbalance)';
        }

        if (isRci) {
            const rows = summaryData.rci.table_rows || [];
            thead.innerHTML = `
                <tr>
                    <th>NOP</th>
                    <th style="text-align: right;">Direct Investment</th>
                    <th style="text-align: right;">Direct Optim</th>
                    <th style="text-align: right;">Direct Operation</th>
                    <th style="text-align: right;">RAN Vendor</th>
                    <th style="text-align: right;">% Need Optim</th>
                    <th style="text-align: right;">% Need Investment</th>
                    <th style="text-align: center;">Target Status</th>
                </tr>
            `;

            let bodyHtml = '';
            let sumInv = 0, sumOpt = 0, sumOp = 0, sumVen = 0;
            rows.forEach(r => {
                sumInv += (typeof r.direct_investment === 'number' ? r.direct_investment : 0);
                sumOpt += (typeof r.direct_optim === 'number' ? r.direct_optim : 0);
                sumOp += (typeof r.direct_operation === 'number' ? r.direct_operation : 0);
                sumVen += (typeof r.ran_vendor === 'number' ? r.ran_vendor : 0);

                const badge = r.is_pass
                    ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                    : '<span class="ran-pill ran-pill-breach">BREACH</span>';

                bodyHtml += `
                    <tr>
                        <td><strong>${r.nop}</strong></td>
                        <td style="text-align: right;">${r.direct_investment}</td>
                        <td style="text-align: right; font-weight: 700; color: #ea580c;">${r.direct_optim}</td>
                        <td style="text-align: right;">${r.direct_operation}</td>
                        <td style="text-align: right;">${r.ran_vendor}</td>
                        <td style="text-align: right; font-weight: 700;">${r.optim_pct}</td>
                        <td style="text-align: right;">${r.eng_pct}</td>
                        <td style="text-align: center;">${badge}</td>
                    </tr>
                `;
            });

            // Total PUMA row
            const p = summaryData.rci;
            const pBadge = p.is_pass
                ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                : '<span class="ran-pill ran-pill-breach">BREACH</span>';

            bodyHtml += `
                <tr class="total-row">
                    <td><strong>Regional PUMA</strong></td>
                    <td style="text-align: right;">${p.engineering_sectors}</td>
                    <td style="text-align: right; color: #ea580c;">${p.optim_sectors}</td>
                    <td style="text-align: right;">${p.operation_sectors}</td>
                    <td style="text-align: right;">${p.vendor_sectors}</td>
                    <td style="text-align: right;">${p.optim_pct.toFixed(2)}%</td>
                    <td style="text-align: right;">${p.engineering_pct.toFixed(2)}%</td>
                    <td style="text-align: center;">${pBadge}</td>
                </tr>
            `;
            tbody.innerHTML = bodyHtml;

        } else {
            // Unbalance Mode
            const rows = summaryData.unbalance.table_rows || [];
            thead.innerHTML = `
                <tr>
                    <th>NOP</th>
                    <th style="text-align: right;">Balanced</th>
                    <th style="text-align: right;">P1</th>
                    <th style="text-align: right;">P2</th>
                    <th style="text-align: right;">P3</th>
                    <th style="text-align: right;">V1 Unb</th>
                    <th style="text-align: right;">V2 Unb</th>
                    <th style="text-align: right;">V3 Unb</th>
                    <th style="text-align: right;">% Unbalance P1</th>
                    <th style="text-align: center;">Target Status</th>
                </tr>
            `;

            let bodyHtml = '';
            rows.forEach(r => {
                const badge = r.is_pass
                    ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                    : '<span class="ran-pill ran-pill-breach">BREACH</span>';

                bodyHtml += `
                    <tr>
                        <td><strong>${r.nop}</strong></td>
                        <td style="text-align: right;">${r.balanced}</td>
                        <td style="text-align: right; font-weight: 700; color: #ea580c;">${r.p1}</td>
                        <td style="text-align: right;">${r.p2}</td>
                        <td style="text-align: right;">${r.p3}</td>
                        <td style="text-align: right;">${r.v1_unb}</td>
                        <td style="text-align: right;">${r.v2_unb}</td>
                        <td style="text-align: right;">${r.v3_unb}</td>
                        <td style="text-align: right; font-weight: 700;">${r.p1_pct}</td>
                        <td style="text-align: center;">${badge}</td>
                    </tr>
                `;
            });

            // Total PUMA row
            const u = summaryData.unbalance;
            const uBadge = u.is_pass
                ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                : '<span class="ran-pill ran-pill-breach">BREACH</span>';

            bodyHtml += `
                <tr class="total-row">
                    <td><strong>Regional PUMA</strong></td>
                    <td style="text-align: right;">${u.balanced_sectors}</td>
                    <td style="text-align: right; color: #ea580c;">${u.p1_sectors}</td>
                    <td style="text-align: right;">${u.p2_sectors}</td>
                    <td style="text-align: right;">${u.p3_sectors}</td>
                    <td style="text-align: right;">--</td>
                    <td style="text-align: right;">--</td>
                    <td style="text-align: right;">--</td>
                    <td style="text-align: right;">${u.p1_pct.toFixed(2)}%</td>
                    <td style="text-align: center;">${uBadge}</td>
                </tr>
            `;
            tbody.innerHTML = bodyHtml;
        }
    }

    // ── Render 8: Tab 2 NOP Trend Multi-Line Chart ──────────────────────────
    function renderNopTrendChart() {
        if (!trendData) return;
        const container = document.getElementById('chartNopTrend');
        if (!container) return;

        if (!chartNopTrendInstance) {
            chartNopTrendInstance = echarts.init(container);
        }

        const th = getEChartsTheme();
        const isRci = nopTrendMode === 'rci';
        const titleEl = document.getElementById('nopTrendTitle');
        if (titleEl) {
            titleEl.textContent = isRci
                ? 'RCI Direct Optim Trend by NOP'
                : 'Capacity Unbalance P1 Trend by NOP';
        }

        const weeks = trendData.week_labels;
        const nopSeriesMap = isRci ? trendData.rci_trend.nop_series : trendData.unbalance_trend.nop_series;
        const targetSeries = isRci ? trendData.rci_trend.target_series : trendData.unbalance_trend.target_series;

        const nopColors = {
            'AMBON': '#3b82f6',
            'JAYAPURA': '#f97316',
            'TIMIKA': '#10b981',
            'SORONG': '#06b6d4'
        };

        const series = Object.keys(nopColors).map(nop => ({
            name: `NOP ${nop}`,
            type: 'line',
            data: nopSeriesMap[nop] || [],
            itemStyle: { color: nopColors[nop] },
            lineStyle: { width: 2.5, color: nopColors[nop] },
            symbol: 'circle',
            symbolSize: 6
        }));

        series.push({
            name: 'Target Threshold',
            type: 'line',
            step: 'end',
            data: targetSeries,
            itemStyle: { color: th.targetLineColor },
            lineStyle: { type: 'dashed', width: 2, color: th.targetLineColor },
            symbol: 'none'
        });

        chartNopTrendInstance.setOption({
            tooltip: {
                trigger: 'axis',
                confine: true,
                ...TOOLTIP_STYLE
            },
            legend: {
                top: 4,
                left: 'center',
                textStyle: { color: th.legendColor, fontSize: 10 },
                icon: 'roundRect',
                itemWidth: 10,
                itemHeight: 6,
                itemGap: 14
            },
            grid: {
                top: 52,
                right: 20,
                bottom: 28,
                left: 48
            },
            xAxis: {
                type: 'category',
                data: weeks,
                axisLabel: { color: th.textMuted, fontSize: 9.5 }
            },
            yAxis: {
                type: 'value',
                name: 'Rate (%)',
                nameTextStyle: { fontSize: 9, color: th.textMuted, padding: [0, 0, 4, 0] },
                axisLabel: { color: th.textMuted, fontSize: 9.5, formatter: '{value}%' },
                splitLine: { lineStyle: { color: th.splitLineColor } }
            },
            series: series
        }, true);
    }

    // ── Render 9: Tab 2 Top Contributors Horizontal Bar ─────────────────────
    function renderTopContributorsChart() {
        if (!summaryData) return;
        const container = document.getElementById('chartTopContributors');
        if (!container) return;

        if (!chartTopContributorsInstance) {
            chartTopContributorsInstance = echarts.init(container);
        }

        const th = getEChartsTheme();
        const isRci = topKabMode === 'rci';
        const titleEl = document.getElementById('topKabTitle');
        if (titleEl) {
            titleEl.textContent = isRci
                ? 'Top 10 Contributor Direct Optim (Kabupaten)'
                : 'Top 10 Contributor Unbalance P1 (Kabupaten)';
        }

        const topList = isRci ? summaryData.rci.top_contributors : summaryData.unbalance.top_contributors;
        const reversedList = (topList || []).slice().reverse();

        const categories = reversedList.map(item => item.kabupaten);
        const dataValues = reversedList.map(item => item.count);

        chartTopContributorsInstance.setOption({
            tooltip: {
                trigger: 'item',
                confine: true,
                ...TOOLTIP_STYLE,
                formatter: '{b}: <b>{c} sectors</b>'
            },
            grid: {
                top: 20,
                right: 36,
                bottom: 20,
                left: 165
            },
            xAxis: {
                type: 'value',
                name: '# Sectors',
                nameTextStyle: { fontSize: 9, color: th.textMuted },
                axisLabel: { color: th.textMuted, fontSize: 9.5 },
                splitLine: { lineStyle: { color: th.splitLineColor } }
            },
            yAxis: {
                type: 'category',
                data: categories,
                axisLabel: { color: th.textMuted, fontSize: 10 }
            },
            series: [
                {
                    type: 'bar',
                    data: dataValues,
                    itemStyle: {
                        color: isRci ? '#ea580c' : '#f97316',
                        borderRadius: [0, 4, 4, 0]
                    },
                    label: {
                        show: true,
                        position: 'right',
                        color: th.textColor,
                        fontWeight: 'bold',
                        fontSize: 9.5
                    }
                }
            ]
        }, true);
    }

    // ── Render 10: Tab 2 Interactive Kabupaten Historical Drill-Down ────────
    function renderKabTrendChart() {
        if (!trendData) return;
        const container = document.getElementById('chartKabTrend');
        if (!container) return;

        if (!chartKabTrendInstance) {
            chartKabTrendInstance = echarts.init(container);
        }

        const th = getEChartsTheme();
        const isRci = kabTrendMode === 'rci';
        const selectEl = document.getElementById('trendKabSelect');
        const titleEl = document.getElementById('kabTrendTitle');

        const kabList = trendData.kabupaten_list || [];
        if (selectEl && kabList.length > 0 && selectEl.options.length <= 1) {
            selectEl.innerHTML = kabList.map(k => `<option value="${k}" ${k === selectedTrendKab ? 'selected' : ''}>${k}</option>`).join('');
        }

        if (!selectedTrendKab && kabList.length > 0) {
            selectedTrendKab = (selectEl && selectEl.value) ? selectEl.value : kabList[0];
        }

        if (titleEl) {
            titleEl.textContent = isRci
                ? `Kabupaten Trend (RCI): ${selectedTrendKab}`
                : `Kabupaten Trend (Unbalance): ${selectedTrendKab}`;
        }

        const kt = (trendData.kabupaten_trends && trendData.kabupaten_trends[selectedTrendKab]) || null;
        if (!kt) return;

        let series = [];
        let legendData = [];

        if (isRci) {
            legendData = ['Direct Optim', 'Direct Investment', 'Operation Part', 'RAN Vendor', '% Need Optim'];
            series = [
                {
                    name: 'Direct Investment',
                    type: 'bar',
                    stack: 'kab_rci',
                    itemStyle: { color: '#38bdf8' },
                    data: kt.engineering
                },
                {
                    name: 'Direct Optim',
                    type: 'bar',
                    stack: 'kab_rci',
                    itemStyle: { color: '#f97316' },
                    data: kt.optim
                },
                {
                    name: 'Operation Part',
                    type: 'bar',
                    stack: 'kab_rci',
                    itemStyle: { color: '#94a3b8' },
                    data: kt.operation
                },
                {
                    name: 'RAN Vendor',
                    type: 'bar',
                    stack: 'kab_rci',
                    itemStyle: { color: '#06b6d4', borderRadius: [3, 3, 0, 0] },
                    data: kt.ran_vendor
                },
                {
                    name: '% Need Optim',
                    type: 'line',
                    yAxisIndex: 1,
                    itemStyle: { color: '#ea580c' },
                    lineStyle: { width: 2.5, color: '#ea580c' },
                    symbol: 'circle',
                    symbolSize: 5,
                    data: kt.optim_pct
                }
            ];
        } else {
            legendData = ['Balance', 'P3', 'P2', 'P1', '% Unbalance P1'];
            series = [
                {
                    name: 'Balance',
                    type: 'bar',
                    stack: 'kab_unb',
                    itemStyle: { color: '#1e3a8a' },
                    data: kt.balanced
                },
                {
                    name: 'P3',
                    type: 'bar',
                    stack: 'kab_unb',
                    itemStyle: { color: '#7c3aed' },
                    data: kt.p3
                },
                {
                    name: 'P2',
                    type: 'bar',
                    stack: 'kab_unb',
                    itemStyle: { color: '#0d9488' },
                    data: kt.p2
                },
                {
                    name: 'P1',
                    type: 'bar',
                    stack: 'kab_unb',
                    itemStyle: { color: '#f97316', borderRadius: [3, 3, 0, 0] },
                    data: kt.p1
                },
                {
                    name: '% Unbalance P1',
                    type: 'line',
                    yAxisIndex: 1,
                    itemStyle: { color: '#eab308' },
                    lineStyle: { width: 2.5, color: '#eab308' },
                    symbol: 'circle',
                    symbolSize: 5,
                    data: kt.p1_pct
                }
            ];
        }

        chartKabTrendInstance.setOption({
            tooltip: {
                trigger: 'axis',
                confine: true,
                ...TOOLTIP_STYLE
            },
            legend: {
                top: 4,
                left: 'center',
                textStyle: { color: th.legendColor, fontSize: 10 },
                icon: 'roundRect',
                itemWidth: 10,
                itemHeight: 6,
                itemGap: 12
            },
            grid: {
                top: 50,
                right: 48,
                bottom: 28,
                left: 48
            },
            xAxis: {
                type: 'category',
                data: kt.weeks,
                axisLabel: { color: th.textMuted, fontSize: 9.5 }
            },
            yAxis: [
                {
                    type: 'value',
                    name: '# Sectors',
                    nameTextStyle: { fontSize: 9, color: th.textMuted },
                    axisLabel: { color: th.textMuted, fontSize: 9.5 },
                    splitLine: { lineStyle: { color: th.splitLineColor } }
                },
                {
                    type: 'value',
                    name: 'Rate (%)',
                    position: 'right',
                    nameTextStyle: { fontSize: 9, color: th.textMuted },
                    axisLabel: { color: th.textMuted, fontSize: 9.5, formatter: '{value}%' },
                    splitLine: { show: false }
                }
            ],
            series: series
        }, true);
    }

    // ── Render 11: Tab 2 Methodology / Domain Trajectory Trend ──────────────
    function renderDomainTrajectoryChart() {
        if (!trendData) return;
        const container = document.getElementById('chartDomainTrajectory');
        if (!container) return;

        if (!chartDomainTrajectoryInstance) {
            chartDomainTrajectoryInstance = echarts.init(container);
        }

        const th = getEChartsTheme();
        const isRci = trajMode === 'rci';
        const titleEl = document.getElementById('domainTrajectoryTitle');
        if (titleEl) {
            titleEl.textContent = isRci
                ? 'Operational Domain Weekly Trajectory'
                : 'Methodology Version Weekly Trajectory (V1, V2, V3)';
        }

        const weeks = trendData.week_labels;
        let series = [];
        let legendData = [];

        if (isRci) {
            const r = trendData.rci_trend;
            legendData = ['Optimization Part', 'Operation Part', 'Direct Investment', 'RAN Vendor'];
            series = [
                {
                    name: 'Optimization Part',
                    type: 'line',
                    data: r.optimization,
                    itemStyle: { color: '#ea580c' },
                    lineStyle: { width: 2.8, color: '#ea580c' },
                    symbol: 'circle',
                    symbolSize: 5
                },
                {
                    name: 'Operation Part',
                    type: 'line',
                    data: r.operation,
                    itemStyle: { color: '#64748b' },
                    lineStyle: { width: 2.2, color: '#64748b' },
                    symbol: 'circle',
                    symbolSize: 4.5
                },
                {
                    name: 'Direct Investment',
                    type: 'line',
                    data: r.engineering,
                    itemStyle: { color: '#0284c7' },
                    lineStyle: { width: 2.2, color: '#0284c7' },
                    symbol: 'circle',
                    symbolSize: 4.5
                },
                {
                    name: 'RAN Vendor',
                    type: 'line',
                    data: r.ran_vendor,
                    itemStyle: { color: '#06b6d4' },
                    lineStyle: { width: 2.2, color: '#06b6d4' },
                    symbol: 'circle',
                    symbolSize: 4.5
                }
            ];
        } else {
            const u = trendData.unbalance_trend;
            legendData = ['V1 Unbalance (PRB L18/L21)', 'V2 Unbalance (FDD-TDD Gap)', 'V3 Unbalance (Throughput L9)'];
            series = [
                {
                    name: 'V1 Unbalance (PRB L18/L21)',
                    type: 'line',
                    data: u.v1_unb,
                    itemStyle: { color: '#7c3aed' },
                    lineStyle: { width: 2.8, color: '#7c3aed' },
                    symbol: 'circle',
                    symbolSize: 5
                },
                {
                    name: 'V2 Unbalance (FDD-TDD Gap)',
                    type: 'line',
                    data: u.v2_unb,
                    itemStyle: { color: '#0284c7' },
                    lineStyle: { width: 2.8, color: '#0284c7' },
                    symbol: 'circle',
                    symbolSize: 5
                },
                {
                    name: 'V3 Unbalance (Throughput L9)',
                    type: 'line',
                    data: u.v3_unb,
                    itemStyle: { color: '#ea580c' },
                    lineStyle: { width: 2.8, color: '#ea580c' },
                    symbol: 'circle',
                    symbolSize: 5
                }
            ];
        }

        chartDomainTrajectoryInstance.setOption({
            tooltip: {
                trigger: 'axis',
                confine: true,
                ...TOOLTIP_STYLE
            },
            legend: {
                top: 4,
                left: 'center',
                textStyle: { color: th.legendColor, fontSize: 10 },
                icon: 'roundRect',
                itemWidth: 10,
                itemHeight: 6,
                itemGap: 14
            },
            grid: {
                top: 52,
                right: 24,
                bottom: 28,
                left: 48
            },
            xAxis: {
                type: 'category',
                data: weeks,
                axisLabel: { color: th.textMuted, fontSize: 9.5 }
            },
            yAxis: {
                type: 'value',
                name: '# Sectors',
                nameTextStyle: { fontSize: 9, color: th.textMuted, padding: [0, 0, 4, 0] },
                axisLabel: { color: th.textMuted, fontSize: 9.5 },
                splitLine: { lineStyle: { color: th.splitLineColor } }
            },
            series: series
        }, true);
    }

    // ── Render 12: Tab 3 Comparison Tables ──────────────────────────────────
    function renderComparisonTables() {
        if (!comparisonData) return;
        const nopTbody = document.getElementById('comparisonNopTbody');
        const kabTbody = document.getElementById('comparisonKabTbody');

        const isRci = tab3Mode === 'rci';
        const thTab1Cnt = document.getElementById('thTab1PrimaryCnt');
        const thTab1Pct = document.getElementById('thTab1PrimaryPct');
        const thTab2Cnt = document.getElementById('thTab2PrimaryCnt');
        const thTab2Pct = document.getElementById('thTab2PrimaryPct');

        if (thTab1Cnt) thTab1Cnt.textContent = isRci ? 'Direct Optim' : 'Unbalance P1';
        if (thTab1Pct) thTab1Pct.textContent = isRci ? '% Direct Optim' : '% Unbalance P1';
        if (thTab2Cnt) thTab2Cnt.textContent = isRci ? 'Direct Optim' : 'Unbalance P1';
        if (thTab2Pct) thTab2Pct.textContent = isRci ? '% Direct Optim' : '% Unbalance P1';

        // Table 1: NOP Rollup
        if (nopTbody) {
            let html = '';
            (comparisonData.table_nop || []).forEach(r => {
                const badge = r.target_status === 'PASS'
                    ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                    : '<span class="ran-pill ran-pill-breach">BREACH</span>';

                const wowBadge = r.wow_status === 'Improved'
                    ? '<span class="ran-pill ran-pill-improved">Improved</span>'
                    : (r.wow_status === 'Degraded' ? '<span class="ran-pill ran-pill-degraded">Degraded</span>' : '<span class="ran-pill">Flat</span>');

                html += `
                    <tr>
                        <td><strong>${r.branch}</strong></td>
                        <td style="text-align: right;">${(r.total_sectors || 0).toLocaleString()}</td>
                        <td style="text-align: right; font-weight: 700; color: #ea580c;">${r.primary_count}</td>
                        <td style="text-align: right; font-weight: 700;">${r.primary_pct.toFixed(2)}%</td>
                        <td style="text-align: right;">${r.prev_count}</td>
                        <td style="text-align: right;">${r.prev_pct.toFixed(2)}%</td>
                        <td style="text-align: right; font-weight: 600;">${r.wow_delta >= 0 ? '+' : ''}${r.wow_delta.toFixed(2)}</td>
                        <td style="text-align: center;">${wowBadge}</td>
                        <td style="text-align: right;">${r.target.toFixed(2)}%</td>
                        <td style="text-align: center;">${badge}</td>
                    </tr>
                `;
            });

            // Total row
            const tot = comparisonData.total_row;
            if (tot) {
                const totBadge = tot.target_status === 'PASS'
                    ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                    : '<span class="ran-pill ran-pill-breach">BREACH</span>';

                const totWow = tot.wow_status === 'Improved'
                    ? '<span class="ran-pill ran-pill-improved">Improved</span>'
                    : (tot.wow_status === 'Degraded' ? '<span class="ran-pill ran-pill-degraded">Degraded</span>' : '<span class="ran-pill">Flat</span>');

                html += `
                    <tr class="total-row">
                        <td><strong>${tot.branch}</strong></td>
                        <td style="text-align: right;">${(tot.total_sectors || 0).toLocaleString()}</td>
                        <td style="text-align: right; color: #ea580c;">${tot.primary_count}</td>
                        <td style="text-align: right;">${tot.primary_pct.toFixed(2)}%</td>
                        <td style="text-align: right;">${tot.prev_count}</td>
                        <td style="text-align: right;">${tot.prev_pct.toFixed(2)}%</td>
                        <td style="text-align: right;">${tot.wow_delta >= 0 ? '+' : ''}${tot.wow_delta.toFixed(2)}</td>
                        <td style="text-align: center;">${totWow}</td>
                        <td style="text-align: right;">${tot.target.toFixed(2)}%</td>
                        <td style="text-align: center;">${totBadge}</td>
                    </tr>
                `;
            }
            nopTbody.innerHTML = html;
        }

        // Table 2: Granular Kabupaten Table
        if (kabTbody) {
            const nopFilter = document.getElementById('compNopFilter') ? document.getElementById('compNopFilter').value : 'ALL';
            const search = document.getElementById('compSearchInput') ? document.getElementById('compSearchInput').value.trim().toUpperCase() : '';
            const status = document.getElementById('compStatusFilter') ? document.getElementById('compStatusFilter').value : 'ALL';

            let filteredKab = (rawComparisonKabRows || []).filter(r => {
                if (nopFilter !== 'ALL' && r.branch !== nopFilter && r.branch !== `NOP ${nopFilter}`) return false;
                if (status !== 'ALL' && r.target_status !== status) return false;
                if (search && !r.kabupaten.toUpperCase().includes(search) && !r.branch.toUpperCase().includes(search)) return false;
                return true;
            });

            filteredKab.sort((a, b) => {
                let valA = a[sortColumn];
                let valB = b[sortColumn];
                if (typeof valA === 'string') {
                    return sortDirection === 'desc' ? valB.localeCompare(valA) : valA.localeCompare(valB);
                }
                valA = valA !== null && valA !== undefined ? Number(valA) : 0;
                valB = valB !== null && valB !== undefined ? Number(valB) : 0;
                return sortDirection === 'desc' ? valB - valA : valA - valB;
            });

            // Update sort signs in headers
            const sortCols = ['branch', 'kabupaten', 'total_sectors', 'primary_count', 'primary_pct', 'prev_count', 'prev_pct', 'wow_delta'];
            sortCols.forEach(col => {
                const spanEl = document.getElementById(`sortSign_${col}`);
                if (spanEl) {
                    if (sortColumn === col) {
                        spanEl.innerHTML = sortDirection === 'desc'
                            ? '<i class="fas fa-sort-down" style="color: var(--ran-crimson);"></i>'
                            : '<i class="fas fa-sort-up" style="color: var(--ran-crimson);"></i>';
                    } else {
                        spanEl.innerHTML = '<i class="fas fa-sort" style="opacity: 0.35;"></i>';
                    }
                }
            });

            let html = '';
            filteredKab.forEach(r => {
                const badge = r.target_status === 'PASS'
                    ? '<span class="ran-pill ran-pill-pass">PASS</span>'
                    : '<span class="ran-pill ran-pill-breach">BREACH</span>';

                const wowBadge = r.wow_status === 'Improved'
                    ? '<span class="ran-pill ran-pill-improved">Improved</span>'
                    : (r.wow_status === 'Degraded' ? '<span class="ran-pill ran-pill-degraded">Degraded</span>' : '<span class="ran-pill">Flat</span>');

                html += `
                    <tr>
                        <td><strong>${r.branch}</strong></td>
                        <td>${r.kabupaten}</td>
                        <td style="text-align: right;">${(r.total_sectors || 0).toLocaleString()}</td>
                        <td style="text-align: right; font-weight: 700; color: #ea580c;">${r.primary_count}</td>
                        <td style="text-align: right; font-weight: 700;">${r.primary_pct.toFixed(2)}%</td>
                        <td style="text-align: right;">${r.prev_count}</td>
                        <td style="text-align: right;">${r.prev_pct.toFixed(2)}%</td>
                        <td style="text-align: right; font-weight: 600;">${r.wow_delta >= 0 ? '+' : ''}${r.wow_delta.toFixed(2)}</td>
                        <td style="text-align: center;">${wowBadge}</td>
                        <td style="text-align: right;">${r.target.toFixed(2)}%</td>
                        <td style="text-align: center;">${badge}</td>
                    </tr>
                `;
            });
            kabTbody.innerHTML = html;
        }
    }

    // ── Table Sorting & Search ──────────────────────────────────────────────
    window.sortComparisonTable = function (col) {
        if (sortColumn === col) {
            sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
        } else {
            sortColumn = col;
            sortDirection = 'desc';
        }
        renderComparisonTables();
    };

    window.onComparisonSearch = function () {
        renderComparisonTables();
    };

    window.onComparisonFilterChange = function () {
        renderComparisonTables();
    };

    // ── Tab Switching ───────────────────────────────────────────────────────
    window.switchRanTab = function (tabName, btn) {
        activeTab = tabName;
        document.querySelectorAll('.ran-tab-btn').forEach(b => b.classList.remove('active'));
        if (btn) btn.classList.add('active');

        document.querySelectorAll('.ran-tab-pane').forEach(p => p.classList.remove('active'));
        const activePane = document.getElementById(`pane-${tabName}`);
        if (activePane) activePane.classList.add('active');

        // Resize charts upon tab reveal
        requestAnimationFrame(() => {
            setTimeout(resizeAllCharts, 80);
        });

        if (tabName === 'comparison' && !comparisonData) {
            fetchComparisonData();
        }
    };

    // ── Filter Change Trigger ───────────────────────────────────────────────
    window.onGlobalFilterChange = function () {
        showLoading();
        const p1 = fetchSummaryData();
        const p2 = fetchTrendData();
        const p3 = (activeTab === 'comparison') ? fetchComparisonData() : Promise.resolve();

        Promise.all([p1, p2, p3]).finally(() => {
            hideLoading();
        });
    };

    // ── Export CSV Handler ──────────────────────────────────────────────────
    window.exportCurrentData = function () {
        const reg = document.getElementById('filterRegion').value;
        const br = document.getElementById('filterBranch').value;
        const wk = document.getElementById('filterWeek').value;
        const level = activeTab === 'comparison' ? 'sector' : 'kabupaten';

        window.location.href = `/api/sow/ran_capacity/export?region=${encodeURIComponent(reg)}&branch=${encodeURIComponent(br)}&week=${encodeURIComponent(wk)}&mode=${encodeURIComponent(globalMode)}&level=${encodeURIComponent(level)}`;
    };

    // ── Fullscreen Enlarge Modal ────────────────────────────────────────────
    window.enlargeChart = function (type) {
        currentEnlargedType = type;
        const modal = document.getElementById('ranEnlargeModal');
        const box = document.getElementById('ranEnlargeContainer');
        const titleEl = document.getElementById('ranEnlargeTitle');
        if (!modal || !box) return;

        modal.style.display = 'flex';
        box.innerHTML = '';

        if (chartEnlargedInstance) {
            chartEnlargedInstance.dispose();
            chartEnlargedInstance = null;
        }
        chartEnlargedInstance = echarts.init(box);

        if (type === 'macroTrend') {
            titleEl.textContent = trendMode === 'rci' ? 'Trend RCI PUMA' : 'Trend Unbalance PUMA';
            if (chartMacroTrendInstance) {
                chartEnlargedInstance.setOption(chartMacroTrendInstance.getOption());
            }
        } else if (type === 'transition') {
            titleEl.textContent = transMode === 'rci' ? 'Moving Trend (Other to Optim)' : 'Sector Transition & State Dynamics';
            if (chartTransitionInstance) {
                chartEnlargedInstance.setOption(chartTransitionInstance.getOption());
            }
        } else if (type === 'nopTrend') {
            titleEl.textContent = nopTrendMode === 'rci' ? 'RCI Direct Optim Trend by NOP' : 'Capacity Unbalance P1 Trend by NOP';
            if (chartNopTrendInstance) {
                chartEnlargedInstance.setOption(chartNopTrendInstance.getOption());
            }
        } else if (type === 'topKab') {
            titleEl.textContent = topKabMode === 'rci' ? 'Top 10 Contributor Direct Optim (Kabupaten)' : 'Top 10 Contributor Unbalance P1 (Kabupaten)';
            if (chartTopContributorsInstance) {
                chartEnlargedInstance.setOption(chartTopContributorsInstance.getOption());
            }
        } else if (type === 'kabTrend') {
            titleEl.textContent = kabTrendMode === 'rci' ? `Kabupaten Trend (RCI): ${selectedTrendKab}` : `Kabupaten Trend (Unbalance): ${selectedTrendKab}`;
            if (chartKabTrendInstance) {
                chartEnlargedInstance.setOption(chartKabTrendInstance.getOption());
            }
        } else if (type === 'domainTrajectory') {
            titleEl.textContent = trajMode === 'rci' ? 'Operational Domain Weekly Trajectory' : 'Methodology Version Weekly Trajectory (V1, V2, V3)';
            if (chartDomainTrajectoryInstance) {
                chartEnlargedInstance.setOption(chartDomainTrajectoryInstance.getOption());
            }
        }
    };

    window.closeEnlargeModal = function () {
        const modal = document.getElementById('ranEnlargeModal');
        if (modal) modal.style.display = 'none';
        if (chartEnlargedInstance) {
            chartEnlargedInstance.dispose();
            chartEnlargedInstance = null;
        }
    };

    window.downloadEnlargedChart = function () {
        if (!chartEnlargedInstance) return;
        const url = chartEnlargedInstance.getDataURL({ pixelRatio: 2, backgroundColor: '#ffffff' });
        const a = document.createElement('a');
        a.href = url;
        a.download = `RAN_Capacity_Chart_${currentEnlargedType || 'Export'}.png`;
        a.click();
    };

    // ══════════════════════════════════════════════════════════════════
    // Multi-File Batch Queue Importer for RAN Capacity
    // ══════════════════════════════════════════════════════════════════
    let ranFileQueue = [];
    let isRanQueueRunning = false;
    let ranQueueAborted = false;

    // Helper to format seconds into readable string (e.g. 14s, 1m 25s)
    function formatDuration(sec) {
        if (!sec || isNaN(sec) || sec < 0) return '0s';
        sec = Math.round(sec);
        if (sec < 60) return `${sec}s`;
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return s === 0 ? `${m}m` : `${m}m ${s}s`;
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    window.openImportModal = function () {
        const modal = document.getElementById('ranImportModalOverlay');
        if (modal) modal.style.display = 'flex';
        initRanDropZoneEvents();
    };

    window.closeImportModal = function () {
        if (isRanQueueRunning) {
            if (!confirm('An import queue is currently running. Are you sure you want to cancel and close?')) {
                return;
            }
            ranQueueAborted = true;
        }
        const hadSuccess = ranFileQueue.some(f => f.status === 'done');
        const modal = document.getElementById('ranImportModalOverlay');
        if (modal) modal.style.display = 'none';
        resetRanImportState();
        if (hadSuccess) {
            window.location.reload();
        }
    };

    function resetRanImportState() {
        ranFileQueue = [];
        isRanQueueRunning = false;
        ranQueueAborted = false;
        const fileInput = document.getElementById('ranImportFileInput');
        if (fileInput) fileInput.value = '';
        renderRanQueueUI();
        const alertBox = document.getElementById('ranImportAlert');
        if (alertBox) {
            alertBox.style.display = 'none';
            alertBox.innerHTML = '';
        }
        const prog = document.getElementById('ranQueueOverallProgress');
        if (prog) prog.style.display = 'none';
        const curFileStage = document.getElementById('ranCurrentFileStage');
        if (curFileStage) curFileStage.textContent = 'Ready';
        const curFilePct = document.getElementById('ranCurrentFilePct');
        if (curFilePct) curFilePct.textContent = '--';
        const overallBar = document.getElementById('ranOverallProgressBar');
        if (overallBar) overallBar.style.width = '0%';
        const overallPct = document.getElementById('ranOverallPct');
        if (overallPct) overallPct.textContent = '0%';
        const overallStage = document.getElementById('ranOverallStage');
        if (overallStage) overallStage.textContent = 'Overall Queue: 0 of 0';
    }

    window.clearRanQueue = function () {
        if (isRanQueueRunning) return;
        resetRanImportState();
    };

    function initRanDropZoneEvents() {
        const dropZone = document.getElementById('ranDropZone');
        if (!dropZone || dropZone._hasEvents) return;
        dropZone._hasEvents = true;

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.background = 'rgba(20, 93, 160, 0.08)';
                dropZone.style.borderColor = '#145DA0';
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.background = '';
                dropZone.style.borderColor = '';
            }, false);
        });

        dropZone.addEventListener('drop', e => {
            const dt = e.dataTransfer;
            if (dt && dt.files && dt.files.length) {
                addFilesToRanQueue(dt.files);
            }
        }, false);
    }

    window.onRanFileSelected = function (input) {
        if (input.files && input.files.length) {
            addFilesToRanQueue(input.files);
            input.value = '';
        }
    };

    function addFilesToRanQueue(files) {
        if (isRanQueueRunning) return;
        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const ext = f.name.toLowerCase().split('.').pop();
            if (!['xlsx', 'xls', 'csv'].includes(ext)) {
                continue;
            }
            if (ranFileQueue.some(item => item.name === f.name && item.size === f.size)) {
                continue;
            }
            ranFileQueue.push({
                id: 'ran_q_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
                file: f,
                name: f.name,
                size: f.size,
                status: 'pending',
                message: 'Waiting',
                pct: 0,
                duration_s: 0,
                duration_str: '',
                elapsed_s: 0,
                rows: 0,
                weeks: []
            });
        }
        renderRanQueueUI();
    }

    function renderRanQueueUI() {
        const sec = document.getElementById('ranQueueSection');
        const list = document.getElementById('ranQueueListContainer');
        const countEl = document.getElementById('ranQueueTotalCount');
        const sizeEl = document.getElementById('ranQueueTotalSize');
        const btnCount = document.getElementById('ranQueueBtnCount');
        const submitBtn = document.getElementById('btnSubmitImport');
        const addMoreBtn = document.getElementById('btnAddMoreRanFiles');
        const clearBtn = document.getElementById('btnClearRanQueue');

        if (!ranFileQueue.length) {
            if (sec) sec.style.display = 'none';
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-upload"></i> Upload & Import (0)';
            }
            if (addMoreBtn) addMoreBtn.style.display = 'none';
            return;
        }

        if (sec) sec.style.display = 'block';
        if (addMoreBtn) addMoreBtn.style.display = isRanQueueRunning ? 'none' : 'inline-block';
        if (clearBtn) clearBtn.style.display = isRanQueueRunning ? 'none' : 'inline-block';

        const totalBytes = ranFileQueue.reduce((acc, f) => acc + f.size, 0);
        const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);

        if (countEl) countEl.textContent = ranFileQueue.length;
        if (sizeEl) sizeEl.textContent = `${totalMb} MB`;

        if (submitBtn && !isRanQueueRunning) {
            const allDone = ranFileQueue.length > 0 && ranFileQueue.every(f => f.status === 'done');
            if (allDone) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Import Complete (Close & Refresh)';
                submitBtn.onclick = function () {
                    closeImportModal();
                };
            } else {
                const pendingCount = ranFileQueue.filter(f => f.status !== 'done').length;
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<i class="fas fa-upload"></i> Upload & Import (${pendingCount})`;
            }
        }

        if (list) {
            list.innerHTML = ranFileQueue.map((item, idx) => {
                let badgeHtml = '';
                const sizeMb = (item.size / (1024 * 1024)).toFixed(1);
                let extraMeta = `${sizeMb} MB`;
                if (item.duration_str) {
                    extraMeta += ` • ${item.duration_str}`;
                } else if (item.status === 'uploading' || item.status === 'processing') {
                    extraMeta += ` • ${formatDuration(item.elapsed_s || 0)}`;
                }

                if (item.status === 'pending') {
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(0,0,0,0.06); color:var(--text-muted); font-weight:700;">Waiting</span>`;
                } else if (item.status === 'uploading') {
                    const elapsed = formatDuration(item.elapsed_s || 0);
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(20,93,160,0.12); color:#145DA0; font-weight:700;">
                        <i class="fas fa-arrow-up"></i> ${item.pct || 0}% (${elapsed})
                    </span>`;
                } else if (item.status === 'processing') {
                    const elapsed = formatDuration(item.elapsed_s || 0);
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(20,93,160,0.12); color:#145DA0; font-weight:700;">
                        <i class="fas fa-spinner fa-spin"></i> ${item.pct || 0}% (${elapsed})
                    </span>`;
                } else if (item.status === 'done') {
                    const wText = (item.weeks && item.weeks.length) ? item.weeks.map(w => 'W' + String(w).slice(4)).join(',') : 'Done';
                    const rText = item.rows ? ` (${item.rows.toLocaleString()} rows)` : '';
                    const durText = item.duration_str ? ` in ${item.duration_str}` : '';
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(16,185,129,0.15); color:#10b981; font-weight:700;">
                        <i class="fas fa-check"></i> ${wText}${rText}${durText}
                    </span>`;
                } else if (item.status === 'error') {
                    const durText = item.duration_str ? ` (${item.duration_str})` : (item.elapsed_s ? ` (${formatDuration(item.elapsed_s)})` : '');
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(239,68,68,0.15); color:#ef4444; font-weight:700;" title="${escapeHtml(item.message)}">
                        <i class="fas fa-exclamation-triangle"></i> Error${durText}
                    </span>`;
                }

                let errorRowHtml = '';
                if (item.status === 'error' && item.message) {
                    errorRowHtml = `
                        <div style="margin-top: 5px; padding: 4px 8px; background: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; border-radius: 4px; font-size: 11px; color: #b91c1c; line-height: 1.35; display: flex; align-items: flex-start; gap: 6px; max-height: 48px; overflow-y: auto;">
                            <i class="fas fa-exclamation-circle" style="color: #ef4444; margin-top: 2px; flex-shrink: 0;"></i>
                            <div><strong>Reason:</strong> ${escapeHtml(item.message)}</div>
                        </div>
                    `;
                }

                return `
                    <div id="${item.id}" style="padding: 7px 10px; background: #ffffff; border: 1px solid var(--border); border-radius: 6px; font-size: 11.5px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div style="display:flex; align-items:center; gap:8px; overflow:hidden; margin-right:8px;">
                                <span style="font-weight:700; color:var(--text-muted); font-size:10px; width:16px;">#${idx + 1}</span>
                                <i class="fas fa-file-excel" style="color:#145DA0; flex-shrink:0;"></i>
                                <span style="font-weight:700; color:var(--text-main); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${item.name}">${item.name}</span>
                                <span style="color:var(--text-muted); font-size:10.5px; flex-shrink:0;">(${extraMeta})</span>
                            </div>
                            <div style="flex-shrink:0;">
                                ${badgeHtml}
                            </div>
                        </div>
                        ${errorRowHtml}
                    </div>
                `;
            }).join('');
        }
    }

    window.startRanQueueImport = async function () {
        if (!ranFileQueue.length || isRanQueueRunning) return;

        isRanQueueRunning = true;
        ranQueueAborted = false;

        const submitBtn = document.getElementById('btnSubmitImport');
        const addMoreBtn = document.getElementById('btnAddMoreRanFiles');
        const clearBtn = document.getElementById('btnClearRanQueue');
        const alertBox = document.getElementById('ranImportAlert');
        const overallProg = document.getElementById('ranQueueOverallProgress');
        const overallBar = document.getElementById('ranOverallProgressBar');
        const overallStage = document.getElementById('ranOverallStage');
        const overallPct = document.getElementById('ranOverallPct');
        const curFileStage = document.getElementById('ranCurrentFileStage');
        const curFilePct = document.getElementById('ranCurrentFilePct');

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing Queue...';
        }
        if (addMoreBtn) addMoreBtn.style.display = 'none';
        if (clearBtn) clearBtn.style.display = 'none';
        if (alertBox) {
            alertBox.style.display = 'none';
            alertBox.innerHTML = '';
        }
        if (overallProg) overallProg.style.display = 'block';

        let successCount = 0;
        let failCount = 0;
        let totalRowsImported = 0;
        let allWeeksImported = new Set();

        const totalFiles = ranFileQueue.length;
        const queueStartTime = Date.now();

        for (let i = 0; i < totalFiles; i++) {
            if (ranQueueAborted) break;

            const item = ranFileQueue[i];
            if (item.status === 'done') {
                successCount++;
                continue;
            }

            const currentFileNum = i + 1;
            const overallProgressValue = Math.round((i / totalFiles) * 100);

            const elapsedTotalSec = Math.round((Date.now() - queueStartTime) / 1000);
            const elapsedTotalStr = formatDuration(elapsedTotalSec);

            if (overallStage) overallStage.textContent = `Overall: File ${currentFileNum} of ${totalFiles} · Total elapsed: ${elapsedTotalStr}`;
            if (overallPct) overallPct.textContent = `${overallProgressValue}%`;
            if (overallBar) overallBar.style.width = `${overallProgressValue}%`;

            item.status = 'uploading';
            item.pct = 5;
            item.message = 'Uploading file...';
            item.elapsed_s = 0;
            const fileStartTime = Date.now();

            const fileTimer = setInterval(() => {
                if (item.status === 'uploading' || item.status === 'processing') {
                    item.elapsed_s = Math.round((Date.now() - fileStartTime) / 1000);
                    renderRanQueueUI();
                }
            }, 1000);

            renderRanQueueUI();

            try {
                const formData = new FormData();
                formData.append('file', item.file);

                if (curFileStage) curFileStage.textContent = `Uploading ${item.name}...`;
                if (curFilePct) curFilePct.textContent = '5%';

                const uploadRes = await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', '/api/sow/ran_capacity/import', true);

                    xhr.upload.onprogress = (e) => {
                        if (e.lengthComputable) {
                            const percent = Math.min(99, Math.round((e.loaded / e.total) * 100));
                            item.pct = percent;
                            const loadedMb = (e.loaded / 1048576).toFixed(1);
                            const totalMb = (e.total / 1048576).toFixed(1);
                            const sec = Math.round((Date.now() - fileStartTime) / 1000);
                            item.message = `Uploading: ${loadedMb}/${totalMb} MB (${percent}%)`;
                            if (curFileStage) curFileStage.textContent = `${item.name}: ${loadedMb}/${totalMb} MB (${sec}s)`;
                            if (curFilePct) curFilePct.textContent = `${percent}%`;
                            renderRanQueueUI();
                        }
                    };

                    xhr.onload = () => {
                        if (xhr.status >= 200 && xhr.status < 300) {
                            try {
                                resolve(JSON.parse(xhr.responseText));
                            } catch (e) {
                                reject(new Error('Invalid JSON response from server'));
                            }
                        } else {
                            try {
                                const errData = JSON.parse(xhr.responseText);
                                reject(new Error(errData.message || `Upload failed with status ${xhr.status}`));
                            } catch (e) {
                                reject(new Error(`Upload failed with status ${xhr.status}`));
                            }
                        }
                    };

                    xhr.onerror = () => reject(new Error('Network error during upload'));
                    xhr.send(formData);
                });

                const data = uploadRes;

                if (data.status === 'queued' && data.job_id) {
                    item.status = 'processing';
                    item.pct = 15;
                    item.message = 'Processing file...';
                    renderRanQueueUI();

                    await new Promise((resolve) => {
                        const poll = setInterval(async () => {
                            if (ranQueueAborted) {
                                clearInterval(poll);
                                clearInterval(fileTimer);
                                resolve();
                                return;
                            }
                            try {
                                const pres = await fetch('/api/sow/ran_capacity/import/progress/' + data.job_id);
                                const pdata = await pres.json();

                                if (pdata.status !== 'queued') {
                                    item.pct = pdata.pct || 15;
                                    item.message = pdata.message || pdata.status;
                                    item.elapsed_s = Math.round((Date.now() - fileStartTime) / 1000);
                                    if (curFileStage) curFileStage.textContent = `${item.name}: ${pdata.message || pdata.status}`;
                                    if (curFilePct) curFilePct.textContent = `${pdata.pct || 0}%`;
                                    renderRanQueueUI();
                                }

                                if (pdata.status === 'success') {
                                    clearInterval(poll);
                                    clearInterval(fileTimer);
                                    item.status = 'done';
                                    item.pct = 100;
                                    item.rows = pdata.total_rows || 0;
                                    item.weeks = pdata.weeknums || [];
                                    item.duration_s = pdata.duration_s || Math.round((Date.now() - fileStartTime) / 1000);
                                    item.duration_str = pdata.duration_str || formatDuration(item.duration_s);
                                    item.message = pdata.message;
                                    successCount++;
                                    totalRowsImported += (pdata.total_rows || 0);
                                    (pdata.weeknums || []).forEach(w => allWeeksImported.add(w));
                                    renderRanQueueUI();
                                    resolve();
                                } else if (pdata.status === 'error') {
                                    clearInterval(poll);
                                    clearInterval(fileTimer);
                                    item.status = 'error';
                                    item.duration_s = Math.round((Date.now() - fileStartTime) / 1000);
                                    item.duration_str = formatDuration(item.duration_s);
                                    item.message = pdata.message || 'Import error';
                                    failCount++;
                                    renderRanQueueUI();
                                    resolve();
                                }
                            } catch (e) {
                                // transient poll error
                            }
                        }, 500);

                        setTimeout(() => {
                            clearInterval(poll);
                            clearInterval(fileTimer);
                            if (item.status !== 'done') {
                                item.status = 'error';
                                item.duration_s = Math.round((Date.now() - fileStartTime) / 1000);
                                item.duration_str = formatDuration(item.duration_s);
                                item.message = 'Processing timed out after 10 minutes';
                                failCount++;
                                renderRanQueueUI();
                            }
                            resolve();
                        }, 600000);
                    });
                } else {
                    clearInterval(fileTimer);
                    item.status = 'error';
                    item.duration_s = Math.round((Date.now() - fileStartTime) / 1000);
                    item.duration_str = formatDuration(item.duration_s);
                    item.message = data.message || 'Upload failed';
                    failCount++;
                    renderRanQueueUI();
                }
            } catch (err) {
                clearInterval(fileTimer);
                item.status = 'error';
                item.duration_s = Math.round((Date.now() - fileStartTime) / 1000);
                item.duration_str = formatDuration(item.duration_s);
                item.message = err.message || 'Network error';
                failCount++;
                renderRanQueueUI();
            }
        }

        const totalQueueSec = Math.round((Date.now() - queueStartTime) / 1000);
        const totalQueueStr = formatDuration(totalQueueSec);
        const avgSec = totalFiles > 0 ? Math.round(totalQueueSec / totalFiles) : 0;

        if (overallBar) overallBar.style.width = '100%';
        if (overallPct) overallPct.textContent = '100%';
        if (overallStage) overallStage.textContent = `Completed ${successCount} of ${totalFiles} files in ${totalQueueStr} (avg ${avgSec}s/file)`;
        if (curFileStage) curFileStage.textContent = 'All files processed.';
        if (curFilePct) curFilePct.textContent = 'Done';

        isRanQueueRunning = false;
        renderRanQueueUI();

        if (submitBtn) {
            if (successCount > 0) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Import Complete (Close & Refresh)';
                submitBtn.onclick = function () {
                    closeImportModal();
                };
            } else {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Import Failed';
            }
        }

        if (alertBox) {
            alertBox.style.display = 'block';
            if (failCount === 0) {
                alertBox.style.background = 'rgba(16,185,129,0.15)';
                alertBox.style.color = '#10b981';
                alertBox.style.border = '1px solid rgba(16,185,129,0.3)';
                const weeksStr = Array.from(allWeeksImported).sort().map(w => 'W' + String(w).slice(4)).join(', ');
                alertBox.innerHTML = `<i class="fas fa-check-circle"></i> <strong>Queue Completed in ${totalQueueStr}!</strong> Successfully imported ${successCount} files (${totalRowsImported.toLocaleString()} rows) across week(s): ${weeksStr}. Average time: ${avgSec}s per file.`;
            } else {
                alertBox.style.background = 'rgba(239, 68, 68, 0.08)';
                alertBox.style.color = '#991b1b';
                alertBox.style.border = '1px solid rgba(239, 68, 68, 0.3)';
                alertBox.innerHTML = `
                    <div style="display:flex; align-items:center; gap:8px;">
                        <i class="fas fa-exclamation-triangle" style="color:#ef4444; font-size:14px; flex-shrink:0;"></i>
                        <div>
                            <div>Processed <strong>${totalFiles} files</strong> in ${totalQueueStr}: <strong style="color:#10b981;">${successCount} succeeded</strong>, <strong style="color:#ef4444;">${failCount} failed</strong>.</div>
                            <div style="font-size:11px; font-weight:normal; opacity:0.85; margin-top:2px;">Specific error reasons are shown under each file in the queue above.</div>
                        </div>
                    </div>
                `;
            }
        }

        // Trigger cache refresh in background so DB changes are ready when user closes modal
        fetch('/api/sow/ran_capacity/summary?refresh=1').catch(() => {});
    };

    // ── Resize All Charts Helper ────────────────────────────────────────────
    function resizeAllCharts() {
        if (chartMacroTrendInstance) chartMacroTrendInstance.resize();
        if (chartTransitionInstance) chartTransitionInstance.resize();
        if (chartBehaviorDonutInstance) chartBehaviorDonutInstance.resize();
        if (chartVersionBarInstance) chartVersionBarInstance.resize();
        if (chartNopTrendInstance) chartNopTrendInstance.resize();
        if (chartTopContributorsInstance) chartTopContributorsInstance.resize();
        if (chartKabTrendInstance) chartKabTrendInstance.resize();
        if (chartDomainTrajectoryInstance) chartDomainTrajectoryInstance.resize();
        if (chartEnlargedInstance) chartEnlargedInstance.resize();
    }

    // ── Theme Observer (data-theme) ─────────────────────────────────────────
    const themeObserver = new MutationObserver(() => {
        renderMacroTrendChart();
        renderTransitionChart();
        renderBreakdownSection();
        renderGaugeSection();
        renderNopTrendChart();
        renderTopContributorsChart();
        renderKabTrendChart();
        renderDomainTrajectoryChart();
    });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    // Sidebar Resize Observer
    const sidebarEl = document.getElementById('sidebar');
    if (sidebarEl) {
        new MutationObserver(() => setTimeout(resizeAllCharts, 320)).observe(sidebarEl, { attributes: true, attributeFilter: ['class'] });
    }

    window.addEventListener('resize', () => {
        requestAnimationFrame(resizeAllCharts);
    });

    // ── Initialization on Page Load ─────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        showLoading();
        Promise.all([
            fetchSummaryData(),
            fetchTrendData()
        ]).finally(() => {
            hideLoading();
        });
    });

})();
