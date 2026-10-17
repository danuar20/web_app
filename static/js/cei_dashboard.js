/**
 * CEI Dashboard JavaScript
 * Multi-Tab CEI Dashboard:
 *   1. CEI Achievement (Gauge + 7 KQI Cards + Branch Distribution Strip + CEI Trend Achievement + KQI Trend Combo)
 *   2. CEI Trend (Geo filtered by Kabupaten & Kecamatan, Summary Bar, Geo Good % Trend, 7 KQI Trend mini-charts)
 *   3. Comparison Table (CEI Table Achievement WoW + 7 KQI Comparison Table WoW + Kabupaten Level WoW Table with 7-KQI Filter)
 */

(function () {
    'use strict';

    // Global ECharts Instances
    let pumaGaugeInstance = null;
    let branchContribInstance = null;
    let trendChartInstance = null;
    let achievementChartInstance = null;
    let geoGoodPctChartInstance = null;
    let geoKqiInstances = [];

    // State
    let activeTab = 'achievement';
    let availableWeeks = [];
    let currentKqiCellFilter = 'bad';
    let currentTrendCellFilter = 'bad';
    let currentTrendMetricType = 'total_days';
    let geoOptionsData = null;
    let rawKabupatenData = [];
    let selectedCeiFile = null;

    // Vibrant Distinct Palette for 7 KQIs
    const KQI_COLORS = {
        web_rtt: '#d97706',       // Amber
        web_ul_retrans: '#4f46e5',// Indigo
        video_vxb: '#db2777',     // Rose Pink
        voip_ul: '#7c3aed',       // Purple
        voip_dl: '#2563eb',       // Blue
        game_rtt: '#059669',      // Emerald
        game_jitter: '#dc2626'    // Crimson
    };

    // DOM Ready
    document.addEventListener('DOMContentLoaded', function () {
        initSidebarObserver();
        initWeeksAndData();
    });

    // ── Tab Management ──
    window.switchCeiTab = function (tabId, btnElem) {
        activeTab = tabId;
        document.querySelectorAll('.cei-tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.cei-tab-pane').forEach(pane => pane.classList.remove('active'));

        if (btnElem) {
            btnElem.classList.add('active');
        }
        const targetPane = document.getElementById(`pane-${tabId}`);
        if (targetPane) {
            targetPane.classList.add('active');
        }

        // Trigger chart resizes when switching tabs
        setTimeout(resizeAllVisibleCharts, 50);
        setTimeout(resizeAllVisibleCharts, 250);
    };

    // ── Auto-Resize on Window & Sidebar Toggle ──
    function resizeAllVisibleCharts() {
        if (activeTab === 'achievement') {
            if (pumaGaugeInstance) pumaGaugeInstance.resize();
            if (branchContribInstance) branchContribInstance.resize();
            if (achievementChartInstance) achievementChartInstance.resize();
            if (trendChartInstance) trendChartInstance.resize();
        } else if (activeTab === 'trend') {
            if (geoGoodPctChartInstance) geoGoodPctChartInstance.resize();
            geoKqiInstances.forEach(c => { if (c) c.resize(); });
        }
    }

    window.addEventListener('resize', function () {
        resizeAllVisibleCharts();
    });

    function initSidebarObserver() {
        const sidebar = document.getElementById('sidebar');
        if (sidebar && window.MutationObserver) {
            const observer = new MutationObserver(function () {
                setTimeout(resizeAllVisibleCharts, 220);
                setTimeout(resizeAllVisibleCharts, 420);
            });
            observer.observe(sidebar, { attributes: true, attributeFilter: ['class', 'style'] });
        }
        document.querySelectorAll('#sidebarToggle, .sidebar-toggle, [data-toggle="sidebar"]').forEach(el => {
            el.addEventListener('click', function () {
                setTimeout(resizeAllVisibleCharts, 220);
                setTimeout(resizeAllVisibleCharts, 420);
            });
        });
    }

    // ── Global Initialization ──
    async function initWeeksAndData() {
        // Render Tab 1 initial views immediately with pre-selected Jinja2 defaults
        loadGaugeAndSummary();
        loadKqiCards();
        loadAchievementChart();
        loadTrendChart();

        // Pre-load Tab 2 & 3
        loadGeoOptions();
        loadComparison();
        loadKabupatenComparison();

        // Sync availableWeeks from API if needed
        try {
            const res = await fetch('/api/sow/cei/summary');
            const data = await res.json();
            if (data.status === 'success' && data.yearweeks && data.yearweeks.length) {
                availableWeeks = data.yearweeks;
            }
        } catch (e) {
            console.error('Error syncing available weeks:', e);
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // TAB 1: CEI Achievement Logic
    // ══════════════════════════════════════════════════════════════════
    window.onTrendFilterChange = function () {
        loadAchievementChart();
        loadTrendChart();
    };

    window.onGaugeFilterChange = function () {
        loadGaugeAndSummary();
        loadKqiCards();
    };

    window.setKqiCellFilter = function (filter) {
        currentKqiCellFilter = filter;
        document.querySelectorAll('#btnKqiBad, #btnKqiGood, #btnKqiAll').forEach(b => b.classList.remove('active'));
        if (filter === 'bad') document.getElementById('btnKqiBad').classList.add('active');
        if (filter === 'good') document.getElementById('btnKqiGood').classList.add('active');
        if (filter === 'all') document.getElementById('btnKqiAll').classList.add('active');
        loadKqiCards();
    };

    window.setTrendCellFilter = function (filter) {
        currentTrendCellFilter = filter;
        document.querySelectorAll('#btnTrendBad, #btnTrendGood, #btnTrendAll').forEach(b => b.classList.remove('active'));
        if (filter === 'bad') document.getElementById('btnTrendBad').classList.add('active');
        if (filter === 'good') document.getElementById('btnTrendGood').classList.add('active');
        if (filter === 'all') document.getElementById('btnTrendAll').classList.add('active');
        loadTrendChart();
    };

    window.setTrendMetricType = function (metric) {
        currentTrendMetricType = metric;
        document.querySelectorAll('#btnMetricTotalDays, #btnMetricCellCount').forEach(b => b.classList.remove('active'));
        if (metric === 'total_days') document.getElementById('btnMetricTotalDays').classList.add('active');
        if (metric === 'cell_count') document.getElementById('btnMetricCellCount').classList.add('active');
        loadTrendChart();
    };

    async function loadGaugeAndSummary() {
        const ywElem = document.getElementById('gaugeWeek');
        const yw = ywElem ? ywElem.value : '';
        try {
            const res = await fetch(`/api/sow/cei/summary?weeknum=${yw}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            // Update stats
            const totalEl = document.getElementById('statTotalCells');
            const goodEl = document.getElementById('statGoodCells');
            const badEl = document.getElementById('statBadCells');
            const goodPctEl = document.getElementById('statGoodPct');
            const badPctEl = document.getElementById('statBadPct');

            if (totalEl) totalEl.textContent = (data.total_cells || 0).toLocaleString();
            if (goodEl) goodEl.textContent = (data.good_cells || 0).toLocaleString();
            if (badEl) badEl.textContent = (data.bad_cells || 0).toLocaleString();
            if (goodPctEl) goodPctEl.textContent = `${data.good_cell_pct || 0}%`;
            if (badPctEl) {
                const bPct = (data.total_cells && data.bad_cells) ? ((data.bad_cells * 100.0) / data.total_cells).toFixed(2) : 0;
                badPctEl.textContent = `${bPct}%`;
            }

            // Target badge e.g. Target: 93.95% (Q3)
            const targetBadge = document.getElementById('gaugeTargetBadge');
            const target = data.target !== null ? data.target : 93.95;
            const qStr = (data.quarter || 'Q').replace(/^Target\s*/i, '').trim();
            if (targetBadge) {
                targetBadge.textContent = `Target: ${target}% (${qStr})`;
                targetBadge.className = data.is_above_target ? 'badge-pass' : 'badge-fail';
            }

            // Additional Performance & WoW Insights
            const wowDeltaEl = document.getElementById('statWowDelta');
            if (wowDeltaEl) {
                if (data.diff_prev_pp !== null && data.diff_prev_pp !== undefined) {
                    const isWowUp = data.diff_prev_pp >= 0;
                    const sign = data.diff_prev_pp > 0 ? '+' : '';
                    const arrow = isWowUp ? '▲ ' : '▼ ';
                    const colClass = isWowUp ? 'val-pos' : 'val-neg';
                    wowDeltaEl.innerHTML = `<span class="${colClass}">${arrow}${sign}${data.diff_prev_pp} pp</span> <span style="font-size:9.5px; opacity:0.75; font-weight:600;">vs ${data.prev_label || 'prev'}</span>`;
                } else {
                    wowDeltaEl.textContent = '-';
                }
            }

            const tgtDeltaEl = document.getElementById('statTargetDelta');
            if (tgtDeltaEl) {
                if (data.diff_target_pp !== null && data.diff_target_pp !== undefined) {
                    const isTgtPass = data.diff_target_pp >= 0;
                    const sign = data.diff_target_pp > 0 ? '+' : '';
                    const colClass = isTgtPass ? 'val-pos' : 'val-neg';
                    tgtDeltaEl.innerHTML = `<span class="${colClass}">${sign}${data.diff_target_pp} pp</span> <span style="font-size:9.5px; opacity:0.75; font-weight:600;">(${isTgtPass ? 'Pass' : 'Below'})</span>`;
                } else {
                    tgtDeltaEl.textContent = '-';
                }
            }

            const recEl = document.getElementById('statRecoverNeed');
            if (recEl) {
                const needed = data.needed_recover || 0;
                if (needed > 0) {
                    recEl.innerHTML = `<span class="val-neg">${needed.toLocaleString()} cells</span> <span style="font-size:9.5px; opacity:0.75; font-weight:600;">to pass</span>`;
                } else {
                    recEl.innerHTML = `<span class="val-pos">0 cells</span> <span style="font-size:9.5px; opacity:0.75; font-weight:600;">(On Track)</span>`;
                }
            }

            // Update Top Executive Banner (Image e7b7ff match)
            updateExecBanner(data, target);

            // Render Executive Summary Highlights (Matching Redcoverage / RAN Capacity)
            renderExecutiveSummary(data, target);

            // Render Puma Gauge (Only clean percentage, no overlapping ticks)
            renderPumaGauge(data.good_cell_pct, target);

            // Render Branch Performance Distribution Strip (Image 2)
            renderBranchDistribution(data.regional_gauge, data.good_cell_pct, target, data.quarter);

            // Render Branch Contribution & Volume Breakdown Chart
            renderBranchContribChart(data.regional_gauge, data.label_week || `W${yw.slice(4)}`);
        } catch (e) {
            console.error('Error loading summary & gauge:', e);
        }
    }

    // ── Update Top Executive Banner (Matching Image e7b7ff with Theme #0F3B66) ──
    function updateExecBanner(data, target) {
        const weekNumEl = document.getElementById('bannerWeekNum');
        if (weekNumEl && data.weeknum) {
            weekNumEl.textContent = String(data.weeknum).slice(4);
        }

        const baselineEl = document.getElementById('bannerBaseline');
        if (baselineEl) {
            baselineEl.textContent = `${(data.baseline || 92.51).toFixed(2)}%`;
        }

        const targetLabelEl = document.getElementById('bannerTargetLabel');
        if (targetLabelEl) {
            const qStr = (data.quarter || 'Q3').replace(/^Target\s*/i, '').trim();
            targetLabelEl.textContent = `TARGET (TARGET ${qStr})`;
        }

        const targetEl = document.getElementById('bannerTarget');
        if (targetEl) {
            targetEl.textContent = `${target.toFixed(2)}%`;
        }

        const achEl = document.getElementById('bannerAch');
        if (achEl) {
            achEl.textContent = `${(data.good_cell_pct || 0).toFixed(2)}%`;
        }

        const gapEl = document.getElementById('bannerGap');
        if (gapEl) {
            const gap = data.diff_target_pp || 0;
            const sign = gap > 0 ? '+' : '';
            gapEl.textContent = `${sign}${gap.toFixed(2)} pp`;
            if (gap >= 0) {
                gapEl.style.color = '#6ee7b7'; // Mint green
            } else {
                gapEl.style.color = '#fca5a5'; // Soft red
            }
        }
    }

    // ── Executive Summary Highlights (Matching Redcoverage / RAN Capacity Style) ──
    function renderExecutiveSummary(data, target) {
        const listEl = document.getElementById('execBulletsList');
        if (!listEl) return;

        const isPass = (data.good_cell_pct || 0) >= target;
        const statusText = isPass ? 'PASS TARGET' : 'BELOW TARGET';
        const statusClass = isPass ? 'val-pos' : 'val-neg';
        const wowVal = data.diff_prev_pp || 0;
        const wowText = wowVal > 0 ? `improved by +${wowVal} pp` : (wowVal < 0 ? `declined by ${wowVal} pp` : 'remained stable');
        const gapVal = data.diff_target_pp || 0;
        const gapText = gapVal >= 0 ? `exceeding by +${gapVal} pp` : `trailing by ${Math.abs(gapVal)} pp`;

        const branches = (data.regional_gauge || []).slice();
        const passBranches = branches.filter(b => b.value >= target).map(b => `${b.name} (${b.value}%)`);
        const belowBranches = branches.filter(b => b.value < target).map(b => `${b.name} (${b.value}%)`);

        let bPassText = passBranches.length ? passBranches.join(', ') : 'None';
        let bBelowText = belowBranches.length ? belowBranches.join(', ') : 'None';

        const recoverMsg = (data.needed_recover && data.needed_recover > 0)
            ? `Immediate action required: <strong>${data.needed_recover.toLocaleString()} cells</strong> need recovery to reach quarterly target.`
            : `Cell performance is healthy with <strong>0 recovery cells</strong> required.`;

        listEl.innerHTML = `
            <li>
                <strong>Overall Performance (${data.label_week || 'Latest'}):</strong> Regional PUMA achieved
                <span class="${statusClass}"><strong>${data.good_cell_pct}%</strong> (${statusText})</span> vs
                target <strong>${target}% (${data.quarter || 'Q3'})</strong>, ${gapText}.
            </li>
            <li>
                <strong>Week-over-Week Momentum:</strong> Performance ${wowText} compared to ${data.prev_label || 'previous week'}
                with <strong>${(data.good_cells || 0).toLocaleString()}</strong> good cells out of <strong>${(data.total_cells || 0).toLocaleString()}</strong> total cells.
            </li>
            <li>
                <strong>Branch Achievement:</strong> Passing target: <strong class="val-pos">${bPassText}</strong>.
                Below target: <strong class="val-neg">${bBelowText}</strong>.
            </li>
            <li>
                <strong>Operational Focus:</strong> ${recoverMsg}
            </li>
        `;
    }

    // ── Gauge: Clean percentage only, no tick clutter (Image 1 fix) ──
    function renderPumaGauge(pct, target) {
        const dom = document.getElementById('pumaGaugeChart');
        if (!dom) return;
        if (!pumaGaugeInstance) {
            pumaGaugeInstance = echarts.init(dom);
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const numPct = typeof pct === 'number' ? pct : (parseFloat(pct) || 0);
        const numTarget = typeof target === 'number' ? target : (parseFloat(target) || 93.95);
        const isPass = numPct >= numTarget;
        const mainColor = isPass ? '#00B074' : '#ef4444';

        const option = {
            series: [
                {
                    type: 'gauge',
                    startAngle: 195,
                    endAngle: -15,
                    min: 70,
                    max: 100,
                    itemStyle: { color: mainColor },
                    progress: {
                        show: true,
                        width: 14,
                        roundCap: true,
                        itemStyle: { color: mainColor }
                    },
                    pointer: { show: false },
                    axisLine: {
                        lineStyle: {
                            width: 14,
                            color: [[1, isDark ? 'rgba(255,255,255,0.08)' : '#E5E9EC']]
                        }
                    },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: false }, // Completely hide overlapping ticks
                    title: {
                        show: true,
                        offsetCenter: [0, '35%'],
                        fontSize: 11.5,
                        fontWeight: '700',
                        color: isDark ? '#94a3b8' : '#64748b'
                    },
                    detail: {
                        valueAnimation: true,
                        offsetCenter: [0, '-10%'],
                        fontSize: 27,
                        fontWeight: '800',
                        formatter: '{value}%',
                        color: mainColor
                    },
                    data: [
                        {
                            value: numPct,
                            name: isPass ? 'PASS TARGET' : 'BELOW TARGET'
                        }
                    ]
                }
            ]
        };

        pumaGaugeInstance.setOption(option, true);
        pumaGaugeInstance.resize();
    }

    // ── Branch Contribution & Cell Volume Chart (Right Pane of Section 3) ──
    function renderBranchContribChart(branchesData, focusWeekLabel) {
        const dom = document.getElementById('branchContribChart');
        if (!dom) return;

        const lblEl = document.getElementById('branchContribWeekLbl');
        if (lblEl && focusWeekLabel) {
            lblEl.textContent = focusWeekLabel;
        }

        if (!branchContribInstance) {
            branchContribInstance = echarts.init(dom);
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const branches = (branchesData && branchesData.length) ? branchesData.slice() : [
            { name: 'TIMIKA', value: 93.74, total: 9803, good: 9189, bad: 614 },
            { name: 'JAYAPURA', value: 93.15, total: 10700, good: 9967, bad: 733 },
            { name: 'AMBON', value: 95.63, total: 11618, good: 11110, bad: 508 },
            { name: 'SORONG', value: 94.95, total: 9486, good: 9007, bad: 479 }
        ];

        const branchNames = branches.map(b => b.name);
        const goodCounts = branches.map(b => b.good || 0);
        const badCounts = branches.map(b => b.bad !== undefined ? b.bad : (b.fail || 0));
        const pctValues = branches.map(b => b.value || 0);

        const option = {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                padding: [6, 10],
                textStyle: { fontSize: 11 },
                formatter: function (params) {
                    if (!params || !params.length) return '';
                    const idx = params[0].dataIndex;
                    const b = branches[idx];
                    let html = `<div style="font-weight:700; margin-bottom:4px; font-size:11px;">${b.name}</div>`;
                    html += `<div style="font-size:10.5px; line-height:1.5;"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#0F3B66;margin-right:5px;"></span>Total Cells: <strong>${(b.total || 0).toLocaleString()}</strong></div>`;
                    html += `<div style="font-size:10.5px; line-height:1.5;"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#10b981;margin-right:5px;"></span>Good Cells: <strong>${(b.good || 0).toLocaleString()}</strong></div>`;
                    html += `<div style="font-size:10.5px; line-height:1.5;"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#ef4444;margin-right:5px;"></span>Bad Cells: <strong>${(b.bad || 0).toLocaleString()}</strong></div>`;
                    html += `<div style="font-size:10.5px; line-height:1.5; margin-top:2px; padding-top:2px; border-top:1px dashed rgba(255,255,255,0.2);"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#0284c7;margin-right:5px;"></span>% Good: <strong>${b.value}%</strong></div>`;
                    return html;
                }
            },
            legend: {
                data: ['Good Cells', 'Bad Cells', '% Good Cell'],
                bottom: 0,
                itemWidth: 14,
                itemHeight: 9,
                textStyle: { color: isDark ? '#cbd5e1' : '#334155', fontSize: 10 }
            },
            grid: { top: 26, left: 48, right: 46, bottom: 36 },
            xAxis: {
                type: 'category',
                data: branchNames,
                axisLabel: { color: isDark ? '#94a3b8' : '#334155', fontSize: 10, fontWeight: '700' }
            },
            yAxis: [
                {
                    type: 'value',
                    name: 'Cells',
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 9.5 },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: 9.5,
                        formatter: val => (val >= 1000 ? `${(val / 1000).toFixed(0)}k` : val)
                    },
                    splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' } }
                },
                {
                    type: 'value',
                    name: '% Good',
                    min: 85,
                    max: 100,
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 9.5 },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: 9.5,
                        formatter: '{value}%'
                    },
                    splitLine: { show: false }
                }
            ],
            series: [
                {
                    name: 'Good Cells',
                    type: 'bar',
                    stack: 'cells',
                    barWidth: '38%',
                    itemStyle: { color: '#0F3B66' }, // Branded Navy Blue #0F3B66
                    data: goodCounts
                },
                {
                    name: 'Bad Cells',
                    type: 'bar',
                    stack: 'cells',
                    itemStyle: { color: '#ef4444', borderRadius: [3, 3, 0, 0] },
                    data: badCounts
                },
                {
                    name: '% Good Cell',
                    type: 'line',
                    yAxisIndex: 1,
                    symbol: 'circle',
                    symbolSize: 7,
                    lineStyle: { color: '#10b981', width: 2.5 },
                    itemStyle: { color: '#10b981', borderWidth: 2, borderColor: '#ffffff' },
                    label: {
                        show: true,
                        position: 'top',
                        formatter: '{c}%',
                        fontSize: 9.5,
                        fontWeight: '700',
                        color: isDark ? '#a7f3d0' : '#065f46'
                    },
                    data: pctValues
                }
            ]
        };

        branchContribInstance.setOption(option, true);
        branchContribInstance.resize();
    }

    // ── Branch Performance Distribution vs Target (Matches RHI Subpage) ──
    function renderBranchDistribution(branchesData, pumaPct, target, quarterLabel) {
        const wrap = document.getElementById('branchDistribWrap');
        if (!wrap) return;

        const qBadge = document.getElementById('distribQuarterBadge');
        if (qBadge) {
            qBadge.textContent = `${quarterLabel || 'Target'}: ${target}%`;
        }

        const branchList = (branchesData && branchesData.length) ? branchesData.slice() : [
            { name: 'TIMIKA', value: 93.74, is_above: false, total: 9803, bad: 614 },
            { name: 'JAYAPURA', value: 93.15, is_above: false, total: 10700, bad: 733 },
            { name: 'AMBON', value: 95.63, is_above: true, total: 11618, bad: 508 },
            { name: 'SORONG', value: 94.95, is_above: true, total: 9486, bad: 479 }
        ];

        // Sort ascending by value for reliable spacing & collision checks
        branchList.sort((a, b) => a.value - b.value);

        const allVals = [target, pumaPct || 94.48].concat(branchList.map(b => b.value));
        let minScale = Math.floor(Math.min(...allVals) - 0.5);
        let maxScale = Math.ceil(Math.max(...allVals) + 0.5);
        if (maxScale - minScale < 6) {
            minScale -= 1;
            maxScale += 1;
        }
        const scaleRange = maxScale - minScale;

        function getLeftPct(val) {
            const clamped = Math.max(minScale, Math.min(maxScale, val));
            return ((clamped - minScale) / scaleRange) * 100;
        }

        const targetLeft = getLeftPct(target);
        const pumaLeft = getLeftPct(pumaPct || 94.48);

        // Render Branch/NOP: ALL AT TOP, with 2-line format (Branch Name shift+Enter Value)
        let branchPointsHtml = '';
        let lastLeft = -999;
        let lastTop = 20;

        branchList.forEach(b => {
            const bLeft = getLeftPct(b.value);
            const isMet = b.value >= target;
            const valColor = isMet ? '#16a34a' : '#dc2626';
            const dotColor = isMet ? '#10b981' : '#ef4444';

            // Anti-collision staggering: if closer than 7.5% to previous branch, alternate top position
            let topOffset = 20;
            if (Math.abs(bLeft - lastLeft) < 7.5) {
                topOffset = (lastTop === 20) ? 8 : 20;
            }
            lastLeft = bLeft;
            lastTop = topOffset;

            const badCount = b.bad !== undefined ? b.bad : (b.fail !== undefined ? b.fail : 0);

            branchPointsHtml += `
                <div class="cei-distrib-branch-top" style="left: ${bLeft}%; top: ${topOffset}px;" title="${b.name}: ${b.value}% (Total: ${(b.total || 0).toLocaleString()}, Bad: ${badCount.toLocaleString()})">
                    <div class="cei-branch-text">
                        <span class="cei-branch-name">${b.name}</span>
                        <span class="cei-branch-val" style="color: ${valColor};">${b.value}%</span>
                    </div>
                    <div class="cei-branch-dot" style="background: ${dotColor}; margin-top: ${topOffset === 8 ? '16px' : '4px'};"></div>
                </div>
            `;
        });

        // Numerical Axis Ticks along bottom of track
        let ticksHtml = '';
        for (let tickVal = Math.ceil(minScale); tickVal <= Math.floor(maxScale); tickVal++) {
            const tickLeft = getLeftPct(tickVal);
            ticksHtml += `
                <div class="cei-distrib-tick" style="left: ${tickLeft}%;">
                    <div class="cei-distrib-tick-line"></div>
                    <span>${tickVal}</span>
                </div>
            `;
        }

        // PUMA Marker — Strictly at BOTTOM
        const isPumaPass = (pumaPct || 94.48) >= target;
        const pumaColor = isPumaPass ? '#16a34a' : '#dc2626';

        wrap.innerHTML = `
            <!-- Dual-colored track (soft red on left of target, soft green on right) -->
            <div class="cei-distrib-track">
                <div class="cei-distrib-track-fail" style="width: ${targetLeft}%;"></div>
                <div class="cei-distrib-track-pass"></div>
            </div>

            <!-- Target Label on TOP & dashed line extending directly beneath it down across track -->
            <div class="cei-distrib-target-label" style="left: ${targetLeft}%;">Target ${target}%</div>
            <div class="cei-distrib-target-line" style="left: ${targetLeft}%;"></div>

            <!-- All Branch Markers on TOP -->
            ${branchPointsHtml}

            <!-- Axis Ticks below track -->
            <div class="cei-distrib-ticks">
                ${ticksHtml}
            </div>

            <!-- PUMA Marker on BOTTOM -->
            <div class="cei-distrib-puma-bottom" style="left: ${pumaLeft}%;" title="PUMA Regional: ${pumaPct}%">
                <div style="width:0; height:0; border-left:5px solid transparent; border-right:5px solid transparent; border-bottom:6px solid ${pumaColor}; margin-bottom:2px;"></div>
                <div class="cei-puma-pill" style="color:${pumaColor}; border-color:${pumaColor};">
                    PUMA ${pumaPct}%
                </div>
            </div>
        `;

        // Fill Branch Summary Mini-Cards Row (Matching RHI Subpage)
        const statRow = document.getElementById('branchStatRow');
        if (statRow && branchList.length) {
            statRow.innerHTML = branchList.map(b => {
                const isMet = b.value >= target;
                const badgeClass = isMet ? 'badge-pass' : 'badge-fail';
                const badgeText = isMet ? 'Pass' : 'Below';
                const badCount = b.bad !== undefined ? b.bad : (b.fail !== undefined ? b.fail : 0);
                return `
                    <div class="cei-branch-chip">
                        <div class="cei-branch-chip-hdr">
                            <span class="cei-branch-chip-name">${b.name}</span>
                            <span class="${badgeClass}">${b.value}% (${badgeText})</span>
                        </div>
                        <div class="cei-branch-chip-sub">
                            <span>${(b.total || 0).toLocaleString()} cells</span>
                            <span style="color:#ef4444; font-weight:700;">${badCount.toLocaleString()} bad</span>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    async function loadKqiCards() {
        const ywElem = document.getElementById('gaugeWeek');
        const yw = ywElem ? ywElem.value : '';
        const grid = document.getElementById('kqiCardsGrid');
        if (!grid) return;
        grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:16px; opacity:0.6;"><i class="fas fa-spinner fa-spin"></i> Loading KQIs...</div>';

        try {
            const res = await fetch(`/api/sow/cei/kqi-cards?weeknum=${yw}&cell_filter=${currentKqiCellFilter}`);
            const data = await res.json();
            if (data.status !== 'success' || !data.cards) {
                grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; opacity:0.6;">No KQI data available</div>';
                return;
            }

            grid.innerHTML = '';
            data.cards.forEach(k => {
                const card = document.createElement('div');
                card.className = 'cei-kqi-card';
                const color = KQI_COLORS[k.id] || '#0F3B66';
                card.style.borderTopColor = color;

                const val = k.value !== undefined && k.value !== null ? k.value : (k.avg_hit_days !== undefined ? k.avg_hit_days : 0);
                const impacted = k.hit_cells !== undefined && k.hit_cells !== null ? k.hit_cells : (k.affected_cells !== undefined ? k.affected_cells : 0);
                const isBreached = k.is_better === false;

                let deltaHtml = '';
                if (k.delta !== null && k.delta !== undefined) {
                    const isGoodDelta = k.is_better;
                    const deltaColor = isGoodDelta ? '#10b981' : '#ef4444';
                    const arrow = k.delta < 0 ? '▼' : (k.delta > 0 ? '▲' : '–');
                    deltaHtml = `<span style="color:${deltaColor}; font-weight:700; font-size:10px;">${arrow} ${Math.abs(k.delta)}</span>`;
                }

                card.innerHTML = `
                    <div class="cei-kqi-name" title="${k.title}">
                        <i class="fas fa-circle" style="color:${color}; font-size:7px;"></i> ${k.title}
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:baseline; margin-top:1px;">
                        <div class="cei-kqi-val" style="color:${isBreached ? '#ef4444' : color};">
                            ${val}
                        </div>
                        ${deltaHtml}
                    </div>
                    <div class="cei-kqi-sub">
                        <span>Avg hit days/cell</span>
                    </div>
                    <div class="cei-kqi-impact">
                        <span>Impacted:</span>
                        <strong style="color:var(--text-main);">${impacted.toLocaleString()}</strong>
                    </div>
                `;
                grid.appendChild(card);
            });
        } catch (e) {
            console.error('Error loading KQI cards:', e);
            grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:#ef4444;">Failed to load KQI cards</div>';
        }
    }

    // ── Chart 1: CEI Trend Achievement (Matches Ref 1) ──
    async function loadAchievementChart() {
        const startElem = document.getElementById('trendStartWeek');
        const endElem = document.getElementById('trendEndWeek');
        const start = startElem ? startElem.value : '';
        const end = endElem ? endElem.value : '';
        const dom = document.getElementById('achievementChart');
        if (!dom) return;

        if (!achievementChartInstance) {
            achievementChartInstance = echarts.init(dom);
        }
        achievementChartInstance.showLoading({ text: 'Loading achievement chart...', color: '#0F3B66' });

        try {
            const res = await fetch(`/api/sow/cei/achievement?start_yw=${start}&end_yw=${end}`);
            const data = await res.json();
            achievementChartInstance.hideLoading();

            if (data.status !== 'success') return;

            const targetInfoEl = document.getElementById('achTargetInfo');
            if (targetInfoEl) targetInfoEl.textContent = `Target Pass: ${data.target}%`;
            renderAchievementChart(data);
        } catch (e) {
            achievementChartInstance.hideLoading();
            console.error('Error loading achievement chart:', e);
        }
    }

    function renderAchievementChart(data) {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const targetVal = data.target !== null ? data.target : 93.95;

        // Accurate evaluation: check actual achievement against THAT SPECIFIC WEEK's dynamic target
        const goodLineData = (data.good_pct_series || []).map((val, idx) => {
            if (val === null || val === undefined) return null;
            const weekTarget = (data.target_series && data.target_series[idx] !== undefined && data.target_series[idx] !== null)
                ? data.target_series[idx]
                : targetVal;
            const meets = val >= weekTarget;
            return {
                value: val,
                itemStyle: { color: meets ? '#10b981' : '#ef4444' },
                label: {
                    show: true,
                    position: 'top',
                    formatter: `${val}%`,
                    fontSize: 10,
                    fontWeight: 'bold',
                    color: meets ? '#10b981' : '#ef4444',
                    backgroundColor: isDark ? 'rgba(15,23,42,0.85)' : 'rgba(255,255,255,0.92)',
                    padding: [2, 4],
                    borderRadius: 4,
                    borderColor: meets ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)',
                    borderWidth: 1
                }
            };
        });

        const option = {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross' },
                padding: [6, 10],
                textStyle: { fontSize: 11 },
                formatter: function (params) {
                    if (!params || !params.length) return '';
                    const idx = params[0].dataIndex;
                    const weekName = params[0].axisValue;
                    const weekTarget = (data.target_series && data.target_series[idx] !== undefined && data.target_series[idx] !== null)
                        ? data.target_series[idx]
                        : targetVal;
                    let html = `<div style="font-weight:700; margin-bottom:4px; font-size:11px;">${weekName}</div>`;
                    params.forEach(p => {
                        let dotColor = p.color;
                        if (p.seriesName === '% Good Cell') {
                            const val = typeof p.value === 'object' ? p.value.value : p.value;
                            const isPass = val >= weekTarget;
                            dotColor = isPass ? '#10b981' : '#ef4444';
                        }
                        const valDisplay = (typeof p.value === 'object' && p.value !== null) ? p.value.value : p.value;
                        html += `<div style="font-size:10.5px; line-height:1.5;"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${dotColor};margin-right:5px;"></span>${p.seriesName}: <strong>${valDisplay}</strong></div>`;
                    });
                    return html;
                }
            },
            legend: {
                data: ['Good Cell', 'Bad Cell', '% Good Cell', 'Target Pass'],
                bottom: 0,
                itemWidth: 14,
                itemHeight: 9,
                textStyle: { color: isDark ? '#cbd5e1' : '#334155', fontSize: 10 }
            },
            grid: { top: 32, left: 52, right: 50, bottom: 40 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 10 }
            },
            yAxis: [
                {
                    type: 'value',
                    name: 'Count Cell',
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 10 },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: 9.5,
                        formatter: value => (value >= 1000 ? `${(value / 1000).toFixed(0)}k` : value)
                    },
                    splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' } }
                },
                {
                    type: 'value',
                    name: '% Cell',
                    min: 80,
                    max: 100,
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 10 },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: 9.5,
                        formatter: '{value}%'
                    },
                    splitLine: { show: false }
                }
            ],
            series: [
                {
                    name: 'Good Cell',
                    type: 'bar',
                    stack: 'cells',
                    itemStyle: { color: '#4EBA97' },
                    data: data.good_counts
                },
                {
                    name: 'Bad Cell',
                    type: 'bar',
                    stack: 'cells',
                    itemStyle: { color: '#64748B' },
                    data: data.bad_counts
                },
                {
                    name: '% Good Cell',
                    type: 'line',
                    yAxisIndex: 1,
                    symbol: 'circle',
                    symbolSize: 6,
                    itemStyle: { color: '#0284c7' },
                    lineStyle: { width: 2.5, color: '#0284c7' },
                    data: goodLineData
                },
                {
                    name: 'Target Pass',
                    type: 'line',
                    yAxisIndex: 1,
                    symbol: 'none',
                    itemStyle: { color: '#ef4444' },
                    lineStyle: { type: 'dashed', width: 2, color: '#ef4444' },
                    data: data.target_series || []
                }
            ]
        };

        achievementChartInstance.setOption(option, true);
        achievementChartInstance.resize();
    }

    // Cache of fetched trend data to allow instant toggle without re-fetching
    let cachedTrendData = {};

    // ── Chart 2: KQI Trend & % Good Cell (Monochrome Blue Palette matching Image 3) ──
    async function loadTrendChart() {
        const startElem = document.getElementById('trendStartWeek');
        const endElem = document.getElementById('trendEndWeek');
        const start = startElem ? startElem.value : '';
        const end = endElem ? endElem.value : '';
        const dom = document.getElementById('trendChart');
        if (!dom) return;

        const cacheKey = `${start}_${end}_${currentTrendCellFilter}_${currentTrendMetricType}`;
        if (cachedTrendData[cacheKey]) {
            renderTrendChart(cachedTrendData[cacheKey]);
            return;
        }

        if (!trendChartInstance) {
            trendChartInstance = echarts.init(dom);
        }
        trendChartInstance.showLoading({ text: 'Loading trend data...', color: '#0F3B66' });

        try {
            const res = await fetch(`/api/sow/cei/trend?start_yw=${start}&end_yw=${end}&cell_filter=${currentTrendCellFilter}&metric_type=${currentTrendMetricType}`);
            const data = await res.json();
            trendChartInstance.hideLoading();

            if (data.status !== 'success') return;
            cachedTrendData[cacheKey] = data;
            renderTrendChart(data);
        } catch (e) {
            trendChartInstance.hideLoading();
            console.error('Error loading trend chart:', e);
        }
    }

    function renderTrendChart(data) {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const targetVal = data.target !== null ? data.target : 93.95;

        // Monochrome Blue sequential palette (Image 3 reference: deep navy -> ocean -> cerulean -> pastel ice blue)
        const KQI_MONOCHROME_BLUES = [
            '#0E4B75', // Layer 1 (Bottom): Deep Navy Blue
            '#186899', // Layer 2: Dark Ocean Blue
            '#2685B8', // Layer 3: Steel Blue
            '#47A1CD', // Layer 4: Soft Cerulean Blue
            '#68B4DC', // Layer 5: Sky Blue
            '#8EC7E6', // Layer 6: Light Ice Blue
            '#B8DCF0'  // Layer 7 (Top): Pastel Ice Blue
        ];

        const series = [];

        const kqiList = Array.isArray(data.kqi_series_list) ? data.kqi_series_list :
                        (Array.isArray(data.kqi_series) ? data.kqi_series :
                        (data.kqi_defs || []).map(k => ({
                            id: k.id,
                            title: k.title,
                            data: (data.kqi_series && data.kqi_series[k.id]) || []
                        })));

        kqiList.forEach((k, idx) => {
            const isTop = (idx === kqiList.length - 1);
            series.push({
                name: k.title,
                type: 'bar',
                stack: 'kqi',
                emphasis: { focus: 'series' },
                itemStyle: {
                    color: KQI_MONOCHROME_BLUES[idx % KQI_MONOCHROME_BLUES.length],
                    borderRadius: isTop ? [3, 3, 0, 0] : [0, 0, 0, 0]
                },
                data: k.data || []
            });
        });

        // % Good Cell Line with dynamic Green/Red labels evaluated against that week's dynamic target
        const goodLineData = (data.good_pct_series || []).map((val, idx) => {
            if (val === null || val === undefined) return null;
            const weekTarget = (data.target_series && data.target_series[idx] !== undefined && data.target_series[idx] !== null)
                ? data.target_series[idx]
                : targetVal;
            const meets = val >= weekTarget;
            return {
                value: val,
                itemStyle: { color: meets ? '#16803C' : '#DC2626' },
                label: {
                    show: true,
                    position: 'top',
                    formatter: `${val}%`,
                    fontSize: 10,
                    fontWeight: 'bold',
                    color: meets ? '#16803C' : '#DC2626',
                    backgroundColor: isDark ? 'rgba(15,23,42,0.85)' : 'rgba(255,255,255,0.92)',
                    padding: [2, 4],
                    borderRadius: 4,
                    borderColor: meets ? 'rgba(22,128,60,0.4)' : 'rgba(220,38,38,0.4)',
                    borderWidth: 1
                }
            };
        });

        // Dark Slate / Charcoal Line (matching Ref 3)
        series.push({
            name: '% Good Cell',
            type: 'line',
            yAxisIndex: 1,
            symbol: 'circle',
            symbolSize: 6,
            itemStyle: { color: '#ffffff', borderColor: '#3E4D5B', borderWidth: 2 },
            lineStyle: { width: 2.5, color: '#3E4D5B' },
            data: goodLineData
        });

        // Target Pass Line
        series.push({
            name: 'Target Pass',
            type: 'line',
            yAxisIndex: 1,
            symbol: 'none',
            itemStyle: { color: '#DC2626' },
            lineStyle: { type: 'dashed', width: 1.5, color: '#DC2626' },
            data: data.target_series || []
        });

        const yNameLeft = currentTrendMetricType === 'cell_count' ? 'Hit Cell Count' : 'Total Hit Days';

        const option = {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross' },
                padding: [6, 10],
                textStyle: { fontSize: 11 },
                formatter: function (params) {
                    if (!params || !params.length) return '';
                    const idx = params[0].dataIndex;
                    const weekName = params[0].axisValue;
                    const weekTarget = (data.target_series && data.target_series[idx] !== undefined && data.target_series[idx] !== null)
                        ? data.target_series[idx]
                        : targetVal;
                    let html = `<div style="font-weight:700; margin-bottom:4px; font-size:11px;">${weekName}</div>`;
                    params.forEach(p => {
                        let dotColor = p.color;
                        if (p.seriesName === '% Good Cell') {
                            const val = typeof p.value === 'object' ? p.value.value : p.value;
                            const isPass = val >= weekTarget;
                            dotColor = isPass ? '#16803C' : '#DC2626';
                        }
                        const valDisplay = (typeof p.value === 'object' && p.value !== null) ? p.value.value : p.value;
                        html += `<div style="font-size:10.5px; line-height:1.5;"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${dotColor};margin-right:5px;"></span>${p.seriesName}: <strong>${valDisplay}</strong></div>`;
                    });
                    return html;
                }
            },
            legend: {
                bottom: 0,
                itemWidth: 14,
                itemHeight: 9,
                textStyle: { color: isDark ? '#cbd5e1' : '#334155', fontSize: 10 },
                type: 'scroll'
            },
            grid: { top: 32, left: 52, right: 50, bottom: 40 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 10 }
            },
            yAxis: [
                {
                    type: 'value',
                    name: yNameLeft,
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 10 },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: 9.5,
                        formatter: value => (value >= 1000 ? `${(value / 1000).toFixed(0)}k` : value)
                    },
                    splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' } }
                },
                {
                    type: 'value',
                    name: '% Good Cell',
                    min: 80,
                    max: 100,
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 10 },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: 9.5,
                        formatter: '{value}%'
                    },
                    splitLine: { show: false }
                }
            ],
            series: series
        };

        trendChartInstance.setOption(option, true);
        trendChartInstance.resize();
    }

    window.exportCurrentTrend = function (fmt) {
        const start = document.getElementById('trendStartWeek').value;
        const end = document.getElementById('trendEndWeek').value;
        window.location.href = `/api/sow/cei/export?format=${fmt}&start_yw=${start}&end_yw=${end}&cell_filter=${currentTrendCellFilter}`;
    };

    // ══════════════════════════════════════════════════════════════════
    // TAB 2: CEI Geo Trend Logic (Ref 4 Fix: No Overlap)
    // ══════════════════════════════════════════════════════════════════
    async function loadGeoOptions() {
        try {
            const res = await fetch('/api/sow/cei/geo-options');
            geoOptionsData = await res.json();
            if (geoOptionsData.status !== 'success') return;

            const selKab = document.getElementById('geoKabupaten');
            if (selKab) {
                selKab.innerHTML = '<option value="">All Kabupaten</option>';
                (geoOptionsData.kabupaten || []).forEach(k => {
                    const opt = document.createElement('option');
                    opt.value = k;
                    opt.textContent = k;
                    selKab.appendChild(opt);
                });
            }

            // Also populate Table 2 Kabupaten filter dropdown
            const kqiKabSel = document.getElementById('kqiFilterKab');
            if (kqiKabSel) {
                kqiKabSel.innerHTML = '<option value="">All Kabupaten</option>';
                (geoOptionsData.kabupaten || []).forEach(k => {
                    const opt = document.createElement('option');
                    opt.value = k;
                    opt.textContent = k;
                    kqiKabSel.appendChild(opt);
                });
            }

            onGeoKabChange();
            loadGeoTrend();
        } catch (e) {
            console.error('Error loading geo options:', e);
        }
    }

    window.onGeoKabChange = function () {
        const kabElem = document.getElementById('geoKabupaten');
        const kab = kabElem ? kabElem.value : '';
        const selKec = document.getElementById('geoKecamatan');
        if (selKec) {
            selKec.innerHTML = '<option value="">All Kecamatan</option>';

            if (kab && geoOptionsData && geoOptionsData.kecamatan_map && geoOptionsData.kecamatan_map[kab]) {
                geoOptionsData.kecamatan_map[kab].forEach(kec => {
                    const opt = document.createElement('option');
                    opt.value = kec;
                    opt.textContent = kec;
                    selKec.appendChild(opt);
                });
            }
        }
        loadGeoTrend();
    };

    window.loadGeoTrend = async function () {
        const kabElem = document.getElementById('geoKabupaten');
        const kecElem = document.getElementById('geoKecamatan');
        const filterElem = document.getElementById('geoCellFilter');
        const metricElem = document.getElementById('geoMetricType');

        const kab = kabElem ? kabElem.value : '';
        const kec = kecElem ? kecElem.value : '';
        const cellFilter = filterElem ? filterElem.value : 'bad';
        const metricType = metricElem ? metricElem.value : 'avg';

        try {
            const res = await fetch(`/api/sow/cei/geo-trend?kabupaten=${encodeURIComponent(kab)}&kecamatan=${encodeURIComponent(kec)}&cell_filter=${cellFilter}&metric_type=${metricType}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            renderGeoSummary(data.summary);
            renderGeoGoodPctChart(data);
            renderGeoKqiGrid(data);
        } catch (e) {
            console.error('Error loading geo trend:', e);
        }
    };

    function renderGeoSummary(sum) {
        const container = document.getElementById('geoSummaryContainer');
        if (!container || !sum) return;

        const passBadge = sum.is_above
            ? `<span class="badge-pass">(PASS)</span>`
            : `<span class="badge-fail">(NOT PASS)</span>`;

        const wowVal = sum.diff_wow || 0;
        const isWowUp = wowVal >= 0;
        const wowArrow = isWowUp ? '▲' : '▼';
        const wowClass = isWowUp ? 'val-pos' : 'val-neg';
        const wowDisplay = sum.prev_pct !== null && sum.prev_pct !== undefined
            ? `<span class="${wowClass}">${wowArrow} ${wowVal > 0 ? '+' : ''}${wowVal} pp</span> <span style="font-size:9px; color:var(--text-muted); font-weight:600;">(vs W${String(sum.prev_weeknum).slice(4)})</span>`
            : `-`;

        const targetGap = sum.diff_target || 0;
        const isGapPass = targetGap >= 0;
        const gapClass = isGapPass ? 'val-pos' : 'val-neg';
        const gapDisplay = `<span class="${gapClass}">${targetGap > 0 ? '+' : ''}${targetGap} pp</span> <span style="font-size:9px; color:var(--text-muted); font-weight:600;">(${isGapPass ? 'Pass' : 'Below'})</span>`;

        container.innerHTML = `
            <div class="cei-geo-stat-card">
                <span class="cei-geo-stat-title">Location</span>
                <span class="cei-geo-stat-value" style="font-size:13.5px; font-weight:800; color:#0F3B66;">
                    ${sum.kabupaten} ${sum.kecamatan !== 'All' ? `/ ${sum.kecamatan}` : ''}
                </span>
            </div>
            <div class="cei-geo-stat-card">
                <span class="cei-geo-stat-title">Latest Week</span>
                <span class="cei-geo-stat-value">W${String(sum.weeknum).slice(4)}</span>
            </div>
            <div class="cei-geo-stat-card">
                <span class="cei-geo-stat-title">Total Cells</span>
                <span class="cei-geo-stat-value" style="color:#0F3B66;">${(sum.total || 0).toLocaleString()}</span>
            </div>
            <div class="cei-geo-stat-card">
                <span class="cei-geo-stat-title">Good / Bad Cells</span>
                <div class="cei-geo-stat-value" style="font-size:14px; gap:4px;">
                    <span style="color:#10b981;">${(sum.good || 0).toLocaleString()}</span>
                    <span style="font-size:11px; color:var(--text-muted);">/</span>
                    <span style="color:#ef4444;">${(sum.bad || 0).toLocaleString()}</span>
                </div>
            </div>
            <div class="cei-geo-stat-card">
                <span class="cei-geo-stat-title">% Good Cell</span>
                <div class="cei-geo-stat-value" style="font-size:15px;">
                    ${sum.pct}% ${passBadge}
                </div>
            </div>
            <div class="cei-geo-stat-card">
                <span class="cei-geo-stat-title">Target (${sum.quarter || 'Q3'})</span>
                <div class="cei-geo-stat-value" style="font-size:14px;">
                    ${sum.target}% <span style="font-size:10.5px;">${gapDisplay}</span>
                </div>
            </div>
            <div class="cei-geo-stat-card">
                <span class="cei-geo-stat-title">WoW Momentum</span>
                <div class="cei-geo-stat-value" style="font-size:14px;">
                    ${wowDisplay}
                </div>
            </div>
        `;
    }

    function renderGeoGoodPctChart(data) {
        const dom = document.getElementById('geoGoodPctChart');
        if (!dom) return;
        if (!geoGoodPctChartInstance) {
            geoGoodPctChartInstance = echarts.init(dom);
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const targetVal = data.summary ? data.summary.target : 93.95;

        // Dynamic Y-Axis based on actual data points and target threshold
        const validVals = (data.good_pct_series || []).filter(v => typeof v === 'number' && !isNaN(v));
        const allCompareVals = validVals.concat([targetVal]);
        let dMin = allCompareVals.length ? Math.floor(Math.min(...allCompareVals) - 2) : 80;
        let dMax = allCompareVals.length ? Math.ceil(Math.max(...allCompareVals) + 2) : 100;
        dMin = Math.max(0, dMin);
        dMax = Math.min(100, dMax);
        if (dMax - dMin < 6) {
            dMin = Math.max(0, dMin - 2);
            dMax = Math.min(100, dMax + 2);
        }

        const goodLineData = (data.good_pct_series || []).map((val, idx) => {
            if (val === null || val === undefined) return null;
            const weekTarget = (data.target_series && data.target_series[idx] !== undefined && data.target_series[idx] !== null)
                ? data.target_series[idx]
                : targetVal;
            const meets = val >= weekTarget;
            return {
                value: val,
                itemStyle: { color: meets ? '#10b981' : '#ef4444' },
                label: {
                    show: true,
                    position: 'top',
                    formatter: `${val}%`,
                    fontSize: 9,
                    fontWeight: 'bold',
                    color: meets ? '#10b981' : '#ef4444'
                }
            };
        });

        const option = {
            tooltip: {
                trigger: 'axis',
                padding: [6, 10],
                textStyle: { fontSize: 11 },
                formatter: function (params) {
                    if (!params || !params.length) return '';
                    const idx = params[0].dataIndex;
                    const weekName = params[0].axisValue;
                    const weekTarget = (data.target_series && data.target_series[idx] !== undefined && data.target_series[idx] !== null)
                        ? data.target_series[idx]
                        : targetVal;
                    let html = `<div style="font-weight:700; margin-bottom:4px; font-size:11px;">${weekName}</div>`;
                    params.forEach(p => {
                        let dotColor = p.color;
                        if (p.seriesName === '% Good Cell') {
                            const val = typeof p.value === 'object' ? p.value.value : p.value;
                            const isPass = val >= weekTarget;
                            dotColor = isPass ? '#10b981' : '#ef4444';
                        }
                        const valDisplay = (typeof p.value === 'object' && p.value !== null) ? p.value.value : p.value;
                        html += `<div style="font-size:10.5px; line-height:1.5;"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${dotColor};margin-right:5px;"></span>${p.seriesName}: <strong>${valDisplay}</strong></div>`;
                    });
                    return html;
                }
            },
            legend: {
                data: ['% Good Cell', 'Target Pass'],
                bottom: 0,
                itemWidth: 14,
                itemHeight: 9,
                textStyle: { color: isDark ? '#cbd5e1' : '#334155', fontSize: 10 }
            },
            grid: { top: 20, left: 42, right: 28, bottom: 32 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 9.5, interval: 3 }
            },
            yAxis: {
                type: 'value',
                min: dMin,
                max: dMax,
                axisLabel: {
                    color: isDark ? '#94a3b8' : '#64748b',
                    fontSize: 9.5,
                    formatter: '{value}%'
                },
                splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' } }
            },
            series: [
                {
                    name: '% Good Cell',
                    type: 'line',
                    smooth: true,
                    symbol: 'circle',
                    symbolSize: 6,
                    itemStyle: { color: '#10b981' },
                    lineStyle: { width: 2.5, color: '#10b981' },
                    data: goodLineData
                },
                {
                    name: 'Target Pass',
                    type: 'line',
                    symbol: 'none',
                    itemStyle: { color: '#ef4444' },
                    lineStyle: { type: 'dashed', width: 2, color: '#ef4444' },
                    data: data.target_series || []
                }
            ]
        };

        geoGoodPctChartInstance.setOption(option, true);
        geoGoodPctChartInstance.resize();
    }

    // ── 7 KQIs Breakdown in Geo Tab (Fixed Symmetrical Grid & Sizing) ──
    function renderGeoKqiGrid(data) {
        const grid = document.getElementById('geoKqiGrid');
        if (!grid) return;

        // Dispose previous instances cleanly
        geoKqiInstances.forEach(c => {
            if (c && typeof c.dispose === 'function') {
                try { c.dispose(); } catch (e) {}
            }
        });
        geoKqiInstances = [];

        grid.innerHTML = '';
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

        // 1. Build DOM structure for all 8 cards FIRST so layout measurements are 100% computed
        const cardDoms = [];
        (data.kqi_defs || []).forEach(k => {
            const card = document.createElement('div');
            card.className = 'cei-kqi-chart-card';

            const color = KQI_COLORS[k.id] || '#0F3B66';
            card.innerHTML = `
                <div style="font-size:12px; font-weight:700; margin-bottom:8px; display:flex; align-items:center; gap:6px; color:var(--text-main);">
                    <i class="fas fa-circle" style="color:${color}; font-size:9px;"></i> ${k.title}
                </div>
                <div id="geo_kqi_${k.id}" style="height:190px; width:100%; min-height:190px;"></div>
            `;
            grid.appendChild(card);
            cardDoms.push({ def: k, color: color, chartDomId: `geo_kqi_${k.id}` });
        });

        // 8th Summary Card to complete the 4x2 grid cleanly
        const summaryCard = document.createElement('div');
        summaryCard.className = 'cei-kqi-chart-card';
        
        const sum = data.summary || {};
        const latestW = sum.weeknum ? `W${String(sum.weeknum).slice(4)}` : (data.labels && data.labels.length ? data.labels[data.labels.length - 1] : 'Latest');
        const locName = sum.kabupaten ? `${sum.kabupaten}${sum.kecamatan && sum.kecamatan !== 'All' ? ' / ' + sum.kecamatan : ''}` : 'Regional Overview';

        summaryCard.innerHTML = `
            <div>
                <div style="font-size:12px; font-weight:700; margin-bottom:8px; display:flex; align-items:center; gap:6px; color:#0F3B66;">
                    <i class="fas fa-layer-group"></i> 7 KQIs Performance Summary
                </div>
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:12px;">
                    Location: <strong>${locName}</strong> (${latestW})
                </div>
                <div style="display:flex; flex-direction:column; gap:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; padding:6px 8px; background:rgba(15,59,102,0.04); border-radius:6px;">
                        <span>Active Monitoring:</span>
                        <strong style="color:#0F3B66;">7 KQIs Tracked</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; padding:6px 8px; background:rgba(16,185,129,0.08); border-radius:6px;">
                        <span>% Good Cell Status:</span>
                        <strong style="color:${sum.is_above ? '#10b981' : '#ef4444'};">${sum.pct || 0}% ${sum.is_above ? '(PASS)' : '(BELOW)'}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; padding:6px 8px; background:rgba(0,0,0,0.03); border-radius:6px;">
                        <span>Impacted Cell Ratio:</span>
                        <strong>${(sum.bad || 0).toLocaleString()} / ${(sum.total || 0).toLocaleString()}</strong>
                    </div>
                </div>
            </div>
            <div style="margin-top:10px; font-size:10px; color:var(--text-muted); text-align:right;">
                <i class="fas fa-info-circle"></i> Weekly Trend Analysis W01–${latestW}
            </div>
        `;
        grid.appendChild(summaryCard);

        // 2. NOW initialize ECharts on each already-measured container
        cardDoms.forEach(item => {
            const cDom = document.getElementById(item.chartDomId);
            if (!cDom) return;
            const chart = echarts.init(cDom);
            geoKqiInstances.push(chart);

            const seriesData = (data.kqi_series && data.kqi_series[item.def.id]) || [];

            chart.setOption({
                tooltip: {
                    trigger: 'axis',
                    confine: true, // Keep tooltip inside canvas
                    backgroundColor: isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.98)',
                    borderColor: isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(0, 0, 0, 0.12)',
                    borderWidth: 1,
                    padding: [6, 10],
                    textStyle: {
                        color: isDark ? '#f8fafc' : '#0f172a',
                        fontSize: 11,
                        fontWeight: '600'
                    },
                    formatter: function (params) {
                        if (!params || !params.length) return '';
                        const p = params[0];
                        return `<div style="font-size:10.5px; line-height:1.4;"><strong>${p.name}</strong><br/><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${item.color};margin-right:4px;"></span>${item.def.title}: <strong>${p.value}</strong></div>`;
                    }
                },
                grid: { top: 14, bottom: 22, left: 36, right: 14 },
                xAxis: {
                    type: 'category',
                    data: data.labels,
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: 8.5,
                        interval: 3 // Clean interval spacing so dates never collide
                    }
                },
                yAxis: {
                    type: 'value',
                    axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: 8.5 },
                    splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' } }
                },
                series: [
                    {
                        name: item.def.title,
                        type: 'line',
                        smooth: true,
                        itemStyle: { color: item.color },
                        lineStyle: { width: 2, color: item.color },
                        areaStyle: {
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                { offset: 0, color: item.color + '40' },
                                { offset: 1, color: item.color + '00' }
                            ])
                        },
                        data: seriesData
                    }
                ]
            });
        });

        // 3. Ensure exact responsive rendering
        requestAnimationFrame(() => {
            geoKqiInstances.forEach(c => { if (c) c.resize(); });
        });
        setTimeout(() => {
            geoKqiInstances.forEach(c => { if (c) c.resize(); });
        }, 80);
    }

    // ══════════════════════════════════════════════════════════════════
    // TAB 3: Comparison Tables Logic (NOP + 7 KQI + Kabupaten WoW)
    // ══════════════════════════════════════════════════════════════════
    window.loadComparison = async function () {
        const compElem = document.getElementById('compWeek');
        const yw = compElem ? compElem.value : '';

        const branchFilter = document.getElementById('kqiFilterBranch')?.value || 'ALL';
        const kabFilter = document.getElementById('kqiFilterKab')?.value || '';
        const kecFilter = document.getElementById('kqiFilterKec')?.value || '';

        try {
            const res = await fetch(`/api/sow/cei/comparison?weeknum=${yw}&branch=${encodeURIComponent(branchFilter)}&kabupaten=${encodeURIComponent(kabFilter)}&kecamatan=${encodeURIComponent(kecFilter)}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            // Target badge & header label
            const tgtDisplay = document.getElementById('compTargetDisplay');
            if (tgtDisplay) tgtDisplay.textContent = `Target: ${data.target}%`;

            const compLabel = document.getElementById('compWeekLabel');
            if (compLabel) compLabel.textContent = `Comparing W${String(data.prev_week).slice(4)} vs W${String(data.curr_week).slice(4)}`;

            // Update Table Headers
            const thPrev = document.getElementById('thPrevWeek');
            const thCurr = document.getElementById('thCurrWeek');
            const thBefore = document.getElementById('thKqiBefore');
            const thAfter = document.getElementById('thKqiAfter');
            if (thPrev) thPrev.textContent = `${data.prev_week} (W${String(data.prev_week).slice(4)})`;
            if (thCurr) thCurr.textContent = `${data.curr_week} (W${String(data.curr_week).slice(4)})`;
            if (thBefore) thBefore.textContent = `Before (${data.prev_week})`;
            if (thAfter) thAfter.textContent = `After (${data.curr_week})`;

            renderNopTable(data.rows);
            renderKqiWowTable(data.kqi_wow);
        } catch (e) {
            console.error('Error loading comparison data:', e);
        }
    };

    window.onKqiFilterBranchChange = function () {
        const branch = document.getElementById('kqiFilterBranch')?.value || 'ALL';
        const kabSel = document.getElementById('kqiFilterKab');
        const kecSel = document.getElementById('kqiFilterKec');
        if (!kabSel) return;

        kabSel.innerHTML = '<option value="">All Kabupaten</option>';
        if (kecSel) kecSel.innerHTML = '<option value="">All Kecamatan</option>';

        if (geoOptionsData && geoOptionsData.kabupaten) {
            geoOptionsData.kabupaten.forEach(k => {
                if (branch === 'ALL') {
                    const opt = document.createElement('option');
                    opt.value = k;
                    opt.textContent = k;
                    kabSel.appendChild(opt);
                } else if (rawKabupatenData && rawKabupatenData.length) {
                    const match = rawKabupatenData.find(r => r.kabupaten.toUpperCase() === k.toUpperCase() && r.branch.toUpperCase() === branch);
                    if (match) {
                        const opt = document.createElement('option');
                        opt.value = k;
                        opt.textContent = k;
                        kabSel.appendChild(opt);
                    }
                }
            });
        }
        loadComparison();
    };

    window.onKqiFilterKabChange = function () {
        const kab = document.getElementById('kqiFilterKab')?.value || '';
        const kecSel = document.getElementById('kqiFilterKec');
        if (!kecSel) return;
        kecSel.innerHTML = '<option value="">All Kecamatan</option>';

        if (kab && geoOptionsData && geoOptionsData.kecamatan_map && geoOptionsData.kecamatan_map[kab]) {
            geoOptionsData.kecamatan_map[kab].forEach(kec => {
                const opt = document.createElement('option');
                opt.value = kec;
                opt.textContent = kec;
                kecSel.appendChild(opt);
            });
        }
        loadComparison();
    };

    function renderNopTable(rows) {
        const tbody = document.querySelector('#nopTable tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        (rows || []).forEach(r => {
            const tr = document.createElement('tr');
            const isPuma = r.nop === 'PUMA';
            if (isPuma) tr.className = 'row-puma';

            const dtgtClass = r.delta_target >= 0 ? 'val-pos' : 'val-neg';
            const wowVal = r.delta_wow !== undefined ? r.delta_wow : r.ach_wow;
            const wowClass = wowVal >= 0 ? 'val-pos' : 'val-neg';
            const passBadge = r.st_target === 'Pass' ? 'badge-pass' : 'badge-fail';

            let wowBadge = 'badge-pass';
            if (r.st_wow === 'Degraded') wowBadge = 'badge-fail';
            else if (r.st_wow === 'Stable') wowBadge = 'badge-pass';

            tr.innerHTML = `
                <td style="font-weight:700;">${r.nop}</td>
                <td>${r.target}%</td>
                <td>${(r.prev_total || 0).toLocaleString()}</td>
                <td>${(r.prev_good || 0).toLocaleString()}</td>
                <td>${(r.prev_bad || 0).toLocaleString()}</td>
                <td style="font-weight:600;">${r.prev_ach}%</td>
                <td>${(r.curr_total || 0).toLocaleString()}</td>
                <td>${(r.curr_good || 0).toLocaleString()}</td>
                <td>${(r.curr_bad || 0).toLocaleString()}</td>
                <td style="font-weight:700;">${r.curr_ach}%</td>
                <td class="${dtgtClass}">${r.delta_target > 0 ? '+' : ''}${r.delta_target}%</td>
                <td class="${wowClass}">${wowVal > 0 ? '+' : ''}${wowVal}%</td>
                <td><span class="${passBadge}">${r.st_target}</span></td>
                <td><span class="${wowBadge}">${r.st_wow}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }

    function renderKqiWowTable(kqiRows) {
        const tbody = document.querySelector('#kqiTable tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        (kqiRows || []).forEach(k => {
            const tr = document.createElement('tr');
            const isImprove = k.remark === 'Improve';
            const remBadge = isImprove ? 'badge-pass' : 'badge-fail';
            const deltaClass = k.delta <= 0 ? 'val-pos' : 'val-neg';

            if (!isImprove && (k.delta_pct > 20 || k.id === 'game_jitter')) {
                tr.className = 'highlight-degrade';
            }

            tr.innerHTML = `
                <td style="text-align:left; padding-left:16px; font-weight:600;">
                    <i class="fas fa-circle" style="color:${KQI_COLORS[k.id] || '#64748b'}; font-size:8px; margin-right:6px;"></i>${k.title}
                </td>
                <td>${(k.before || 0).toLocaleString()}</td>
                <td>${(k.after || 0).toLocaleString()}</td>
                <td class="${deltaClass}">${k.delta > 0 ? '+' : ''}${(k.delta || 0).toLocaleString()}</td>
                <td class="${deltaClass}">${k.delta_pct > 0 ? '+' : ''}${k.delta_pct}%</td>
                <td><span class="${remBadge}">${k.remark}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }

    // ── Table 3: Kabupaten Level WoW Comparison Table ──
    window.loadKabupatenComparison = async function () {
        const compElem = document.getElementById('compWeek');
        const yw = compElem ? compElem.value : '';
        const branchFilter = document.getElementById('kabFilterBranch').value;
        const kqiFilter = document.getElementById('kabFilterKqi').value;

        try {
            const res = await fetch(`/api/sow/cei/comparison-kabupaten?weeknum=${yw}&branch=${encodeURIComponent(branchFilter)}&kqi=${encodeURIComponent(kqiFilter)}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            rawKabupatenData = data.rows || [];
            renderKabupatenTable(rawKabupatenData, kqiFilter);
        } catch (e) {
            console.error('Error loading Kabupaten comparison:', e);
        }
    };

    function renderKabupatenTable(rows, kqiFilter) {
        const tbody = document.querySelector('#kabupatenTable tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        const thKqi = document.getElementById('thKabKqiColumn');
        if (thKqi) {
            if (kqiFilter && kqiFilter !== 'ALL') {
                const kqiTitles = {
                    web_rtt: 'Web RTT WoW',
                    web_ul_retrans: 'Web Retrans WoW',
                    video_vxb: 'Video Start WoW',
                    voip_ul: 'VoIP UL WoW',
                    voip_dl: 'VoIP DL WoW',
                    game_rtt: 'Game RTT WoW',
                    game_jitter: 'Game Jitter WoW'
                };
                thKqi.textContent = kqiTitles[kqiFilter] || 'KQI WoW';
            } else {
                thKqi.textContent = 'Overall Status';
            }
        }

        (rows || []).forEach(r => {
            const tr = document.createElement('tr');
            const dtgtClass = r.delta_target >= 0 ? 'val-pos' : 'val-neg';
            const wowClass = r.ach_wow >= 0 ? 'val-pos' : 'val-neg';
            const passBadge = r.st_target === 'Pass' ? 'badge-pass' : 'badge-fail';

            let wowBadge = 'badge-pass';
            if (r.st_wow === 'Degraded') wowBadge = 'badge-fail';
            else if (r.st_wow === 'Stable') wowBadge = 'badge-pass';

            let kqiCellHtml = '';
            if (kqiFilter && kqiFilter !== 'ALL' && r.kqis && r.kqis[kqiFilter]) {
                const kData = r.kqis[kqiFilter];
                const kRemBadge = kData.remark === 'Improve' ? 'badge-pass' : 'badge-fail';
                const dClass = kData.delta <= 0 ? 'val-pos' : 'val-neg';
                kqiCellHtml = `
                    <div style="display:flex; align-items:center; justify-content:flex-end; gap:6px;">
                        <span>${(kData.before || 0).toLocaleString()} → <strong>${(kData.after || 0).toLocaleString()}</strong></span>
                        <span class="${dClass}">(${kData.delta > 0 ? '+' : ''}${kData.delta})</span>
                        <span class="${kRemBadge}">${kData.remark}</span>
                    </div>
                `;
            } else {
                kqiCellHtml = `<span class="${passBadge}">${r.st_target}</span>`;
            }

            // Branch first, then Kabupaten (per user instruction)
            tr.innerHTML = `
                <td style="font-weight:600; color:var(--text-main); text-align:left; padding-left:14px;">${r.branch}</td>
                <td style="text-align:left; padding-left:14px; font-weight:700;">${r.kabupaten}</td>
                <td>${r.target}%</td>
                <td>${r.prev_ach}%</td>
                <td style="font-weight:700;">${r.curr_ach}%</td>
                <td class="${dtgtClass}">${r.delta_target > 0 ? '+' : ''}${r.delta_target}%</td>
                <td class="${wowClass}">${r.ach_wow > 0 ? '+' : ''}${r.ach_wow}%</td>
                <td><span class="${passBadge}">${r.st_target}</span></td>
                <td><span class="${wowBadge}">${r.st_wow}</span></td>
                <td style="text-align:right; padding-right:14px;">${kqiCellHtml}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    window.filterKabupatenTable = function () {
        const query = (document.getElementById('kabSearchInput').value || '').trim().toUpperCase();
        const kqiFilter = document.getElementById('kabFilterKqi').value;
        if (!query) {
            renderKabupatenTable(rawKabupatenData, kqiFilter);
            return;
        }
        const filtered = rawKabupatenData.filter(r => r.kabupaten.toUpperCase().includes(query) || r.branch.toUpperCase().includes(query));
        renderKabupatenTable(filtered, kqiFilter);
    };

    // ══════════════════════════════════════════════════════════════════
    // Import Modal Handlers (same flow as Redcoverage import)
    // ══════════════════════════════════════════════════════════════════
    // Multi-File Batch Queue Importer for CEI
    // ══════════════════════════════════════════════════════════════════
    let ceiFileQueue = [];
    let isCeiQueueRunning = false;
    let ceiQueueAborted = false;

    window.openCeiImportModal = function () {
        const m = document.getElementById('ceiImportModal');
        if (m) m.style.display = 'flex';
        initCeiDropZoneEvents();
    };

    window.closeCeiImportModal = function () {
        if (isCeiQueueRunning) {
            if (!confirm('An import queue is currently running. Are you sure you want to cancel and close?')) {
                return;
            }
            ceiQueueAborted = true;
        }
        const m = document.getElementById('ceiImportModal');
        if (m) m.style.display = 'none';
        resetCeiImportState();
    };

    function resetCeiImportState() {
        ceiFileQueue = [];
        isCeiQueueRunning = false;
        ceiQueueAborted = false;
        const fileInput = document.getElementById('ceiFileInput');
        if (fileInput) fileInput.value = '';
        renderCeiQueueUI();
        const alertBox = document.getElementById('ceiImportAlert');
        if (alertBox) alertBox.style.display = 'none';
        const prog = document.getElementById('ceiQueueOverallProgress');
        if (prog) prog.style.display = 'none';
    }

    window.clearCeiQueue = function () {
        if (isCeiQueueRunning) return;
        resetCeiImportState();
    };

    function initCeiDropZoneEvents() {
        const dropZone = document.getElementById('ceiDropZone');
        if (!dropZone || dropZone._hasEvents) return;
        dropZone._hasEvents = true;

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.background = 'rgba(15, 59, 102, 0.08)';
                dropZone.style.borderColor = '#0F3B66';
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
                addFilesToCeiQueue(dt.files);
            }
        }, false);
    }

    window.handleCeiFileSelect = function (input) {
        if (input.files && input.files.length) {
            addFilesToCeiQueue(input.files);
            input.value = '';
        }
    };

    function addFilesToCeiQueue(files) {
        if (isCeiQueueRunning) return;
        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const ext = f.name.toLowerCase().split('.').pop();
            if (!['xlsx', 'xls', 'csv'].includes(ext)) {
                continue;
            }
            if (ceiFileQueue.some(item => item.name === f.name && item.size === f.size)) {
                continue;
            }
            ceiFileQueue.push({
                id: 'cei_q_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
                file: f,
                name: f.name,
                size: f.size,
                status: 'pending',
                message: 'Queued',
                pct: 0,
                rows: 0,
                weeks: []
            });
        }
        renderCeiQueueUI();
    }

    function renderCeiQueueUI() {
        const sec = document.getElementById('ceiQueueSection');
        const list = document.getElementById('ceiQueueListContainer');
        const countEl = document.getElementById('ceiQueueTotalCount');
        const sizeEl = document.getElementById('ceiQueueTotalSize');
        const btnCount = document.getElementById('ceiQueueBtnCount');
        const submitBtn = document.getElementById('ceiImportBtn');
        const addMoreBtn = document.getElementById('btnAddMoreCeiFiles');
        const clearBtn = document.getElementById('btnClearCeiQueue');

        if (!ceiFileQueue.length) {
            if (sec) sec.style.display = 'none';
            if (submitBtn) {
                submitBtn.disabled = true;
                if (btnCount) btnCount.textContent = '0';
            }
            if (addMoreBtn) addMoreBtn.style.display = 'none';
            return;
        }

        if (sec) sec.style.display = 'block';
        if (addMoreBtn) addMoreBtn.style.display = isCeiQueueRunning ? 'none' : 'inline-block';
        if (clearBtn) clearBtn.style.display = isCeiQueueRunning ? 'none' : 'inline-block';

        const totalBytes = ceiFileQueue.reduce((acc, f) => acc + f.size, 0);
        const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);

        if (countEl) countEl.textContent = ceiFileQueue.length;
        if (sizeEl) sizeEl.textContent = `${totalMb} MB`;
        if (btnCount) btnCount.textContent = `${ceiFileQueue.length} files`;

        if (submitBtn) {
            submitBtn.disabled = isCeiQueueRunning || ceiFileQueue.every(f => f.status === 'done');
        }

        if (list) {
            list.innerHTML = ceiFileQueue.map((item, idx) => {
                let badgeHtml = '';
                const sizeMb = (item.size / (1024 * 1024)).toFixed(1);

                if (item.status === 'pending') {
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(0,0,0,0.06); color:var(--text-muted); font-weight:700;">Waiting</span>`;
                } else if (item.status === 'uploading' || item.status === 'processing') {
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(15,59,102,0.12); color:#0F3B66; font-weight:700;">
                        <i class="fas fa-spinner fa-spin"></i> ${item.pct || 0}%
                    </span>`;
                } else if (item.status === 'done') {
                    const wText = (item.weeks && item.weeks.length) ? item.weeks.map(w => 'W' + String(w).slice(4)).join(',') : 'Done';
                    const rText = item.rows ? ` (${item.rows.toLocaleString()} rows)` : '';
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(16,185,129,0.15); color:#10b981; font-weight:700;">
                        <i class="fas fa-check"></i> ${wText}${rText}
                    </span>`;
                } else if (item.status === 'error') {
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(239,68,68,0.15); color:#ef4444; font-weight:700;" title="${item.message}">
                        <i class="fas fa-exclamation-triangle"></i> Error
                    </span>`;
                }

                return `
                    <div id="${item.id}" style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; background:#ffffff; border:1px solid var(--border); border-radius:6px; font-size:11.5px;">
                        <div style="display:flex; align-items:center; gap:8px; overflow:hidden; margin-right:8px;">
                            <span style="font-weight:700; color:var(--text-muted); font-size:10px; width:16px;">#${idx + 1}</span>
                            <i class="fas fa-file-excel" style="color:#0F3B66; flex-shrink:0;"></i>
                            <span style="font-weight:700; color:var(--text-main); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${item.name}">${item.name}</span>
                            <span style="color:var(--text-muted); font-size:10.5px; flex-shrink:0;">(${sizeMb} MB)</span>
                        </div>
                        <div style="flex-shrink:0;">
                            ${badgeHtml}
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    window.startCeiQueueImport = async function () {
        if (!ceiFileQueue.length || isCeiQueueRunning) return;

        isCeiQueueRunning = true;
        ceiQueueAborted = false;

        const submitBtn = document.getElementById('ceiImportBtn');
        const addMoreBtn = document.getElementById('btnAddMoreCeiFiles');
        const clearBtn = document.getElementById('btnClearCeiQueue');
        const alertBox = document.getElementById('ceiImportAlert');
        const overallProg = document.getElementById('ceiQueueOverallProgress');
        const overallBar = document.getElementById('ceiOverallProgressBar');
        const overallStage = document.getElementById('ceiOverallStage');
        const overallPct = document.getElementById('ceiOverallPct');
        const curFileStage = document.getElementById('ceiCurrentFileStage');
        const curFilePct = document.getElementById('ceiCurrentFilePct');

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing Queue...';
        }
        if (addMoreBtn) addMoreBtn.style.display = 'none';
        if (clearBtn) clearBtn.style.display = 'none';
        if (alertBox) alertBox.style.display = 'none';
        if (overallProg) overallProg.style.display = 'block';

        let successCount = 0;
        let failCount = 0;
        let totalRowsImported = 0;
        let allWeeksImported = new Set();

        const totalFiles = ceiFileQueue.length;

        for (let i = 0; i < totalFiles; i++) {
            if (ceiQueueAborted) break;

            const item = ceiFileQueue[i];
            if (item.status === 'done') {
                successCount++;
                continue;
            }

            const currentFileNum = i + 1;
            const overallProgressValue = Math.round((i / totalFiles) * 100);

            if (overallStage) overallStage.textContent = `Overall: File ${currentFileNum} of ${totalFiles} (${item.name})`;
            if (overallPct) overallPct.textContent = `${overallProgressValue}%`;
            if (overallBar) overallBar.style.width = `${overallProgressValue}%`;

            item.status = 'uploading';
            item.pct = 10;
            item.message = 'Uploading file...';
            renderCeiQueueUI();

            try {
                const formData = new FormData();
                formData.append('file', item.file);

                if (curFileStage) curFileStage.textContent = `Uploading ${item.name}...`;
                if (curFilePct) curFilePct.textContent = '10%';

                const res = await fetch('/api/sow/cei/import', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                if (data.status === 'queued' && data.job_id) {
                    item.status = 'processing';
                    await new Promise((resolve) => {
                        const poll = setInterval(async () => {
                            if (ceiQueueAborted) {
                                clearInterval(poll);
                                resolve();
                                return;
                            }
                            try {
                                const pres = await fetch('/api/sow/cei/import/progress/' + data.job_id);
                                const pdata = await pres.json();

                                if (pdata.status !== 'queued') {
                                    item.pct = pdata.pct || 15;
                                    item.message = pdata.message || pdata.status;
                                    if (curFileStage) curFileStage.textContent = `${item.name}: ${pdata.message || pdata.status}`;
                                    if (curFilePct) curFilePct.textContent = `${pdata.pct || 0}%`;
                                    renderCeiQueueUI();
                                }

                                if (pdata.status === 'success') {
                                    clearInterval(poll);
                                    item.status = 'done';
                                    item.pct = 100;
                                    item.rows = pdata.rows_imported || 0;
                                    item.weeks = pdata.weeks || [];
                                    item.message = pdata.message;
                                    successCount++;
                                    totalRowsImported += (pdata.rows_imported || 0);
                                    (pdata.weeks || []).forEach(w => allWeeksImported.add(w));
                                    renderCeiQueueUI();
                                    resolve();
                                } else if (pdata.status === 'error') {
                                    clearInterval(poll);
                                    item.status = 'error';
                                    item.message = pdata.message || 'Import error';
                                    failCount++;
                                    renderCeiQueueUI();
                                    resolve();
                                }
                            } catch (e) {
                                // transient poll error
                            }
                        }, 500);

                        setTimeout(() => {
                            clearInterval(poll);
                            if (item.status !== 'done') {
                                item.status = 'error';
                                item.message = 'Timeout';
                                failCount++;
                                renderCeiQueueUI();
                            }
                            resolve();
                        }, 600000);
                    });
                } else {
                    item.status = 'error';
                    item.message = data.message || 'Upload failed';
                    failCount++;
                    renderCeiQueueUI();
                }
            } catch (err) {
                item.status = 'error';
                item.message = err.message || 'Network error';
                failCount++;
                renderCeiQueueUI();
            }
        }

        if (overallBar) overallBar.style.width = '100%';
        if (overallPct) overallPct.textContent = '100%';
        if (overallStage) overallStage.textContent = `Completed ${successCount} of ${totalFiles} files`;
        if (curFileStage) curFileStage.textContent = 'All files processed.';
        if (curFilePct) curFilePct.textContent = 'Done';

        isCeiQueueRunning = false;
        renderCeiQueueUI();

        if (submitBtn) {
            submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Import Complete';
            submitBtn.disabled = true;
        }

        if (alertBox) {
            alertBox.style.display = 'block';
            if (failCount === 0) {
                alertBox.style.background = 'rgba(16,185,129,0.15)';
                alertBox.style.color = '#10b981';
                const weeksStr = Array.from(allWeeksImported).sort().map(w => 'W' + String(w).slice(4)).join(', ');
                alertBox.innerHTML = `<i class="fas fa-check-circle"></i> <strong>Queue Completed!</strong> Successfully imported ${successCount} files (${totalRowsImported.toLocaleString()} rows) across week(s): ${weeksStr}.`;
            } else {
                alertBox.style.background = 'rgba(234,179,8,0.15)';
                alertBox.style.color = '#ca8a04';
                alertBox.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Processed ${totalFiles} files: <strong>${successCount} succeeded</strong>, <strong>${failCount} failed</strong>. Total rows: ${totalRowsImported.toLocaleString()}.`;
            }
        }

        setTimeout(() => {
            window.location.reload();
        }, 1500);
    };

    // Drag & drop support on the drop zone
    (function () {
        const dz = document.getElementById('ceiDropZone');
        const input = document.getElementById('ceiFileInput');
        if (!dz || !input) return;
        ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => {
            e.preventDefault();
            e.stopPropagation();
            dz.style.borderColor = '#0F3B66';
            dz.style.background = 'rgba(15,59,102,0.06)';
        }));
        ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => {
            e.preventDefault();
            e.stopPropagation();
            dz.style.borderColor = '#475569';
            dz.style.background = 'var(--cei-card-bg, #ffffff)';
        }));
        dz.addEventListener('drop', e => {
            const files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length) {
                const f = files[0];
                const name = (f.name || '').toLowerCase();
                if (!name.endsWith('.csv') && !name.endsWith('.xlsx') && !name.endsWith('.xls')) {
                    const status = document.getElementById('ceiImportStatus');
                    if (status) {
                        status.style.display = 'block';
                        status.style.color = '#ef4444';
                        status.innerHTML = '<i class="fas fa-exclamation-circle"></i> Only CSV and Excel (.xlsx, .xls) files are supported';
                    }
                    return;
                }
                try {
                    const dt = new DataTransfer();
                    dt.items.add(f);
                    input.files = dt.files;
                } catch (err) { /* fallback: click to browse */ }
                handleCeiFileSelect(input);
            }
        });
    })();

    // ══════════════════════════════════════════════════════════════════
    // Modal Chart Enlarge & Save PNG
    // ══════════════════════════════════════════════════════════════════
    let chartEnlargedInstance = null;
    let currentEnlargedType = null;

    window.openChartEnlargeModal = function (type) {
        currentEnlargedType = type;
        const modal = document.getElementById('chartEnlargeModal');
        const titleEl = document.getElementById('enlargeModalTitle');
        const subEl = document.getElementById('enlargeModalSubtitle');
        const container = document.getElementById('enlargedChartContainer');
        if (!modal || !container) return;

        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        if (chartEnlargedInstance) {
            chartEnlargedInstance.dispose();
            chartEnlargedInstance = null;
        }
        chartEnlargedInstance = echarts.init(container);

        let sourceInstance = null;
        let titleText = 'Chart';
        let subText = '';

        if (type === 'branchContrib') {
            sourceInstance = branchContribInstance;
            titleText = 'Branch Performance & Cell Volume Contribution';
            subText = 'Good cells vs bad cells distribution alongside % achievement line';
        } else if (type === 'achievement') {
            sourceInstance = achievementChartInstance;
            titleText = 'CEI Trend Achievement';
            subText = 'Weekly regional CEI achievement against dynamic quarterly targets';
        } else if (type === 'trendChart') {
            sourceInstance = trendChartInstance;
            titleText = 'KQI Trend & % Good Cell';
            subText = 'Monochrome sequential KQI breakdown stacked with regional % good cell';
        } else if (type === 'geoGoodPct') {
            sourceInstance = geoGoodPctChartInstance;
            titleText = '% Good Cell Trend vs Target';
            subText = 'Geographical location performance trend and benchmark compliance';
        }

        if (titleEl) titleEl.innerHTML = `<i class="fas fa-chart-line" style="color:#0F3B66;"></i> ${titleText}`;
        if (subEl) subEl.textContent = subText;

        if (sourceInstance) {
            try {
                const opt = JSON.parse(JSON.stringify(sourceInstance.getOption()));
                if (opt.grid && opt.grid.length) {
                    opt.grid[0].top = 45;
                    opt.grid[0].bottom = 50;
                    opt.grid[0].left = 60;
                    opt.grid[0].right = 60;
                }
                chartEnlargedInstance.setOption(opt);
            } catch (err) {
                console.warn('Could not copy options to enlarge chart:', err);
            }
        }

        setTimeout(() => {
            if (chartEnlargedInstance) chartEnlargedInstance.resize();
        }, 150);
    };

    window.closeChartEnlargeModal = function () {
        const modal = document.getElementById('chartEnlargeModal');
        if (modal) modal.style.display = 'none';
        document.body.style.overflow = '';
        if (chartEnlargedInstance) {
            chartEnlargedInstance.dispose();
            chartEnlargedInstance = null;
        }
    };

    window.downloadEnlargedChart = function () {
        if (!chartEnlargedInstance) return;
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const url = chartEnlargedInstance.getDataURL({
            pixelRatio: 2,
            backgroundColor: isDark ? '#0f172a' : '#ffffff'
        });
        const a = document.createElement('a');
        a.download = `CEI_${currentEnlargedType || 'Chart'}.png`;
        a.href = url;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    // ══════════════════════════════════════════════════════════════════
    // Smart PNG Presentation Export
    // ══════════════════════════════════════════════════════════════════
    window.openSmartPngModal = function () {
        const modal = document.getElementById('smartPngModal');
        if (modal) modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    };

    window.closeSmartPngModal = function () {
        const modal = document.getElementById('smartPngModal');
        if (modal) modal.style.display = 'none';
        document.body.style.overflow = '';
    };

    // ── ECharts-aware clone ──────────────────────────────────────────────
    // ECharts paints into <canvas>, and cloneNode(true) copies the <canvas>
    // element WITHOUT its bitmap — that is why cloned charts exported blank.
    // Replace every chart node in the clone with a real <img> produced by the
    // live instance's getDataURL(), so the capture always has pixels.
    function buildEchartsAwareClone(sourceEl, bgColor) {
        const clone = sourceEl.cloneNode(true);
        if (!window.echarts || typeof echarts.getInstanceByDom !== 'function') return clone;
        const origNodes = [sourceEl].concat(Array.prototype.slice.call(sourceEl.querySelectorAll('*')));
        const cloneNodes = [clone].concat(Array.prototype.slice.call(clone.querySelectorAll('*')));
        for (let i = 0; i < origNodes.length; i++) {
            const orig = origNodes[i];
            if (!orig || orig.nodeType !== 1) continue;
            let inst = null;
            try { inst = echarts.getInstanceByDom(orig); } catch (e) { inst = null; }
            if (!inst) continue;
            const target = cloneNodes[i];
            if (!target || !target.parentNode) continue;
            try {
                const url = inst.getDataURL({
                    type: 'png',
                    pixelRatio: 2,
                    backgroundColor: bgColor || 'transparent'
                });
                const img = document.createElement('img');
                img.src = url;
                const w = orig.clientWidth || orig.offsetWidth || 0;
                const h = orig.clientHeight || orig.offsetHeight || 0;
                img.style.width = w ? (w + 'px') : '100%';
                img.style.height = h ? (h + 'px') : 'auto';
                img.style.display = 'block';
                img.style.maxWidth = '100%';
                target.parentNode.replaceChild(img, target);
            } catch (err) {
                console.warn('Could not rasterize chart for export:', err);
            }
        }
        return clone;
            }

            // Resolve once every <img> inside the capture target is decoded, so
            // html2canvas never snapshots a half-painted rasterized chart.
            function waitForImages(root) {
                if (!root || !root.querySelectorAll) return Promise.resolve();
                const imgs = Array.prototype.slice.call(root.querySelectorAll('img'));
                if (!imgs.length) return Promise.resolve();
                return Promise.all(imgs.map(img => (img.decode && img.complete)
                    ? Promise.resolve()
                    : new Promise(res => {
                        const done = () => res();
                        img.addEventListener('load', done, { once: true });
                        img.addEventListener('error', done, { once: true });
                        setTimeout(done, 1500);
                    })));
            }

    window.executeSmartPngExport = async function () {
        const btn = document.getElementById('btnRunSmartPng');
        const status = document.getElementById('smartPngStatus');
        const scope = document.getElementById('smartPngScope')?.value || 'overview';
        const theme = document.getElementById('smartPngTheme')?.value || 'white';
        const scale = parseInt(document.getElementById('smartPngResolution')?.value || '2', 10);

        if (typeof html2canvas === 'undefined') {
            alert('Image capture library is still initializing. Please try again.');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating Presentation PNG...';
        status.style.display = 'block';
        status.innerHTML = '<span style="color:var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Capturing high-resolution slide view...</span>';

        // Select capture target — scope each selection to a precise region,
        // never the whole page.
        let targetElem = null;
        let targetName = 'Overview';

        if (scope === 'full') {
            targetElem = document.querySelector('.cei-tab-pane.active');
            targetName = 'Full_Dashboard';
        } else if (scope === 'overview') {
            // Executive overview strip: banner + 7 KQIs grid
            const src = document.querySelector('#pane-achievement [data-capture="banner"]')
                ? document.getElementById('execBanner')
                : null;
            if (src) {
                const banner = document.getElementById('execBanner');
                const kqi = document.getElementById('kqiCardsGrid');
                const wrap = document.createElement('div');
                wrap.style.cssText = 'display:grid; gap:14px; background:transparent;';
                // Rasterize charts with a transparent background so the card's own
                // theme background shows through (white, dark or explicit alpha).
                wrap.appendChild(buildEchartsAwareClone(banner, null));
                if (kqi) {
                    const kqiCard = kqi.closest('.cei-card') || kqi;
                    wrap.appendChild(buildEchartsAwareClone(kqiCard, null));
                }
                wrap.style.position = 'absolute';
                wrap.style.left = '-100000px';
                wrap.style.top = '0';
                wrap.style.pointerEvents = 'none';
                document.body.appendChild(wrap);
                setTimeout(() => wrap.remove(), 5000);
                targetElem = wrap;
            } else {
                targetElem = document.getElementById('pane-achievement') || document.querySelector('.cei-container');
            }
            targetName = 'Executive_Overview';
        } else if (scope === 'charts') {
            // Only the two chart containers (CEI Trend Achievement + KQI Trend)
            const charts = document.querySelectorAll('#pane-achievement .cei-chart-container[data-capture="charts"]');
            if (charts.length) {
                const wrap = document.createElement('div');
                wrap.style.cssText = 'display:grid; gap:14px; background:transparent;';
                charts.forEach(c => wrap.appendChild(buildEchartsAwareClone(c, null)));
                wrap.style.position = 'absolute';
                wrap.style.left = '-100000px';
                wrap.style.top = '0';
                wrap.style.pointerEvents = 'none';
                document.body.appendChild(wrap);
                setTimeout(() => wrap.remove(), 5000);
                targetElem = wrap;
            } else {
                targetElem = document.querySelector('#pane-achievement .cei-chart-container') || document.getElementById('pane-achievement');
            }
            targetName = 'Charts';
        }

        if (!targetElem) targetElem = document.querySelector('.cei-container') || document.body;

        let bgColor = '#ffffff';
        if (theme === 'dark') bgColor = '#0f172a';
        else if (theme === 'theme') {
            bgColor = document.documentElement.getAttribute('data-theme') === 'dark' ? '#0f172a' : '#f8fafc';
        }
        // transparent => null (html2canvas keeps alpha channel)
        if (theme === 'transparent') bgColor = null;

        try {
                    closeSmartPngModal();
                    await new Promise(r => setTimeout(r, 140));

                    // Wait for any rasterized <img> in an offscreen wrapper to decode,
                    // otherwise html2canvas captures it before the bitmap is painted.
                    await waitForImages(targetElem);

                    const canvas = await html2canvas(targetElem, {
                        backgroundColor: bgColor,
                        scale: scale,
                        useCORS: true,
                        logging: false,
                        allowTaint: true
                    });

            const yw = document.getElementById('gaugeWeek')?.value || document.getElementById('trendEndWeek')?.value || 'latest';
            const link = document.createElement('a');
            link.download = `CEI_Smart_Presentation_${targetName}_${yw}.png`;
            link.href = canvas.toDataURL('image/png');
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        } catch (err) {
            console.error('Smart PNG export error:', err);
            alert('Smart PNG export encountered an error: ' + err.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-download"></i> Generate &amp; Download PNG';
            status.style.display = 'none';
        }
    };

    // ══════════════════════════════════════════════════════════════════
    // Comparison Table Excel / XLSX Export (SheetJS)
    // ══════════════════════════════════════════════════════════════════
    window.exportComparisonTableXlsx = function (tableId, defaultName) {
        const table = document.getElementById(tableId);
        if (!table) {
            alert('Table not found.');
            return;
        }
        if (typeof XLSX === 'undefined') {
            alert('Excel export library is still loading. Please try again.');
            return;
        }

        try {
            const wb = XLSX.utils.table_to_book(table, { sheet: "Comparison" });
            const yw = document.getElementById('compWeek')?.value || 'latest';
            XLSX.writeFile(wb, `${defaultName}_W${String(yw).slice(4)}_${yw}.xlsx`);
        } catch (err) {
            console.error('XLSX export failed:', err);
            alert('Export to XLSX failed: ' + err.message);
        }
    };

})();
