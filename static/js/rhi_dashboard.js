/**
 * RHI Dashboard JavaScript
 * Multi-Tab Radio Health Index Dashboard:
 *   1. RHI Achievement (PUMA Gauge + Tech Cards + Indicators + Branch Distribution Strip + RHI Trend Achievement combo)
 *   2. RHI Trend & Root Causes (Technology Trend Line + Top Fail Root Causes Chart + Geo Location Trend)
 *   3. Comparison Table (NOP Table WoW + Tech WoW + Root Causes WoW + Kabupaten Level WoW Table)
 */

(function () {
    'use strict';

    // Global ECharts Instances
    let pumaGaugeInstance = null;
    let achievementChartInstance = null;
    let failTechChartInstance = null;
    let chartEnlargedInstance = null;
    let techTrendChartInstance = null;
    let failReasonChartInstance = null;
    let geoGoodPctChartInstance = null;

    // State
    let activeTab = 'achievement';
    let availableWeeks = [];
    let geoOptionsData = null;
    let rawKabupatenData = [];
    let selectedRhiFile = null;
    let currentAchievementData = null;
    let currentSummaryData = null;
    let currentIndicatorData = null;
    let currentIndicatorTech = '4g';
    let currentTrendData = null;
    let currentGeoData = null;
    let currentEnlargedType = null;

    // Distinct Colors
    const TECH_COLORS = {
        '2g': '#db2777',   // Rose
        '4g': '#2563eb',   // Blue
        '5g': '#10b981',   // Emerald
        'overall': '#0F3B66' // Navy
    };

    const REASON_COLORS = [
        '#ef4444', '#f97316', '#eab308', '#06b6d4', '#6366f1', '#ec4899', '#8b5cf6', '#14b8a6'
    ];

    // DOM Ready
    document.addEventListener('DOMContentLoaded', function () {
        initSidebarObserver();
        initWeeksAndData();
    });

    let tab2Loaded = false;
    let tab3Loaded = false;

    // ── Tab Management ──
    window.switchRhiTab = function (tabId, btnElem) {
        activeTab = tabId;
        document.querySelectorAll('.rhi-tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.rhi-tab-pane').forEach(pane => pane.classList.remove('active'));

        if (btnElem) {
            btnElem.classList.add('active');
        }
        const targetPane = document.getElementById(`pane-${tabId}`);
        if (targetPane) {
            targetPane.classList.add('active');
        }

        // Lazy-load tabs on demand
        if (tabId === 'trend' && !tab2Loaded) {
            tab2Loaded = true;
            loadTrendCharts();
            loadGeoOptions();
        } else if (tabId === 'comparison' && !tab3Loaded) {
            tab3Loaded = true;
            loadComparison();
            loadKabupatenComparison();
        }

        setTimeout(resizeAllVisibleCharts, 50);
        setTimeout(resizeAllVisibleCharts, 250);
    };

    // ── Auto-Resize on Window & Sidebar Toggle ──
    function resizeAllVisibleCharts() {
        if (activeTab === 'achievement') {
            if (pumaGaugeInstance) pumaGaugeInstance.resize();
            if (achievementChartInstance) achievementChartInstance.resize();
            if (failTechChartInstance) failTechChartInstance.resize();
        } else if (activeTab === 'trend') {
            if (techTrendChartInstance) techTrendChartInstance.resize();
            if (failReasonChartInstance) failReasonChartInstance.resize();
            if (geoGoodPctChartInstance) geoGoodPctChartInstance.resize();
        }
        if (chartEnlargedInstance) chartEnlargedInstance.resize();
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
        // Tab 1 (Achievement) loads immediately on page display
        loadGaugeAndSummary();
        loadIndicatorCards();
        loadAchievementChart();
        // Tabs 2 & 3 load on demand when user switches tabs
    }

    // ══════════════════════════════════════════════════════════════════
    // TAB 1: RHI Achievement Logic
    // ══════════════════════════════════════════════════════════════════
    window.onTrendFilterChange = function () {
        loadAchievementChart();
        loadTrendCharts();
    };

    window.onGaugeFilterChange = function () {
        loadGaugeAndSummary();
        loadIndicatorCards();
    };

    async function loadGaugeAndSummary() {
        const ywElem = document.getElementById('gaugeWeek');
        const yw = ywElem ? ywElem.value : '';
        try {
            const res = await fetch(`/api/sow/rhi/summary?weeknum=${yw}`);
            const data = await res.json();
            if (data.status !== 'success') return;
            currentSummaryData = data;

            // Stats
            const totalEl = document.getElementById('statTotalCells');
            const goodEl = document.getElementById('statGoodCells');
            const badEl = document.getElementById('statBadCells');
            const goodPctEl = document.getElementById('statGoodPct');
            const badPctEl = document.getElementById('statBadPct');

            if (totalEl) totalEl.textContent = (data.total_cells || 0).toLocaleString();
            if (goodEl) goodEl.textContent = (data.good_cells || 0).toLocaleString();
            if (badEl) badEl.textContent = (data.fail_cells || 0).toLocaleString();
            if (goodPctEl) goodPctEl.textContent = `${data.good_cell_pct || 0}%`;
            if (badPctEl) {
                const bPct = (data.total_cells && data.fail_cells) ? ((data.fail_cells * 100.0) / data.total_cells).toFixed(2) : 0;
                badPctEl.textContent = `${bPct}%`;
            }

            const targetBadge = document.getElementById('gaugeTargetBadge');
            const target = data.target !== null ? data.target : 93.55;
            const qStr = (data.quarter || 'Q').replace(/^Target\s*/i, '').trim();
            if (targetBadge) {
                targetBadge.textContent = `Target: ${target}% (${qStr})`;
                targetBadge.className = data.is_above_target ? 'badge-pass' : 'badge-fail';
            }

            // Additional Performance & WoW Insights (Like CEI)
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

            // Top Executive Performance Banner (Like 1st Picture)
            const bWeekEl = document.getElementById('bannerWeekNum');
            const bBaseEl = document.getElementById('bannerBaseline');
            const bTgtEl = document.getElementById('bannerTarget');
            const bTgtLblEl = document.getElementById('bannerTargetLabel');
            const bAchEl = document.getElementById('bannerAch');
            const bGapEl = document.getElementById('bannerGap');

            if (bWeekEl) bWeekEl.textContent = strWeek(data.yearweek);
            if (bBaseEl && data.baseline !== undefined) bBaseEl.textContent = `${Number(data.baseline).toFixed(2)}%`;
            if (bTgtEl) bTgtEl.textContent = `${Number(target).toFixed(2)}%`;
            if (bTgtLblEl) bTgtLblEl.textContent = `Target (${qStr})`;
            if (bAchEl) bAchEl.textContent = `${Number(data.good_cell_pct).toFixed(2)}%`;
            if (bGapEl) {
                const gap = data.diff_target_pp !== undefined ? data.diff_target_pp : (data.good_cell_pct - target);
                const sign = gap >= 0 ? '+' : '';
                bGapEl.textContent = `${sign}${Number(gap).toFixed(2)} pp`;
                bGapEl.style.color = gap >= 0 ? '#a7f3d0' : '#fca5a5';
            }

            // Speedometer Gauge
            renderPumaGauge(data.good_cell_pct, target);

            // Branch Performance Distribution Strip
            renderBranchDistribution(data.regional_gauge, data.good_cell_pct, target, data.quarter);

            // Executive Performance Highlights (Executive Summary)
            const listEl = document.getElementById('execBulletsList');
            const passBadgeEl = document.getElementById('execPassBadge');
            if (passBadgeEl) {
                passBadgeEl.className = data.is_above_target ? 'badge-pass' : 'badge-fail';
                passBadgeEl.textContent = data.is_above_target ? 'PASS TARGET' : 'BELOW TARGET';
            }
            if (listEl && data.bullets && data.bullets.length) {
                listEl.innerHTML = data.bullets.map(b => {
                    let formatted = b
                        .replace(/\b(PUMA|AMBON|JAYAPURA|TIMIKA|SORONG)\b/g, '<strong>$1</strong>')
                        .replace(/\b(\d+[\d,]*\s*cells)\b/gi, '<strong>$1</strong>')
                        .replace(/\b(\d+\.\d{2}%)\b/g, '<strong>$1</strong>')
                        .replace(/(degraded by [^)]+\))/gi, '<span style="color:#ef4444; font-weight:700;">$1</span>')
                        .replace(/(improved by [^)]+\))/gi, '<span style="color:#10b981; font-weight:700;">$1</span>')
                        .replace(/(Need to recover [^.]+\.)/gi, '<span style="color:#ef4444; font-weight:700;">$1</span>')
                        .replace(/(successfully passing the target[^.]*\.)/gi, '<span style="color:#10b981; font-weight:700;">$1</span>')
                        .replace(/(breaching the target[^.]*\.)/gi, '<span style="color:#ef4444; font-weight:700;">$1</span>');
                    return `<li>${formatted}</li>`;
                }).join('');
            }
        } catch (e) {
            console.error('Error loading RHI summary & gauge:', e);
        }
    }

    // Speedometer Gauge
    function buildGaugeOption(pct, target, isDark, isEnlarged = false) {
        const numPct = typeof pct === 'number' ? pct : (parseFloat(pct) || 0);
        const numTarget = typeof target === 'number' ? target : (parseFloat(target) || 93.55);
        const isPass = numPct >= numTarget;
        const mainColor = isPass ? '#00B074' : '#ef4444';

        return {
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
                        width: isEnlarged ? 22 : 14,
                        roundCap: true,
                        itemStyle: { color: mainColor }
                    },
                    pointer: { show: false },
                    axisLine: {
                        lineStyle: {
                            width: isEnlarged ? 22 : 14,
                            color: [[1, isDark ? 'rgba(255,255,255,0.08)' : '#E5E9EC']]
                        }
                    },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: false },
                    title: {
                        show: true,
                        offsetCenter: [0, '35%'],
                        fontSize: isEnlarged ? 16 : 11.5,
                        fontWeight: '700',
                        color: isDark ? '#94a3b8' : '#64748b'
                    },
                    detail: {
                        valueAnimation: true,
                        offsetCenter: [0, '-10%'],
                        fontSize: isEnlarged ? 46 : 27,
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
    }

    function renderPumaGauge(pct, target) {
        const dom = document.getElementById('pumaGaugeChart');
        if (!dom) return;
        if (!pumaGaugeInstance) {
            pumaGaugeInstance = echarts.init(dom);
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        pumaGaugeInstance.setOption(buildGaugeOption(pct, target, isDark, false), true);
        pumaGaugeInstance.resize();
    }

    // Branch Performance Distribution vs Target (Matches User Reference Image)
    function renderBranchDistribution(branchesData, pumaPct, target, quarterLabel) {
        const wrap = document.getElementById('branchDistribWrap');
        if (!wrap) return;

        const qBadge = document.getElementById('distribQuarterBadge');
        if (qBadge) {
            qBadge.textContent = `${quarterLabel || 'Target'}: ${target}%`;
        }

        const branchList = (branchesData && branchesData.length) ? branchesData.slice() : [
            { name: 'TIMIKA', value: 91.91, is_above: false, total: 9803, fail: 412 },
            { name: 'JAYAPURA', value: 92.19, is_above: false, total: 10700, fail: 674 },
            { name: 'AMBON', value: 93.20, is_above: false, total: 11618, fail: 959 },
            { name: 'SORONG', value: 95.98, is_above: true, total: 9486, fail: 429 }
        ];

        // Sort ascending by value for reliable spacing & collision checks
        branchList.sort((a, b) => a.value - b.value);

        const allVals = [target, pumaPct || 93.84].concat(branchList.map(b => b.value));
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
        const pumaLeft = getLeftPct(pumaPct || 93.84);

        // Render Branch/NOP: ALL AT TOP, with 2-line format (Branch Name shift+Enter Value)
        let branchPointsHtml = '';
        let lastLeft = -999;
        let lastTop = 20;

        branchList.forEach(b => {
            const bLeft = getLeftPct(b.value);
            const isMet = b.value >= target;
            const valColor = isMet ? '#16a34a' : '#dc2626';
            const dotColor = isMet ? '#10b981' : '#ef4444';

            // Anti-collision staggering: if closer than 7% to previous branch, alternate top position
            let topOffset = 20;
            if (Math.abs(bLeft - lastLeft) < 7.5) {
                topOffset = (lastTop === 20) ? 8 : 20;
            }
            lastLeft = bLeft;
            lastTop = topOffset;

            branchPointsHtml += `
                <div class="rhi-distrib-branch-top" style="left: ${bLeft}%; top: ${topOffset}px;" title="${b.name}: ${b.value}% (Total: ${(b.total || 0).toLocaleString()}, Fail: ${(b.fail || 0).toLocaleString()})">
                    <div class="rhi-branch-text">
                        <span class="rhi-branch-name">${b.name}</span>
                        <span class="rhi-branch-val" style="color: ${valColor};">${b.value}%</span>
                    </div>
                    <div class="rhi-branch-dot" style="background: ${dotColor}; margin-top: ${topOffset === 8 ? '16px' : '4px'};"></div>
                </div>
            `;
        });

        // Numerical Axis Ticks along bottom of track
        let ticksHtml = '';
        for (let tickVal = Math.ceil(minScale); tickVal <= Math.floor(maxScale); tickVal++) {
            const tickLeft = getLeftPct(tickVal);
            ticksHtml += `
                <div class="rhi-distrib-tick" style="left: ${tickLeft}%;">
                    <div class="rhi-distrib-tick-line"></div>
                    <span>${tickVal}</span>
                </div>
            `;
        }

        // PUMA Marker — Strictly at BOTTOM
        const isPumaPass = (pumaPct || 93.84) >= target;
        const pumaColor = isPumaPass ? '#16a34a' : '#dc2626';

        wrap.innerHTML = `
            <!-- Dual-colored track (soft red on left of target, soft green on right) -->
            <div class="rhi-distrib-track">
                <div class="rhi-distrib-track-fail" style="width: ${targetLeft}%;"></div>
                <div class="rhi-distrib-track-pass"></div>
            </div>

            <!-- Target Label on TOP (text color black) & dashed line extending directly beneath it down across track -->
            <div class="rhi-distrib-target-label" style="left: ${targetLeft}%;">Target ${target}%</div>
            <div class="rhi-distrib-target-line" style="left: ${targetLeft}%;"></div>

            <!-- All Branch Markers on TOP -->
            ${branchPointsHtml}

            <!-- Axis Ticks below track -->
            <div class="rhi-distrib-ticks">
                ${ticksHtml}
            </div>

            <!-- PUMA Marker on BOTTOM -->
            <div class="rhi-distrib-puma-bottom" style="left: ${pumaLeft}%;" title="PUMA Regional: ${pumaPct}%">
                <div style="width:0; height:0; border-left:5px solid transparent; border-right:5px solid transparent; border-bottom:6px solid ${pumaColor}; margin-bottom:2px;"></div>
                <div class="rhi-puma-pill" style="color:${pumaColor}; border-color:${pumaColor};">
                    PUMA ${pumaPct}%
                </div>
            </div>
        `;

        // Fill Branch Summary Mini-Cards Row
        const statRow = document.getElementById('branchStatRow');
        if (statRow && branchList.length) {
            statRow.innerHTML = branchList.map(b => {
                const isMet = b.value >= target;
                const badgeClass = isMet ? 'badge-pass' : 'badge-fail';
                const badgeText = isMet ? 'Pass' : 'Below';
                return `
                    <div class="rhi-branch-chip">
                        <div class="rhi-branch-chip-hdr">
                            <span class="rhi-branch-chip-name">${b.name}</span>
                            <span class="${badgeClass}">${b.value}% (${badgeText})</span>
                        </div>
                        <div class="rhi-branch-chip-sub">
                            <span>${(b.total || 0).toLocaleString()} cells</span>
                            <span style="color:#ef4444; font-weight:700;">${(b.fail || 0).toLocaleString()} fails</span>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    // Load Tech & Indicator Cards
    async function loadIndicatorCards() {
        const ywElem = document.getElementById('gaugeWeek');
        const yw = ywElem ? ywElem.value : '';
        try {
            const res = await fetch(`/api/sow/rhi/indicator-cards?weeknum=${yw}`);
            const data = await res.json();
            if (data.status !== 'success') return;
            currentIndicatorData = data;

            // 1. Render 3 Tech Cards
            const techGrid = document.getElementById('techCardsGrid');
            if (techGrid && data.tech_cards) {
                techGrid.innerHTML = data.tech_cards.map(c => {
                    const isPos = c.delta !== null && c.delta >= 0;
                    const deltaIcon = isPos ? '▲' : '▼';
                    const deltaClass = isPos ? 'val-pos' : 'val-neg';
                    const deltaText = c.delta !== null ? `${deltaIcon} ${Math.abs(c.delta)}% WoW` : '--';

                    return `
                        <div class="rhi-tech-card" style="border-top: 3px solid ${c.color};">
                            <div class="rhi-tech-title">
                                <span style="color: ${c.color};">${c.title}</span>
                                <span style="font-size:11px; font-weight:600; color:var(--text-muted);">${(c.total || 0).toLocaleString()} cells</span>
                            </div>
                            <div class="rhi-tech-pct">
                                <span>${c.pct}%</span>
                                <span class="rhi-tech-delta ${deltaClass}">${deltaText}</span>
                            </div>
                            <div class="rhi-tech-footer">
                                <span>Top Fail: <strong>${c.top_fail_label}</strong></span>
                                <span style="color:#ef4444; font-weight:700;" title="${(c.top_fail_count || 0).toLocaleString()} fail cells (${c.top_fail_pct || 0}% of all ${c.tech.toUpperCase()} cells, ${c.top_fail_share || 0}% share of fails)">
                                    ${(c.top_fail_count || 0).toLocaleString()} (${c.top_fail_pct || 0}%)
                                </span>
                            </div>
                        </div>
                    `;
                }).join('');
            }

            // 2. Render Indicator Breakdown & Tech Mini Tabs
            currentIndicatorData = data;
            renderIndicatorBreakdown();
        } catch (e) {
            console.error('Error loading indicator cards:', e);
        }
    }

    // ── Mini Tab for Indicator Tech Selection (4G, 2G, 5G) ──
    window.switchIndicatorTech = function (tech) {
        currentIndicatorTech = tech;
        const tabBtns = document.querySelectorAll('#indicatorTechTabs .rhi-mini-tab-btn');
        tabBtns.forEach(btn => {
            if (btn.getAttribute('data-tech') === tech) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
        renderIndicatorCardsForTech();
    };

    function renderIndicatorBreakdown() {
        if (!currentIndicatorData) return;
        
        // Update mini-tab badge counts
        const b4 = document.getElementById('pillBadge4G');
        const b2 = document.getElementById('pillBadge2G');
        const b5 = document.getElementById('pillBadge5G');
        if (b4) b4.innerText = (currentIndicatorData.total_fail_4g || 0).toLocaleString();
        if (b2) b2.innerText = (currentIndicatorData.total_fail_2g || 0).toLocaleString();
        if (b5) b5.innerText = (currentIndicatorData.total_fail_5g || 0).toLocaleString();

        renderIndicatorCardsForTech();
    }

    function renderIndicatorCardsForTech() {
        if (!currentIndicatorData) return;
        const byTech = currentIndicatorData.indicators_by_tech || {};
        const techData = byTech[currentIndicatorTech] || { tech: currentIndicatorTech.toUpperCase(), total_fails: 0, cards: [] };
        const cards = techData.cards || [];
        const totalTechFails = techData.total_fails || 0;

        const sumTextEl = document.getElementById('indicatorImpactText');
        if (sumTextEl) {
            if (totalTechFails === 0) {
                sumTextEl.innerHTML = `Total <strong style="color:#10b981;">0 failed cells</strong> in ${techData.tech} Network · 100% Good Cell Achievement`;
            } else {
                const topC = cards[0] || {};
                sumTextEl.innerHTML = `Total <strong>${techData.tech}</strong> fails: <strong style="color:#ef4444;">${totalTechFails.toLocaleString()} cells</strong> across ${cards.length} root cause KPIs · Top contributor: <strong style="color:${topC.color || '#ef4444'};">${topC.title}</strong> (${(topC.fail_count || 0).toLocaleString()} cells • ${topC.share || 0}%)`;
            }
        }

        const indGrid = document.getElementById('indicatorCardsGrid');
        if (!indGrid) return;

        if (!cards.length || (totalTechFails === 0 && currentIndicatorTech === '5g')) {
            indGrid.innerHTML = `
                <div style="grid-column: 1 / -1; padding: 22px; text-align: center; color: var(--text-muted); background: rgba(16, 185, 129, 0.05); border: 1px dashed rgba(16, 185, 129, 0.3); border-radius: 8px;">
                    <i class="fas fa-check-circle" style="color: #10b981; font-size: 20px; margin-bottom: 6px;"></i>
                    <div style="font-weight: 700; color: var(--text-main);">Zero Failure in ${techData.tech} Network</div>
                    <div style="font-size: 11px;">All cells achieved RHI targets in Week ${String(currentIndicatorData.yearweek).slice(4)}.</div>
                </div>
            `;
            return;
        }

        indGrid.innerHTML = cards.map(c => {
            const failCount = c.fail_count || 0;
            const deltaFail = c.delta_fail;
            let deltaHtml = '--';
            let isWorsened = false;

            if (deltaFail !== null && deltaFail !== undefined) {
                if (deltaFail > 0) {
                    isWorsened = true; // more fails is worse
                    deltaHtml = `<span class="val-neg">▲ +${deltaFail.toLocaleString()} (${c.delta_pct || 0}%) WoW</span>`;
                } else if (deltaFail < 0) {
                    isWorsened = false; // less fails is improvement
                    deltaHtml = `<span class="val-pos">▼ ${deltaFail.toLocaleString()} (${c.delta_pct || 0}%) WoW</span>`;
                } else {
                    deltaHtml = `<span style="color:var(--text-muted);">0 (0.0%) WoW</span>`;
                }
            }

            const sparkSvg = generateSparklineSvg(c.fail_trend || [], isWorsened, 78, 26);
            const weekListStr = (c.spark_weeks || []).join(', ');
            const avgText = c.avg_score ? ` · Avg: <strong>${c.avg_score}%</strong>` : '';

            return `
                <div class="rhi-ind-card" style="border-top: 3px solid ${c.color};">
                    <div class="rhi-ind-card-title">
                        <span>${c.title}</span>
                        <span class="tech-badge" style="color:${c.color};">${c.tech}</span>
                    </div>
                    <div class="rhi-ind-body">
                        <div class="rhi-ind-left">
                            <div class="rhi-ind-val">
                                ${failCount.toLocaleString()}<span class="unit">cells</span>
                            </div>
                            <div class="rhi-ind-delta">
                                ${deltaHtml}
                            </div>
                            <div class="rhi-ind-subtext">
                                <strong>${c.share}%</strong> of ${c.tech} fails${avgText}
                            </div>
                        </div>
                        <div class="rhi-ind-chart-wrap" title="Weekly fail cell trend (${weekListStr}): ${(c.fail_trend || []).map(v => v.toLocaleString()).join(' → ')} cells">
                            ${sparkSvg}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Mini SVG Sparkline generator (Matching Sample Picture: subtle gray trend line with colored terminal dot)
    function generateSparklineSvg(data, isWorsened, width = 78, height = 26) {
        if (!data || data.length < 2) {
            return `<div style="width:${width}px; height:${height}px;"></div>`;
        }
        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = (max - min) || 0.01;
        const padX = 4;
        const padY = 4;
        const effW = width - (padX * 2);
        const effH = height - (padY * 2);

        const pts = data.map((v, i) => {
            const x = padX + (i / (data.length - 1)) * effW;
            const y = height - padY - ((v - min) / range) * effH;
            return [x.toFixed(1), y.toFixed(1)];
        });

        const pathD = pts.reduce((acc, p, i) => i === 0 ? `M ${p[0]} ${p[1]}` : `${acc} L ${p[0]} ${p[1]}`, '');
        const lastPt = pts[pts.length - 1];
        const dotColor = isWorsened ? '#ef4444' : '#10b981';

        return `
            <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="overflow:visible; display:block;">
                <path d="${pathD}" fill="none" stroke="#94a3b8" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                <circle cx="${lastPt[0]}" cy="${lastPt[1]}" r="3.2" fill="${dotColor}" stroke="#ffffff" stroke-width="1.5" />
            </svg>
        `;
    }

    // Direct export of indicators card as high-res PNG
    window.exportIndicatorsCardPNG = function () {
        const grid = document.getElementById('indicatorCardsGrid');
        const card = grid ? grid.closest('.rhi-card') : null;
        if (!card || typeof html2canvas === 'undefined') return;
        html2canvas(card, { scale: 2, backgroundColor: '#ffffff' }).then(canvas => {
            const a = document.createElement('a');
            const ywElem = document.getElementById('gaugeWeek');
            const yw = ywElem ? ywElem.value : 'export';
            a.download = `RHI_Key_Radio_Indicators_W${String(yw).slice(4)}.png`;
            a.href = canvas.toDataURL('image/png');
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        });
    };

    // Dual-Axis RHI Trend Achievement Chart
    async function loadAchievementChart() {
        const sElem = document.getElementById('trendStartWeek');
        const eElem = document.getElementById('trendEndWeek');
        const startYw = sElem ? sElem.value : '';
        const endYw = eElem ? eElem.value : '';

        try {
            const res = await fetch(`/api/sow/rhi/achievement?start_yw=${startYw}&end_yw=${endYw}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            currentAchievementData = data;

            const targetInfo = document.getElementById('achTargetInfo');
            if (targetInfo) {
                targetInfo.textContent = `Target Pass: ${data.target || 93.55}%`;
            }

            renderAchievementChart(data);
            renderFailTechChart(data);
        } catch (e) {
            console.error('Error loading RHI achievement chart:', e);
        }
    }

    // Dynamic Y-axis scale calculator
    function computeDynamicYAxisRange(seriesArrays, defaultMin = 80, padding = 4) {
        const vals = [];
        (seriesArrays || []).forEach(arr => {
            (arr || []).forEach(v => {
                const num = typeof v === 'object' && v !== null ? v.value : v;
                if (typeof num === 'number' && !isNaN(num) && num > 0) vals.push(num);
            });
        });
        if (!vals.length) return { min: defaultMin, max: 100 };
        const minV = Math.min(...vals);
        const maxV = Math.max(...vals);
        // Floor down with padding to a multiple of 5 (e.g. 69.5 -> 65)
        const yMin = Math.max(0, Math.floor((minV - padding) / 5) * 5);
        // Ensure max reaches at least target or 100
        const yMax = maxV <= 98 ? 100 : Math.min(100, Math.ceil((maxV + 2) / 5) * 5);
        return { min: yMin, max: yMax };
    }

    function buildAchievementOption(data, isDark, isEnlarged = false) {
        const labels = data.labels || [];
        const goodCounts = data.good_counts || [];
        const failCounts = data.fail_counts || [];
        const goodPct = data.good_pct_series || [];
        const targetSeries = data.target_series || [];
        const target = data.target || 93.55;

        // Dynamic Y-axis bounds
        const yPctRange = computeDynamicYAxisRange([goodPct, targetSeries], 85, 4);

        // Conditional dot styles: Green if >= target, Red if < target
        const goodLineData = goodPct.map((val, idx) => {
            const tgt = targetSeries[idx] ?? target;
            const isMet = val >= tgt;
            const color = isMet ? '#107C41' : '#C93B2B';
            return {
                value: val,
                itemStyle: { color: color },
                label: {
                    show: true,
                    position: 'top',
                    color: color,
                    fontWeight: 'bold',
                    fontSize: isEnlarged ? 12 : 10.5,
                    formatter: `${val}%`
                }
            };
        });

        return {
            tooltip: {
                trigger: 'axis',
                confine: true,
                axisPointer: { type: 'cross' },
                formatter: function (params) {
                    let res = `<div style="font-weight:700; margin-bottom:4px;">${params[0].name}</div>`;
                    params.forEach(p => {
                        const val = (p.seriesType === 'line') ? `${p.value}%` : (p.value || 0).toLocaleString();
                        res += `<div style="display:flex; justify-content:space-between; gap:12px; font-size:11.5px;">
                            <span>${p.marker} ${p.seriesName}</span>
                            <strong>${val}</strong>
                        </div>`;
                    });
                    return res;
                }
            },
            legend: {
                bottom: isEnlarged ? 15 : 0,
                textStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 13 : 11 },
                data: ['Good Cells', 'Fail Cells', '% Good Cell', 'Target']
            },
            grid: {
                left: isEnlarged ? '2%' : '3%',
                right: isEnlarged ? '3%' : '4%',
                top: isEnlarged ? '10%' : '12%',
                bottom: isEnlarged ? '10%' : '12%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                data: labels,
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 },
                axisLine: { lineStyle: { color: isDark ? '#334155' : '#cbd5e1' } }
            },
            yAxis: [
                {
                    type: 'value',
                    name: 'Cell Count',
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 },
                    splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9' } },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: isEnlarged ? 12 : 11,
                        formatter: function (val) { return val >= 1000 ? `${(val/1000).toFixed(0)}k` : val; }
                    }
                },
                {
                    type: 'value',
                    name: '% Good Cell',
                    min: yPctRange.min,
                    max: yPctRange.max,
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 },
                    splitLine: { show: false },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: isEnlarged ? 12 : 11,
                        formatter: '{value}%'
                    }
                }
            ],
            series: [
                {
                    name: 'Good Cells',
                    type: 'bar',
                    stack: 'cells',
                    data: goodCounts,
                    itemStyle: { color: '#4EBA97' },
                    barMaxWidth: isEnlarged ? 48 : 38
                },
                {
                    name: 'Fail Cells',
                    type: 'bar',
                    stack: 'cells',
                    data: failCounts,
                    itemStyle: { color: '#64748B' },
                    barMaxWidth: isEnlarged ? 48 : 38
                },
                {
                    name: '% Good Cell',
                    type: 'line',
                    yAxisIndex: 1,
                    data: goodLineData,
                    smooth: true,
                    lineStyle: { color: '#0F3B66', width: isEnlarged ? 3.5 : 2.5 },
                    symbolSize: isEnlarged ? 9 : 7
                },
                {
                    name: 'Target',
                    type: 'line',
                    yAxisIndex: 1,
                    step: 'end',
                    data: targetSeries,
                    lineStyle: { color: '#ef4444', width: 2, type: 'dashed' },
                    itemStyle: { color: '#ef4444' },
                    symbol: 'none'
                }
            ]
        };
    }

    function renderAchievementChart(data) {
        const dom = document.getElementById('achievementChart');
        if (!dom) return;
        if (!achievementChartInstance) {
            achievementChartInstance = echarts.init(dom);
        }
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const option = buildAchievementOption(data, isDark, false);
        achievementChartInstance.setOption(option, true);
        achievementChartInstance.resize();
    }

    function buildFailTechOption(data, isDark, isEnlarged = false) {
        const labels = data.labels || [];
        const fail2g = data.fail_2g || [];
        const fail4g = data.fail_4g || [];
        const fail5g = data.fail_5g || [];
        const achPct = data.good_pct_series || [];
        const targetSeries = data.target_series || [];

        // Dynamic Right Y-axis range for Ach %
        const yPctRange = computeDynamicYAxisRange([achPct, targetSeries], 90, 2);

        // Map Ach % data with explicit label on points
        const achLineData = achPct.map(val => ({
            value: val,
            label: {
                show: true,
                position: 'top',
                color: '#06b6d4',
                fontWeight: 'bold',
                fontSize: isEnlarged ? 12 : 11,
                formatter: `${val}%`
            }
        }));

        return {
            tooltip: {
                trigger: 'axis',
                confine: true,
                axisPointer: { type: 'cross' },
                formatter: function (params) {
                    let res = `<div style="font-weight:700; margin-bottom:4px;">${params[0].name}</div>`;
                    params.forEach(p => {
                        const val = (p.seriesType === 'line') ? `${p.value}%` : (p.value || 0).toLocaleString();
                        res += `<div style="display:flex; justify-content:space-between; gap:12px; font-size:11.5px;">
                            <span>${p.marker} ${p.seriesName}</span>
                            <strong>${val}</strong>
                        </div>`;
                    });
                    return res;
                }
            },
            legend: {
                bottom: isEnlarged ? 15 : 0,
                textStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 13 : 11 },
                data: ['Fail 2g', 'Fail 4g', 'Fail 5g', 'Ach %', 'Target RHI PUMA %']
            },
            grid: {
                left: isEnlarged ? '2%' : '3%',
                right: isEnlarged ? '3%' : '4%',
                top: isEnlarged ? '10%' : '12%',
                bottom: isEnlarged ? '10%' : '12%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                data: labels,
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 },
                axisLine: { lineStyle: { color: isDark ? '#334155' : '#cbd5e1' } }
            },
            yAxis: [
                {
                    type: 'value',
                    name: 'Fail Cells',
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 },
                    splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9' } },
                    axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12 : 11 }
                },
                {
                    type: 'value',
                    name: 'Ach %',
                    min: yPctRange.min,
                    max: yPctRange.max,
                    nameTextStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 },
                    splitLine: { show: false },
                    axisLabel: {
                        color: isDark ? '#94a3b8' : '#64748b',
                        fontSize: isEnlarged ? 12 : 11,
                        formatter: '{value}%'
                    }
                }
            ],
            series: [
                {
                    name: 'Fail 2g',
                    type: 'bar',
                    stack: 'tech_fails',
                    data: fail2g,
                    itemStyle: { color: '#1e3a8a' }, // Dark blue
                    barMaxWidth: isEnlarged ? 48 : 38,
                    label: {
                        show: true,
                        position: 'inside',
                        color: '#ffffff',
                        fontSize: isEnlarged ? 11 : 9.5,
                        fontWeight: 'bold',
                        formatter: function (p) { return p.value > 0 ? p.value : ''; }
                    }
                },
                {
                    name: 'Fail 4g',
                    type: 'bar',
                    stack: 'tech_fails',
                    data: fail4g,
                    itemStyle: { color: '#dc2626' }, // Red
                    barMaxWidth: isEnlarged ? 48 : 38,
                    label: {
                        show: true,
                        position: 'inside',
                        color: '#ffffff',
                        fontSize: isEnlarged ? 11 : 9.5,
                        fontWeight: 'bold',
                        formatter: function (p) { return p.value > 0 ? p.value : ''; }
                    }
                },
                {
                    name: 'Fail 5g',
                    type: 'bar',
                    stack: 'tech_fails',
                    data: fail5g,
                    itemStyle: { color: '#16a34a' }, // Green
                    barMaxWidth: isEnlarged ? 48 : 38
                },
                {
                    name: 'Ach %',
                    type: 'line',
                    yAxisIndex: 1,
                    data: achLineData,
                    smooth: true,
                    lineStyle: { color: '#06b6d4', width: isEnlarged ? 3.5 : 3 }, // Cyan / Bright blue
                    itemStyle: { color: '#06b6d4' },
                    symbolSize: isEnlarged ? 8 : 6
                },
                {
                    name: 'Target RHI PUMA %',
                    type: 'line',
                    yAxisIndex: 1,
                    step: 'end',
                    data: targetSeries,
                    lineStyle: { color: isDark ? '#cbd5e1' : '#0f172a', width: 2, type: 'dashed' }, // Black/white dashed
                    itemStyle: { color: isDark ? '#cbd5e1' : '#0f172a' },
                    symbol: 'none'
                }
            ]
        };
    }

    // Combination Chart: Achievement RHI Puma — Fail per Tech with Ach % (2nd Picture)
    function renderFailTechChart(data) {
        const dom = document.getElementById('failTechChart');
        if (!dom) return;
        if (!failTechChartInstance) {
            failTechChartInstance = echarts.init(dom);
        }
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const option = buildFailTechOption(data, isDark, false);
        failTechChartInstance.setOption(option, true);
        failTechChartInstance.resize();
    }

    // Chart Enlarge Modal Handlers
    window.openChartEnlargeModal = function (chartType) {
        currentEnlargedType = chartType;

        const modal = document.getElementById('chartEnlargeModal');
        const titleEl = document.getElementById('enlargeModalTitle');
        const subtitleEl = document.getElementById('enlargeModalSubtitle');
        const container = document.getElementById('enlargedChartContainer');
        if (!modal || !container) return;

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        let opt = null;
        let titleHtml = '';
        let subtitle = '';

        if (chartType === 'achievement') {
            if (!currentAchievementData) return;
            titleHtml = '<i class="fas fa-chart-line" style="color:#0F3B66;"></i> RHI Trend Achievement';
            subtitle = 'Stacked Good & Fail Cells vs % Good Cell Achievement & Stepped Target Line';
            opt = buildAchievementOption(currentAchievementData, isDark, true);
        } else if (chartType === 'failTech') {
            if (!currentAchievementData) return;
            titleHtml = '<i class="fas fa-layer-group" style="color:#0F3B66;"></i> Achievement RHI Puma — Fail per Tech';
            subtitle = 'Failure Volumes per Technology (2G/4G/5G) vs Ach % Line & Target RHI PUMA %';
            opt = buildFailTechOption(currentAchievementData, isDark, true);
        } else if (chartType === 'pumaGauge') {
            if (!currentSummaryData) return;
            titleHtml = '<i class="fas fa-tachometer-alt" style="color:#0F3B66;"></i> Good cell PUMA';
            subtitle = 'PUMA Regional Achievement vs Quarterly Target';
            opt = buildGaugeOption(
                currentSummaryData.good_cell_pct,
                currentSummaryData.target !== null ? currentSummaryData.target : 93.55,
                isDark, true
            );
        } else if (chartType === 'techTrend') {
            if (!currentTrendData) return;
            titleHtml = '<i class="fas fa-chart-line" style="color:#0F3B66;"></i> Technology Trend (% Good Cell)';
            subtitle = 'Overall PUMA vs 2G / 4G / 5G Network Achievement Trend';
            opt = buildTechTrendOption(currentTrendData, isDark, true);
        } else if (chartType === 'failReason') {
            if (!currentTrendData) return;
            titleHtml = '<i class="fas fa-exclamation-triangle" style="color:#ef4444;"></i> Top Fail Root Causes';
            subtitle = 'Stacked Fail Cell Counts per Root Cause KPI per Week';
            opt = buildFailReasonOption(currentTrendData, isDark, true);
        } else if (chartType === 'geoGoodPct') {
            if (!currentGeoData) return;
            titleHtml = '<i class="fas fa-map-marked-alt" style="color:#0F3B66;"></i> % Good Cell Trend vs Target';
            subtitle = 'Geo Scope Achievement vs Stepped Quarterly Target';
            opt = buildGeoGoodPctOption(currentGeoData, isDark, true);
        }

        if (!opt) return;

        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        titleEl.innerHTML = titleHtml;
        subtitleEl.textContent = subtitle;

        if (chartEnlargedInstance) {
            chartEnlargedInstance.dispose();
        }
        chartEnlargedInstance = echarts.init(container);
        chartEnlargedInstance.setOption(opt, true);
        setTimeout(() => {
            if (chartEnlargedInstance) chartEnlargedInstance.resize();
        }, 80);
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

    // ── PNG export from enlarged chart modal ──
    window.downloadPopupChartPNG = function () {
        if (!chartEnlargedInstance) return;
        const url = chartEnlargedInstance.getDataURL({
            pixelRatio: 2,
            backgroundColor: '#ffffff'
        });
        const a = document.createElement('a');
        a.download = `RHI_${currentEnlargedType || 'chart'}_enlarged.png`;
        a.href = url;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    // ── Direct PNG export for any ECharts instance by type key ──
    window.exportChartDirectPNG = function (chartType) {
        const chartMap = {
            pumaGauge: pumaGaugeInstance,
            achievement: achievementChartInstance,
            failTech: failTechChartInstance,
            techTrend: techTrendChartInstance,
            failReason: failReasonChartInstance,
            geoGoodPct: geoGoodPctChartInstance
        };
        const inst = chartMap[chartType];
        if (!inst) return;
        const url = inst.getDataURL({
            pixelRatio: 2,
            backgroundColor: '#ffffff'
        });
        const a = document.createElement('a');
        a.download = `RHI_${chartType}_export.png`;
        a.href = url;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    // ── Smart PNG export of current dashboard view (captures all charts) ──
    window.exportSmartDashboardPNG = function () {
        if (typeof html2canvas === 'undefined') {
            console.error('html2canvas not loaded');
            return;
        }
        const pane = document.querySelector('.rhi-tab-pane.active');
        if (!pane) return;
        html2canvas(pane, {
            backgroundColor: '#ffffff',
            scale: 2,
            useCORS: true,
            logging: false
        }).then(canvas => {
            const a = document.createElement('a');
            a.download = `RHI_Dashboard_${new Date().toISOString().slice(0, 10)}.png`;
            a.href = canvas.toDataURL('image/png');
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }).catch(err => console.error('Smart PNG export failed:', err));
    };

    // ── Table Export Functions (XLSX) ─────────────────────────────────────
    window.exportNopTableXLSX = function () {
        const table = document.getElementById('nopTable');
        if (!table) return;
        const wb = XLSX.utils.book_new();
        const ws = XLSX.utils.table_to_sheet(table);
        XLSX.utils.book_append_sheet(wb, ws, 'NOP Comparison');
        XLSX.writeFile(wb, `RHI_NOP_Comparison_${new Date().toISOString().slice(0, 10)}.xlsx`);
    };

    window.exportTechTableXLSX = function () {
        const table = document.getElementById('techTable');
        if (!table) return;
        const wb = XLSX.utils.book_new();
        const ws = XLSX.utils.table_to_sheet(table);
        XLSX.utils.book_append_sheet(wb, ws, 'Tech Comparison');
        XLSX.writeFile(wb, `RHI_Tech_Comparison_${new Date().toISOString().slice(0, 10)}.xlsx`);
    };

    window.exportReasonTableXLSX = function () {
        const table = document.getElementById('reasonTable');
        if (!table) return;
        const wb = XLSX.utils.book_new();
        const ws = XLSX.utils.table_to_sheet(table);
        XLSX.utils.book_append_sheet(wb, ws, 'Reason Comparison');
        XLSX.writeFile(wb, `RHI_Reason_Comparison_${new Date().toISOString().slice(0, 10)}.xlsx`);
    };

    window.exportKabupatenTableXLSX = function () {
        const table = document.getElementById('kabupatenTable');
        if (!table) return;
        const wb = XLSX.utils.book_new();
        const ws = XLSX.utils.table_to_sheet(table);
        XLSX.utils.book_append_sheet(wb, ws, 'Kabupaten Comparison');
        XLSX.writeFile(wb, `RHI_Kabupaten_Comparison_${new Date().toISOString().slice(0, 10)}.xlsx`);
    };

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeChartEnlargeModal();
    });
    const enlargeModal = document.getElementById('chartEnlargeModal');
    if (enlargeModal) {
        enlargeModal.addEventListener('click', function (e) {
            if (e.target === enlargeModal) closeChartEnlargeModal();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // TAB 2: RHI Trend & Root Causes Logic
    // ══════════════════════════════════════════════════════════════════
    async function loadTrendCharts() {
        const sElem = document.getElementById('trendStartWeek');
        const eElem = document.getElementById('trendEndWeek');
        const startYw = sElem ? sElem.value : '';
        const endYw = eElem ? eElem.value : '';

        try {
            const res = await fetch(`/api/sow/rhi/trend?start_yw=${startYw}&end_yw=${endYw}`);
            const data = await res.json();
            if (data.status !== 'success') return;
            currentTrendData = data;

            renderTechTrendChart(data);
            renderFailReasonChart(data);
        } catch (e) {
            console.error('Error loading RHI trend charts:', e);
        }
    }

    function buildTechTrendOption(data, isDark, isEnlarged = false) {
        const labels = data.labels || [];
        const td = data.tech_data || {};
        const yRange = computeDynamicYAxisRange([td.overall, td['4g'], td['2g'], td['5g']], 85, 4);

        return {
            tooltip: { trigger: 'axis', confine: true },
            legend: {
                bottom: 0,
                textStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 13 : 11 }
            },
            grid: { left: '3%', right: '4%', top: '8%', bottom: '12%', containLabel: true },
            xAxis: {
                type: 'category',
                data: labels,
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 }
            },
            yAxis: {
                type: 'value',
                min: yRange.min,
                max: yRange.max,
                axisLabel: { formatter: '{value}%', color: isDark ? '#94a3b8' : '#64748b' },
                splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9' } }
            },
            series: [
                {
                    name: 'Overall PUMA',
                    type: 'line',
                    data: td.overall || [],
                    smooth: true,
                    lineStyle: { width: isEnlarged ? 4 : 3, color: TECH_COLORS.overall },
                    itemStyle: { color: TECH_COLORS.overall }
                },
                {
                    name: '4G Network',
                    type: 'line',
                    data: td['4g'] || [],
                    smooth: true,
                    lineStyle: { width: isEnlarged ? 3 : 2, color: TECH_COLORS['4g'] },
                    itemStyle: { color: TECH_COLORS['4g'] }
                },
                {
                    name: '2G Network',
                    type: 'line',
                    data: td['2g'] || [],
                    smooth: true,
                    lineStyle: { width: isEnlarged ? 3 : 2, color: TECH_COLORS['2g'] },
                    itemStyle: { color: TECH_COLORS['2g'] }
                },
                {
                    name: '5G Network',
                    type: 'line',
                    data: td['5g'] || [],
                    smooth: true,
                    lineStyle: { width: isEnlarged ? 3 : 2, color: TECH_COLORS['5g'] },
                    itemStyle: { color: TECH_COLORS['5g'] }
                }
            ]
        };
    }

    function renderTechTrendChart(data) {
        const dom = document.getElementById('techTrendChart');
        if (!dom) return;
        if (!techTrendChartInstance) {
            techTrendChartInstance = echarts.init(dom);
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const option = buildTechTrendOption(data, isDark, false);
        techTrendChartInstance.setOption(option, true);
        techTrendChartInstance.resize();
    }

    function buildFailReasonOption(data, isDark, isEnlarged = false) {
        const labels = data.labels || [];
        const seriesData = (data.reason_series || []).map((r, idx) => ({
            name: r.label,
            type: 'bar',
            stack: 'reasons',
            data: r.data,
            itemStyle: { color: REASON_COLORS[idx % REASON_COLORS.length] },
            barMaxWidth: isEnlarged ? 56 : 38
        }));

        return {
            tooltip: { trigger: 'axis', confine: true },
            legend: {
                bottom: 0,
                textStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12 : 10 }
            },
            grid: { left: '3%', right: '4%', top: '8%', bottom: '15%', containLabel: true },
            xAxis: {
                type: 'category',
                data: labels,
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12 : 11 }
            },
            yAxis: {
                type: 'value',
                axisLabel: { color: isDark ? '#94a3b8' : '#64748b' },
                splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9' } }
            },
            series: seriesData
        };
    }

    function renderFailReasonChart(data) {
        const dom = document.getElementById('failReasonChart');
        if (!dom) return;
        if (!failReasonChartInstance) {
            failReasonChartInstance = echarts.init(dom);
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const option = buildFailReasonOption(data, isDark, false);
        failReasonChartInstance.setOption(option, true);
        failReasonChartInstance.resize();
    }

    // Geo Trend Breakdown
    async function loadGeoOptions() {
        try {
            const res = await fetch('/api/sow/rhi/geo-options');
            const data = await res.json();
            if (data.status !== 'success') return;
            geoOptionsData = data;

            const kabSelect = document.getElementById('geoKabupaten');
            if (kabSelect) {
                kabSelect.innerHTML = '<option value="">All Kabupaten</option>' +
                    (data.kabupaten || []).map(k => `<option value="${k}">${k}</option>`).join('');
            }
            onGeoKabChange();
        } catch (e) {
            console.error('Error loading geo options:', e);
        }
    }

    window.onGeoKabChange = function () {
        const kabSelect = document.getElementById('geoKabupaten');
        const kecSelect = document.getElementById('geoKecamatan');
        const kab = kabSelect ? kabSelect.value : '';

        if (!kecSelect) return;
        if (!kab || !geoOptionsData || !geoOptionsData.kecamatan_map || !geoOptionsData.kecamatan_map[kab]) {
            kecSelect.innerHTML = '<option value="">All Kecamatan</option>';
        } else {
            const kecs = geoOptionsData.kecamatan_map[kab] || [];
            kecSelect.innerHTML = '<option value="">All Kecamatan</option>' +
                kecs.map(k => `<option value="${k}">${k}</option>`).join('');
        }
        loadGeoTrend();
    };

    window.loadGeoTrend = async function () {
        const kab = document.getElementById('geoKabupaten')?.value || '';
        const kec = document.getElementById('geoKecamatan')?.value || '';
        const tech = document.getElementById('geoTech')?.value || 'all';

        try {
            const res = await fetch(`/api/sow/rhi/geo-trend?kabupaten=${encodeURIComponent(kab)}&kecamatan=${encodeURIComponent(kec)}&tech=${tech}`);
            const data = await res.json();
            if (data.status !== 'success') return;
            currentGeoData = data;

            // Summary cards with improved detail information
            const sumBox = document.getElementById('geoSummaryContainer');
            if (sumBox && data.summary) {
                const s = data.summary;
                const isPass = s.pct >= s.target;
                const diffTgt = s.diff_target !== undefined ? s.diff_target : (s.pct - s.target).toFixed(2);
                const sign = diffTgt >= 0 ? '+' : '';
                const diffClass = diffTgt >= 0 ? 'val-pos' : 'val-neg';

                sumBox.innerHTML = `
                    <div class="rhi-geo-stat-card">
                        <span class="rhi-geo-stat-title"><i class="fas fa-map-marker-alt" style="color:#0F3B66;"></i> Scope & Target</span>
                        <span class="rhi-geo-stat-value" style="font-size:13.5px; font-weight:800;">${s.kabupaten} ${s.kecamatan !== 'All' ? '· ' + s.kecamatan : ''} (${s.tech})</span>
                        <span style="font-size:10px; color:var(--text-muted);">Target: <strong>${s.target}%</strong> · Week: <strong>W${strWeek(s.weeknum)}</strong></span>
                    </div>
                    <div class="rhi-geo-stat-card">
                        <span class="rhi-geo-stat-title"><i class="fas fa-tachometer-alt" style="color:${isPass ? '#10b981' : '#ef4444'};"></i> % Good Cell</span>
                        <span class="rhi-geo-stat-value" style="color:${isPass ? '#10b981' : '#ef4444'};">${s.pct}%</span>
                        <span class="${diffClass}" style="font-size:10px;">${sign}${diffTgt} pp (${isPass ? 'Pass' : 'Below Target'})</span>
                    </div>
                    <div class="rhi-geo-stat-card">
                        <span class="rhi-geo-stat-title"><i class="fas fa-check-circle" style="color:#10b981;"></i> Good vs Fail</span>
                        <span class="rhi-geo-stat-value" style="font-size:15px;">
                            <span style="color:#10b981;">${(s.good || 0).toLocaleString()}</span>
                            <span style="color:var(--text-muted); font-size:12px; font-weight:600;">/</span>
                            <span style="color:#ef4444;">${(s.fail || 0).toLocaleString()}</span>
                        </span>
                        <span style="font-size:10px; color:var(--text-muted);">Total: <strong>${(s.total || 0).toLocaleString()} cells</strong></span>
                    </div>
                    <div class="rhi-geo-stat-card">
                        <span class="rhi-geo-stat-title"><i class="fas fa-broadcast-tower" style="color:#2563eb;"></i> 4G Breakdown</span>
                        <span class="rhi-geo-stat-value" style="color:#2563eb; font-size:15px;">${s.pct_4g !== undefined ? s.pct_4g + '%' : '--'}</span>
                        <span style="font-size:10px; color:var(--text-muted);">${(s.good_4g || 0).toLocaleString()} of ${(s.total_4g || 0).toLocaleString()} cells</span>
                    </div>
                    <div class="rhi-geo-stat-card">
                        <span class="rhi-geo-stat-title"><i class="fas fa-broadcast-tower" style="color:#db2777;"></i> 2G Breakdown</span>
                        <span class="rhi-geo-stat-value" style="color:#db2777; font-size:15px;">${s.pct_2g !== undefined ? s.pct_2g + '%' : '--'}</span>
                        <span style="font-size:10px; color:var(--text-muted);">${(s.good_2g || 0).toLocaleString()} of ${(s.total_2g || 0).toLocaleString()} cells</span>
                    </div>
                    <div class="rhi-geo-stat-card">
                        <span class="rhi-geo-stat-title"><i class="fas fa-broadcast-tower" style="color:#10b981;"></i> 5G Breakdown</span>
                        <span class="rhi-geo-stat-value" style="color:#10b981; font-size:15px;">${s.pct_5g !== undefined ? s.pct_5g + '%' : '--'}</span>
                        <span style="font-size:10px; color:var(--text-muted);">${(s.good_5g || 0).toLocaleString()} of ${(s.total_5g || 0).toLocaleString()} cells</span>
                    </div>
                `;
            }

            renderGeoGoodPctChart(data);
        } catch (e) {
            console.error('Error loading geo trend:', e);
        }
    };

    function buildGeoGoodPctOption(data, isDark, isEnlarged = false) {
        const labels = data.labels || [];
        const seriesData = data.good_pct_series || [];
        const targetSeries = data.target_series || [];
        const yRange = computeDynamicYAxisRange([seriesData, targetSeries], 70, 5);

        // Add data point labels to % Good Cell
        const goodLineData = seriesData.map(val => ({
            value: val,
            label: {
                show: true,
                position: 'top',
                color: isDark ? '#38bdf8' : '#0F3B66',
                fontWeight: 'bold',
                fontSize: isEnlarged ? 13 : 10.5,
                formatter: `${val}%`
            }
        }));

        return {
            tooltip: { trigger: 'axis', confine: true },
            legend: { bottom: 0, textStyle: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 13 : 11 } },
            grid: { left: '3%', right: '4%', top: '8%', bottom: '12%', containLabel: true },
            xAxis: { type: 'category', data: labels, axisLabel: { color: isDark ? '#94a3b8' : '#64748b', fontSize: isEnlarged ? 12.5 : 11 } },
            yAxis: {
                type: 'value',
                min: yRange.min,
                max: yRange.max,
                axisLabel: { formatter: '{value}%', color: isDark ? '#94a3b8' : '#64748b' },
                splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9' } }
            },
            series: [
                {
                    name: '% Good Cell',
                    type: 'line',
                    data: goodLineData,
                    smooth: true,
                    lineStyle: { color: '#0F3B66', width: isEnlarged ? 3.5 : 2.5 },
                    itemStyle: { color: '#0F3B66' },
                    symbolSize: isEnlarged ? 10 : 7
                },
                {
                    name: 'Target',
                    type: 'line',
                    step: 'end',
                    data: targetSeries,
                    lineStyle: { color: '#ef4444', width: 2, type: 'dashed' },
                    itemStyle: { color: '#ef4444' },
                    symbol: 'none'
                }
            ]
        };
    }

    function renderGeoGoodPctChart(data) {
        const dom = document.getElementById('geoGoodPctChart');
        if (!dom) return;
        if (!geoGoodPctChartInstance) {
            geoGoodPctChartInstance = echarts.init(dom);
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const option = buildGeoGoodPctOption(data, isDark, false);
        geoGoodPctChartInstance.setOption(option, true);
        geoGoodPctChartInstance.resize();
    }

    // ══════════════════════════════════════════════════════════════════
    // TAB 3: Comparison Table (WoW)
    // ══════════════════════════════════════════════════════════════════
    window.loadComparison = async function () {
        const compYw = document.getElementById('compWeek')?.value || '';
        try {
            const res = await fetch(`/api/sow/rhi/comparison?weeknum=${compYw}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            // Target badge
            const tgtEl = document.getElementById('compTargetDisplay');
            if (tgtEl) {
                tgtEl.textContent = `Target: ${data.target}%`;
            }

            const weekLbl = document.getElementById('compWeekLabel');
            if (weekLbl && data.curr_week && data.prev_week) {
                weekLbl.textContent = `Comparing W${strWeek(data.curr_week)} vs W${strWeek(data.prev_week)}`;
                document.getElementById('thPrevWeek').textContent = `Previous Week (W${strWeek(data.prev_week)})`;
                document.getElementById('thCurrWeek').textContent = `Current Week (W${strWeek(data.curr_week)})`;
            }

            // 1. NOP Table (Vendor column removed, Δ WoW, Target Status, WoW Status)
            const nopTbody = document.querySelector('#nopTable tbody');
            if (nopTbody && data.rows) {
                nopTbody.innerHTML = data.rows.map(r => {
                    const isRegional = r.nop === 'PUMA';
                    const trClass = isRegional ? 'row-regional' : '';
                    const stTargetBadge = r.st_target === 'Pass' ? '<span class="badge-pass">Pass</span>' : '<span class="badge-fail">Not Pass</span>';
                    const isImproved = r.st_wow === 'Improved';
                    const isDegraded = r.st_wow === 'Degraded';
                    const stWowBadge = isImproved ? '<span class="badge-pass">Improved</span>' : (isDegraded ? '<span class="badge-fail">Degraded</span>' : '<span style="color:var(--text-muted);">Stable</span>');

                    const dTargetClass = r.delta_target >= 0 ? 'val-pos' : 'val-neg';
                    const dWowClass = r.ach_wow >= 0 ? 'val-pos' : 'val-neg';

                    return `
                        <tr class="${trClass}">
                            <td><strong>${r.nop}</strong></td>
                            <td>${r.target}%</td>
                            <td>${(r.prev_total || 0).toLocaleString()}</td>
                            <td>${(r.prev_good || 0).toLocaleString()}</td>
                            <td>${(r.prev_bad || 0).toLocaleString()}</td>
                            <td><strong>${r.prev_ach}%</strong></td>
                            <td>${(r.curr_total || 0).toLocaleString()}</td>
                            <td>${(r.curr_good || 0).toLocaleString()}</td>
                            <td>${(r.curr_bad || 0).toLocaleString()}</td>
                            <td><strong>${r.curr_ach}%</strong></td>
                            <td class="${dTargetClass}"><strong>${r.delta_target > 0 ? '+' : ''}${r.delta_target}%</strong></td>
                            <td class="${dWowClass}"><strong>${r.ach_wow > 0 ? '+' : ''}${r.ach_wow}%</strong></td>
                            <td>${stTargetBadge}</td>
                            <td>${stWowBadge}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 2. Tech WoW Table
            const techTbody = document.querySelector('#techTable tbody');
            if (techTbody && data.tech_wow) {
                techTbody.innerHTML = data.tech_wow.map(t => {
                    const isPos = t.delta >= 0;
                    const dClass = isPos ? 'val-pos' : 'val-neg';
                    const remBadge = isPos ? '<span class="badge-pass">Improve</span>' : '<span class="badge-fail">Degrade</span>';
                    return `
                        <tr>
                            <td><strong>${t.tech}</strong></td>
                            <td>${(t.prev_total || 0).toLocaleString()}</td>
                            <td>${t.prev_ach}%</td>
                            <td>${(t.curr_total || 0).toLocaleString()}</td>
                            <td><strong>${t.curr_ach}%</strong></td>
                            <td class="${dClass}"><strong>${t.delta > 0 ? '+' : ''}${t.delta}%</strong></td>
                            <td>${remBadge}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 3. Reasons WoW Table
            const reasonTbody = document.querySelector('#reasonTable tbody');
            if (reasonTbody && data.reasons_wow) {
                reasonTbody.innerHTML = data.reasons_wow.map(r => {
                    const isImprove = r.remark === 'Improve';
                    const remBadge = isImprove ? '<span class="badge-pass">Improve</span>' : (r.remark === 'Degrade' ? '<span class="badge-fail">Degrade</span>' : '<span style="color:var(--text-muted);">Stable</span>');
                    const dClass = isImprove ? 'val-pos' : (r.delta > 0 ? 'val-neg' : '');

                    return `
                        <tr>
                            <td style="text-align:left; padding-left:12px;"><strong>${r.title}</strong></td>
                            <td>${(r.before || 0).toLocaleString()}</td>
                            <td><strong>${(r.after || 0).toLocaleString()}</strong></td>
                            <td class="${dClass}"><strong>${r.delta > 0 ? '+' : ''}${r.delta}</strong></td>
                            <td class="${dClass}">${r.delta_pct > 0 ? '+' : ''}${r.delta_pct}%</td>
                            <td>${remBadge}</td>
                        </tr>
                    `;
                }).join('');
            }
        } catch (e) {
            console.error('Error loading comparison:', e);
        }
    };

    window.loadKabupatenComparison = async function () {
        const compYw = document.getElementById('compWeek')?.value || '';
        const branch = document.getElementById('kabFilterBranch')?.value || 'ALL';
        const tech = document.getElementById('kabFilterTech')?.value || 'ALL';

        try {
            const res = await fetch(`/api/sow/rhi/kabupaten-comparison?weeknum=${compYw}&branch=${branch}&tech=${tech}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            rawKabupatenData = data.rows || [];
            renderKabupatenTable(rawKabupatenData);
        } catch (e) {
            console.error('Error loading kabupaten comparison:', e);
        }
    };

    function renderKabupatenTable(rows) {
        const tbody = document.querySelector('#kabupatenTable tbody');
        if (!tbody) return;

        if (!rows || rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding:18px; color:var(--text-muted);">No matching kabupaten data found</td></tr>';
            return;
        }

        tbody.innerHTML = rows.map(r => {
            const stTargetBadge = r.st_target === 'Pass' ? '<span class="badge-pass">Pass</span>' : '<span class="badge-fail">Not Pass</span>';
            const isImproved = r.st_wow === 'Improved';
            const isDegraded = r.st_wow === 'Degraded';
            const stWowBadge = isImproved ? '<span class="badge-pass">Improved</span>' : (isDegraded ? '<span class="badge-fail">Degraded</span>' : '<span style="color:var(--text-muted);">Stable</span>');

            const dTargetClass = r.delta_target >= 0 ? 'val-pos' : 'val-neg';
            const dWowClass = r.ach_wow >= 0 ? 'val-pos' : 'val-neg';

            return `
                <tr>
                    <td><strong>${r.branch}</strong></td>
                    <td style="text-align:left; padding-left:14px;"><strong>${r.kabupaten}</strong></td>
                    <td>${r.target}%</td>
                    <td>${r.prev_ach}%</td>
                    <td><strong>${r.curr_ach}%</strong></td>
                    <td class="${dTargetClass}"><strong>${r.delta_target > 0 ? '+' : ''}${r.delta_target}%</strong></td>
                    <td class="${dWowClass}"><strong>${r.ach_wow > 0 ? '+' : ''}${r.ach_wow}%</strong></td>
                    <td>${stTargetBadge}</td>
                    <td>${stWowBadge}</td>
                    <td>${(r.curr_total || 0).toLocaleString()}</td>
                    <td style="color:#10b981; font-weight:600;">${(r.curr_good || 0).toLocaleString()}</td>
                    <td style="color:#ef4444; font-weight:600;">${(r.curr_bad || 0).toLocaleString()}</td>
                </tr>
            `;
        }).join('');
    }

    window.filterKabupatenTable = function () {
        const query = (document.getElementById('kabSearchInput')?.value || '').trim().toUpperCase();
        if (!query) {
            renderKabupatenTable(rawKabupatenData);
            return;
        }
        const filtered = rawKabupatenData.filter(r => (r.kabupaten || '').toUpperCase().includes(query) || (r.branch || '').toUpperCase().includes(query));
        renderKabupatenTable(filtered);
    };

    function strWeek(yw) {
        if (!yw) return '--';
        const s = String(yw);
        return s.length >= 6 ? s.substring(4) : s;
    }

    // ══════════════════════════════════════════════════════════════════
    // Data Import Modal Logic
    // ══════════════════════════════════════════════════════════════════
    window.openRhiImportModal = function () {
        const modal = document.getElementById('rhiImportModal');
        if (modal) modal.style.display = 'flex';
        resetRhiImportState();
    };

    window.closeRhiImportModal = function () {
        const modal = document.getElementById('rhiImportModal');
        if (modal) modal.style.display = 'none';
        resetRhiImportState();
    };

    // ══════════════════════════════════════════════════════════════════
    // Multi-File Batch Queue Importer
    // ══════════════════════════════════════════════════════════════════
    let rhiFileQueue = [];
    let isRhiQueueRunning = false;
    let rhiQueueAborted = false;

    window.openRhiImportModal = function () {
        const modal = document.getElementById('rhiImportModal');
        if (modal) modal.style.display = 'flex';
        initDropZoneEvents();
    };

    window.closeRhiImportModal = function () {
        if (isRhiQueueRunning) {
            if (!confirm('An import queue is currently running. Are you sure you want to cancel and close?')) {
                return;
            }
            rhiQueueAborted = true;
        }
        const hadSuccess = rhiFileQueue.some(f => f.status === 'done');
        const modal = document.getElementById('rhiImportModal');
        if (modal) modal.style.display = 'none';
        resetRhiImportState();
        if (hadSuccess) {
            window.location.reload();
        }
    };

    function resetRhiImportState() {
        rhiFileQueue = [];
        isRhiQueueRunning = false;
        rhiQueueAborted = false;
        const fileInput = document.getElementById('rhiFileInput');
        if (fileInput) fileInput.value = '';
        renderRhiQueueUI();
        const alertBox = document.getElementById('rhiImportAlert');
        if (alertBox) {
            alertBox.style.display = 'none';
            alertBox.innerHTML = '';
        }
        const prog = document.getElementById('rhiQueueOverallProgress');
        if (prog) prog.style.display = 'none';
        const curFileStage = document.getElementById('rhiCurrentFileStage');
        if (curFileStage) curFileStage.textContent = 'Ready';
        const curFilePct = document.getElementById('rhiCurrentFilePct');
        if (curFilePct) curFilePct.textContent = '--';
        const overallBar = document.getElementById('rhiOverallProgressBar');
        if (overallBar) overallBar.style.width = '0%';
        const overallPct = document.getElementById('rhiOverallPct');
        if (overallPct) overallPct.textContent = '0%';
        const overallStage = document.getElementById('rhiOverallStage');
        if (overallStage) overallStage.textContent = 'Overall Queue: 0 of 0';
    }

    window.clearRhiQueue = function () {
        if (isRhiQueueRunning) return;
        resetRhiImportState();
    };

    function initDropZoneEvents() {
        const dropZone = document.getElementById('rhiDropZone');
        if (!dropZone || dropZone._hasEvents) return;
        dropZone._hasEvents = true;

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.background = 'rgba(15, 59, 102, 0.12)';
                dropZone.style.borderColor = '#0284c7';
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
                addFilesToRhiQueue(dt.files);
            }
        }, false);
    }

    window.handleRhiFileSelect = function (input) {
        if (input.files && input.files.length) {
            addFilesToRhiQueue(input.files);
            input.value = '';
        }
    };

    function addFilesToRhiQueue(files) {
        if (isRhiQueueRunning) return;
        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const ext = f.name.toLowerCase().split('.').pop();
            if (!['xlsx', 'xls', 'csv'].includes(ext)) {
                continue;
            }
            if (rhiFileQueue.some(item => item.name === f.name && item.size === f.size)) {
                continue;
            }
            rhiFileQueue.push({
                id: 'rhi_q_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
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
        renderRhiQueueUI();
    }

    // Helper to format seconds into readable string (e.g. 14s, 1m 25s)
    function formatDuration(sec) {
        if (!sec || isNaN(sec) || sec < 0) return '0s';
        sec = Math.round(sec);
        if (sec < 60) return `${sec}s`;
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return `${m}m ${s}s`;
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

    function renderRhiQueueUI() {
        const sec = document.getElementById('rhiQueueSection');
        const list = document.getElementById('rhiQueueListContainer');
        const countEl = document.getElementById('rhiQueueTotalCount');
        const sizeEl = document.getElementById('rhiQueueTotalSize');
        const btnCount = document.getElementById('rhiQueueBtnCount');
        const submitBtn = document.getElementById('btnSubmitRhiImport');
        const addMoreBtn = document.getElementById('btnAddMoreFiles');
        const clearBtn = document.getElementById('btnClearRhiQueue');

        if (!rhiFileQueue.length) {
            if (sec) sec.style.display = 'none';
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-upload"></i> Upload & Import (0)';
            }
            if (addMoreBtn) addMoreBtn.style.display = 'none';
            return;
        }

        if (sec) sec.style.display = 'block';
        if (addMoreBtn) addMoreBtn.style.display = isRhiQueueRunning ? 'none' : 'inline-block';
        if (clearBtn) clearBtn.style.display = isRhiQueueRunning ? 'none' : 'inline-block';

        const totalBytes = rhiFileQueue.reduce((acc, f) => acc + f.size, 0);
        const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);

        if (countEl) countEl.textContent = rhiFileQueue.length;
        if (sizeEl) sizeEl.textContent = `${totalMb} MB`;

        if (submitBtn && !isRhiQueueRunning) {
            const allDone = rhiFileQueue.length > 0 && rhiFileQueue.every(f => f.status === 'done');
            if (allDone) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Import Complete';
            } else {
                const pendingCount = rhiFileQueue.filter(f => f.status !== 'done').length;
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<i class="fas fa-upload"></i> Upload & Import (${pendingCount})`;
            }
        }

        if (list) {
            list.innerHTML = rhiFileQueue.map((item, idx) => {
                let badgeHtml = '';
                const sizeMb = (item.size / (1024 * 1024)).toFixed(1);

                if (item.status === 'pending') {
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(0,0,0,0.06); color:var(--text-muted); font-weight:700;">Waiting</span>`;
                } else if (item.status === 'uploading' || item.status === 'processing') {
                    const elap = item.elapsed_s ? ` · ${formatDuration(item.elapsed_s)}` : '';
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(37,99,235,0.12); color:#2563eb; font-weight:700;">
                        <i class="fas fa-spinner fa-spin"></i> ${item.pct || 0}%${elap}
                    </span>`;
                } else if (item.status === 'done') {
                    const wText = (item.weeks && item.weeks.length) ? item.weeks.map(w => 'W' + String(w).slice(4)).join(',') : 'Done';
                    const rText = item.rows ? ` (${item.rows.toLocaleString()} rows)` : '';
                    const dText = item.duration_str ? ` in ${item.duration_str}` : '';
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(16,185,129,0.15); color:#10b981; font-weight:700;">
                        <i class="fas fa-check"></i> ${wText}${rText}${dText}
                    </span>`;
                } else if (item.status === 'error') {
                    const dText = item.duration_str ? ` (${item.duration_str})` : '';
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(239,68,68,0.15); color:#ef4444; font-weight:700;" title="${item.message}">
                        <i class="fas fa-exclamation-triangle"></i> Error${dText}
                    </span>`;
                }

                let extraMeta = `${sizeMb} MB`;
                if (item.duration_str) {
                    extraMeta += ` • ${item.duration_str}`;
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
                    <div id="${item.id}" style="padding: 6px 10px; background:#ffffff; border:1px solid var(--border); border-radius:6px; font-size:11.5px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div style="display:flex; align-items:center; gap:8px; overflow:hidden; margin-right:8px;">
                                <span style="font-weight:700; color:var(--text-muted); font-size:10px; width:16px;">#${idx + 1}</span>
                                <i class="fas fa-file-excel" style="color:#10b981; flex-shrink:0;"></i>
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

    window.startRhiQueueImport = async function () {
        if (!rhiFileQueue.length || isRhiQueueRunning) return;

        isRhiQueueRunning = true;
        rhiQueueAborted = false;

        const submitBtn = document.getElementById('btnSubmitRhiImport');
        const addMoreBtn = document.getElementById('btnAddMoreFiles');
        const clearBtn = document.getElementById('btnClearRhiQueue');
        const alertBox = document.getElementById('rhiImportAlert');
        const overallProg = document.getElementById('rhiQueueOverallProgress');
        const overallBar = document.getElementById('rhiOverallProgressBar');
        const overallStage = document.getElementById('rhiOverallStage');
        const overallPct = document.getElementById('rhiOverallPct');
        const curFileStage = document.getElementById('rhiCurrentFileStage');
        const curFilePct = document.getElementById('rhiCurrentFilePct');

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
        const queueStartTime = Date.now();
        let currentActiveItem = null;
        let currentActiveIndex = -1;

        const totalFiles = rhiFileQueue.length;

        // Periodic live timer update for active item and overall queue
        const queueTimerInterval = setInterval(() => {
            if (!isRhiQueueRunning) {
                clearInterval(queueTimerInterval);
                return;
            }
            const totalElapsed = Math.round((Date.now() - queueStartTime) / 1000);
            if (overallStage && currentActiveIndex >= 0) {
                overallStage.textContent = `Overall: File ${currentActiveIndex + 1} of ${totalFiles} · Total elapsed: ${formatDuration(totalElapsed)}`;
            }
            if (currentActiveItem && currentActiveItem.startTime) {
                currentActiveItem.elapsed_s = Math.round((Date.now() - currentActiveItem.startTime) / 1000);
                renderRhiQueueUI();
            }
        }, 1000);

        for (let i = 0; i < totalFiles; i++) {
            if (rhiQueueAborted) break;

            currentActiveIndex = i;
            const item = rhiFileQueue[i];
            currentActiveItem = item;

            if (item.status === 'done') {
                successCount++;
                continue;
            }

            const currentFileNum = i + 1;
            const overallProgressValue = Math.round((i / totalFiles) * 100);
            const totalElapsedSec = Math.round((Date.now() - queueStartTime) / 1000);

            if (overallStage) overallStage.textContent = `Overall: File ${currentFileNum} of ${totalFiles} (${item.name}) · Elapsed: ${formatDuration(totalElapsedSec)}`;
            if (overallPct) overallPct.textContent = `${overallProgressValue}%`;
            if (overallBar) overallBar.style.width = `${overallProgressValue}%`;

            item.startTime = Date.now();
            item.elapsed_s = 0;
            item.status = 'uploading';
            item.pct = 5;
            item.message = 'Uploading file...';
            renderRhiQueueUI();

            try {
                const formData = new FormData();
                formData.append('file', item.file);

                if (curFileStage) curFileStage.textContent = `Uploading ${item.name}...`;
                if (curFilePct) curFilePct.textContent = '5%';

                // Real-time XHR upload progress for large 45MB files
                const uploadRes = await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', '/api/sow/rhi/import');
                    xhr.upload.onprogress = function(e) {
                        if (e.lengthComputable) {
                            const upPct = Math.round((e.loaded / e.total) * 100);
                            const upMb = (e.loaded / (1024 * 1024)).toFixed(1);
                            const totMb = (e.total / (1024 * 1024)).toFixed(1);
                            item.pct = Math.min(25, Math.round(upPct * 0.25));
                            item.message = `Uploading ${upMb}/${totMb} MB (${upPct}%)...`;
                            item.elapsed_s = Math.round((Date.now() - item.startTime) / 1000);
                            if (curFileStage) curFileStage.textContent = `${item.name}: Uploading ${upMb}/${totMb} MB (${upPct}%) · ${formatDuration(item.elapsed_s)}`;
                            if (curFilePct) curFilePct.textContent = `${upPct}%`;
                            renderRhiQueueUI();
                        }
                    };
                    xhr.onload = function() {
                        if (xhr.status >= 200 && xhr.status < 300) {
                            try { resolve(JSON.parse(xhr.responseText)); }
                            catch(err) { reject(new Error('Invalid response')); }
                        } else {
                            try {
                                const errData = JSON.parse(xhr.responseText);
                                reject(new Error(errData.message || `Upload failed (HTTP ${xhr.status})`));
                            } catch(err) {
                                reject(new Error(`Upload failed (HTTP ${xhr.status})`));
                            }
                        }
                    };
                    xhr.onerror = function() { reject(new Error('Network upload failed')); };
                    xhr.send(formData);
                });

                if (uploadRes.status === 'queued' && uploadRes.job_id) {
                    item.status = 'processing';
                    item.pct = 25;
                    item.message = 'Parsing and streaming to database...';
                    if (curFileStage) curFileStage.textContent = `${item.name}: Streaming to database...`;
                    renderRhiQueueUI();

                    // Poll progress until done
                    await new Promise((resolve) => {
                        const poll = setInterval(async () => {
                            if (rhiQueueAborted) {
                                clearInterval(poll);
                                resolve();
                                return;
                            }
                            try {
                                const pres = await fetch(`/api/sow/rhi/import/progress/${uploadRes.job_id}`);
                                const pdata = await pres.json();

                                if (pdata.status !== 'queued') {
                                    item.pct = pdata.pct || 30;
                                    item.message = pdata.message || pdata.status;
                                    item.elapsed_s = Math.round((Date.now() - item.startTime) / 1000);
                                    if (curFileStage) curFileStage.textContent = `${item.name}: ${pdata.message || pdata.status} · ${formatDuration(item.elapsed_s)}`;
                                    if (curFilePct) curFilePct.textContent = `${pdata.pct || 0}%`;
                                    renderRhiQueueUI();
                                }

                                if (pdata.status === 'success') {
                                    clearInterval(poll);
                                    item.status = 'done';
                                    item.pct = 100;
                                    item.rows = pdata.total_rows || 0;
                                    item.weeks = pdata.weeknums || [];
                                    item.duration_s = pdata.duration_s || Math.round((Date.now() - item.startTime) / 1000);
                                    item.duration_str = pdata.duration_str || formatDuration(item.duration_s);
                                    item.message = pdata.message;
                                    successCount++;
                                    totalRowsImported += (pdata.total_rows || 0);
                                    (pdata.weeknums || []).forEach(w => allWeeksImported.add(w));
                                    renderRhiQueueUI();
                                    resolve();
                                } else if (pdata.status === 'error') {
                                    clearInterval(poll);
                                    item.status = 'error';
                                    item.message = pdata.message || 'Import error';
                                    item.duration_s = Math.round((Date.now() - item.startTime) / 1000);
                                    item.duration_str = formatDuration(item.duration_s);
                                    failCount++;
                                    renderRhiQueueUI();
                                    resolve();
                                }
                            } catch (e) {
                                // transient poll error
                            }
                        }, 500);

                        // 15 min per file timeout
                        setTimeout(() => {
                            clearInterval(poll);
                            if (item.status !== 'done') {
                                item.status = 'error';
                                item.message = 'Timeout';
                                item.duration_s = Math.round((Date.now() - item.startTime) / 1000);
                                item.duration_str = formatDuration(item.duration_s);
                                failCount++;
                                renderRhiQueueUI();
                            }
                            resolve();
                        }, 900000);
                    });
                } else {
                    item.status = 'error';
                    item.message = uploadRes.message || 'Upload failed';
                    item.duration_s = Math.round((Date.now() - item.startTime) / 1000);
                    item.duration_str = formatDuration(item.duration_s);
                    failCount++;
                    renderRhiQueueUI();
                }
            } catch (err) {
                item.status = 'error';
                item.message = err.message || 'Network error';
                item.duration_s = Math.round((Date.now() - item.startTime) / 1000);
                item.duration_str = formatDuration(item.duration_s);
                failCount++;
                renderRhiQueueUI();
            }
        }

        clearInterval(queueTimerInterval);
        const totalQueueSec = Math.round((Date.now() - queueStartTime) / 1000);
        const totalQueueStr = formatDuration(totalQueueSec);
        const avgSec = totalFiles ? Math.round(totalQueueSec / totalFiles) : 0;

        // Final overall progress
        if (overallBar) overallBar.style.width = '100%';
        if (overallPct) overallPct.textContent = '100%';
        if (overallStage) overallStage.textContent = `Completed ${successCount} of ${totalFiles} files in ${totalQueueStr} (avg ${avgSec}s/file)`;
        if (curFileStage) curFileStage.textContent = 'All files processed.';
        if (curFilePct) curFilePct.textContent = 'Done';

        isRhiQueueRunning = false;
        renderRhiQueueUI();

        if (submitBtn) {
            if (successCount > 0) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Import Complete (Close & Refresh)';
                submitBtn.onclick = function () {
                    closeRhiImportModal();
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
        fetch('/api/sow/rhi/summary?refresh=1').catch(() => {});
    };

})();
