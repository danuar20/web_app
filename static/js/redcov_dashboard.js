/**
 * Redcov Dashboard JavaScript
 * Multi-Tab Bad Spot Red Coverage Monitoring Dashboard:
 *   1. Redcov Achievement (2-Pane Layout: WoW Cards, Distribution Track with Anti-Collision & Black Dashed Target Line + Branch Chips Row like RHI, Swapped 2 Charts with Light Green Good Cov & Dark Red Segments + Value Labels on Points)
 *   2. Trend & Regional Analysis (Dynamic Quality Cards with WoW, Unlinked Top Contributors with 175px Left Margin, Dual-Axis Quality Indicators Trend linked to Tab 2 Filters)
 *   3. Comparison Table (Table 1: NOP / Branch Level with Regional Total, Table 2: Kabupaten Level with Inline Selectable NOP, Target, and Search)
 *   4. Data Import & Template Download
 */

(function () {
    'use strict';

    // Global ECharts Instances
    let chartCoverageTrend = null;
    let chartRedBreakdown = null;
    let chartNopTrend = null;
    let chartTopContributors = null;
    let chartNopWeeklyBar = null;
    let chartQualityTrend = null;
    let chartKabTrend = null;
    let chartKabBreakdown = null;
    let chartEnlargedInstance = null;
    let currentEnlargedType = null;

    // State
    let activeTab = 'achievement';
    let activeBranch = 'ALL';
    let coverageMetricMode = 'count'; // 'count' or 'share'
    let currentSummaryData = null;
    let currentTrendData = null;
    let rawComparisonData = [];
    let rawNopComparisonData = [];
    let rawTotalNopData = null;
    let sortColumn = 'red_optim';
    let sortDirection = 'desc';
    let selectedFile = null;

    // Palette: Dark Red palette for Red Coverage, Forest Green for Good Cov, distinct distinct styling for Target & Line
    const THEME_COLORS = {
        // Trend Coverage
        goodCov: '#15803d',        // Dark Green (forest/emerald dark green per instruction)
        redCov: '#8B0000',         // Dark Red
        redCovLine: '#0f172a',     // Dark Charcoal line with contrast white tag

        // Red Breakdown (Dark Red palette per instruction)
        redOptim: '#8B0000',       // Dark Red
        redEng: '#4c0519',         // Very Dark Rose / Wine
        redOptimLine: '#ea580c',   // Warm Vibrant Amber-Orange (contrasts with dark red bars and white pills)
        targetLine: '#000000',     // Dynamic Target (Dashed Line)

        // NOP Series
        nopAmbon: '#3b82f6',       // Bright Royal Blue (clearly visible in dark mode!)
        nopJayapura: '#f97316',    // Bright Orange
        nopTimika: '#10b981',      // Emerald Green
        nopSorong: '#06b6d4',      // Bright Cyan
    };

    // Helper: Get Theme-adaptive Colors for ECharts
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
            lineRedCov: isDark ? '#38bdf8' : '#0f172a',
            tooltipBg: isDark ? 'rgba(15, 23, 42, 0.96)' : 'rgba(255, 255, 255, 0.98)',
            tooltipBorder: isDark ? '#334155' : '#cbd5e1',
            tooltipText: isDark ? '#f8fafc' : '#0f172a'
        };
    }

    // Shared Frosted Tooltip Styling for ECharts
    const TOOLTIP_STYLE = {
        backgroundColor: 'rgba(15, 23, 42, 0.96)',
        borderColor: '#334155',
        borderWidth: 1,
        padding: [10, 14],
        textStyle: { color: '#f8fafc', fontSize: 11.5, fontFamily: 'inherit' },
        extraCssText: 'box-shadow: 0 10px 25px rgba(0,0,0,0.35); border-radius: 8px;'
    };

    function getTooltipStyle(theme) {
        return {
            backgroundColor: theme ? theme.tooltipBg : TOOLTIP_STYLE.backgroundColor,
            borderColor: theme ? theme.tooltipBorder : TOOLTIP_STYLE.borderColor,
            borderWidth: 1,
            padding: [10, 14],
            textStyle: { color: theme ? theme.tooltipText : TOOLTIP_STYLE.textStyle.color, fontSize: 11.5, fontFamily: 'inherit' },
            extraCssText: 'box-shadow: 0 10px 25px rgba(0,0,0,0.35); border-radius: 8px;'
        };
    }

    // DOM Ready
    document.addEventListener('DOMContentLoaded', function () {
        initSidebarObserver();
        initDashboard();
    });

    // ── Tab Management ──
    window.switchRedcovTab = function (tabId, btnElem) {
        activeTab = tabId;
        document.querySelectorAll('.redcov-tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.redcov-tab-pane').forEach(pane => pane.classList.remove('active'));

        if (btnElem) {
            btnElem.classList.add('active');
        }
        const targetPane = document.getElementById(`pane-${tabId}`);
        if (targetPane) {
            targetPane.classList.add('active');
        }

        setTimeout(resizeAllVisibleCharts, 50);
        setTimeout(resizeAllVisibleCharts, 250);
    };

    function resizeAllVisibleCharts() {
        if (activeTab === 'achievement') {
            if (chartCoverageTrend) chartCoverageTrend.resize();
            if (chartRedBreakdown) chartRedBreakdown.resize();
        } else if (activeTab === 'trend') {
            if (chartNopTrend) chartNopTrend.resize();
            if (chartTopContributors) chartTopContributors.resize();
            if (chartNopWeeklyBar) chartNopWeeklyBar.resize();
            if (chartQualityTrend) chartQualityTrend.resize();
            if (chartKabTrend) chartKabTrend.resize();
            if (chartKabBreakdown) chartKabBreakdown.resize();
        }
    }

    window.addEventListener('resize', resizeAllVisibleCharts);

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

        // Theme Observer: Re-render charts when switching between light and dark modes!
        function handleThemeSwitch() {
            if (currentTrendData) {
                renderCoverageTrendChart(currentTrendData);
                renderRedBreakdownChart(currentTrendData);
                renderTab2Charts();
                if (window.loadKabupatenTrendCharts) window.loadKabupatenTrendCharts();
            }
            if (currentSummaryData) {
                renderBranchDistribution(currentSummaryData.branch_distrib, currentSummaryData.target, currentSummaryData.current.red_optim_pct);
            }
        }

        window.updateAllChartsTheme = function () {
            handleThemeSwitch();
        };

        if (window.MutationObserver) {
            const themeObserver = new MutationObserver(function (mutations) {
                mutations.forEach(function (m) {
                    if (m.type === 'attributes' && m.attributeName === 'data-theme') {
                        handleThemeSwitch();
                    }
                });
            });
            themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        }
    }

    // ── Dashboard Initialization ──
    async function initDashboard() {
        await loadSummary();
        await loadTrend();
        await loadComparisonTable();
    }

    // ── Filter Handlers (Tab 1) ──
    window.onRegionChange = function () {
        const reg = document.getElementById('filterRegion').value;
        const chip = document.getElementById('chipRegionName');
        if (chip) chip.textContent = reg;
        document.querySelectorAll('.lblRegion').forEach(el => el.textContent = reg === 'MALUKU DAN PAPUA' ? 'PUMA' : reg);

        updateExportLink();
        loadSummary();
        loadTrend();
        loadComparisonTable();
    };

    window.onBranchChange = function () {
        activeBranch = document.getElementById('filterBranch').value;
        const chipWrapper = document.getElementById('chipBranchWrapper');
        const chip = document.getElementById('chipBranchName');
        const scopeBadge = document.getElementById('bannerScopeBadge');

        if (activeBranch && activeBranch !== 'ALL') {
            if (chipWrapper) chipWrapper.style.display = 'inline-flex';
            if (chip) chip.textContent = activeBranch;
            if (scopeBadge) scopeBadge.textContent = `${activeBranch} NOP`;
        } else {
            if (chipWrapper) chipWrapper.style.display = 'none';
            if (scopeBadge) scopeBadge.textContent = 'ALL NOPS';
        }

        // Also update Table 2's inline selector
        const kabBranch = document.getElementById('kabFilterBranch');
        if (kabBranch) {
            kabBranch.value = activeBranch;
        }

        loadSummary();
        loadTrend();
        filterComparisonTable();
    };

    window.onWeekFilterChange = function () {
        updateExportLink();
        loadSummary();
    };

    window.onTrendFilterChange = function () {
        loadTrend();
    };

    function updateExportLink() {
        const week = document.getElementById('filterWeek').value;
        const reg = document.getElementById('filterRegion').value;
        const btnExport = document.getElementById('btnExportCsv');
        if (btnExport) btnExport.href = `/api/sow/redcov/export?week=${week}&region=${encodeURIComponent(reg)}`;
    }

    // ── Metric Mode (Count vs Share) on Coverage Trend ──
    window.setCoverageMetricMode = function (mode, btn) {
        coverageMetricMode = mode;
        document.getElementById('btnCovCount').classList.toggle('active', mode === 'count');
        document.getElementById('btnCovShare').classList.toggle('active', mode === 'share');
        if (currentTrendData) {
            renderCoverageTrendChart(currentTrendData);
        }
    };

    // ── Tab 2 Dedicated Filter Handler ──
    window.onTrendTabFilterChange = async function () {
        const nopFilter = document.getElementById('trendNopSelect') ? document.getElementById('trendNopSelect').value : 'ALL';
        const region = document.getElementById('filterRegion').value;
        const startWeek = document.getElementById('filterStartWeek').value;
        const endWeek = document.getElementById('filterWeek').value;

        // Fetch NOP-specific trend if filter changed
        try {
            const branchParam = nopFilter !== 'ALL' ? `&branch=${encodeURIComponent(nopFilter)}` : '';
            const res = await fetch(`/api/sow/redcov/trend?region=${encodeURIComponent(region)}&start_week=${startWeek}&end_week=${endWeek}${branchParam}`);
            const data = await res.json();
            if (data.status === 'success') {
                renderTab2Charts(data, nopFilter);
            }
        } catch (e) {
            console.error('Error updating Tab 2 filters:', e);
            renderTab2Charts(currentTrendData, nopFilter);
        }
    };

    // ── Load Summary & Executive KPIs ──
    async function loadSummary() {
        const region = document.getElementById('filterRegion').value;
        const week = document.getElementById('filterWeek').value;
        const branchParam = activeBranch !== 'ALL' ? `&branch=${encodeURIComponent(activeBranch)}` : '';

        try {
            const res = await fetch(`/api/sow/redcov/summary?region=${encodeURIComponent(region)}&week=${week}${branchParam}`);
            const data = await res.json();
            if (data.status !== 'success') {
                console.error('Summary fetch error:', data.message);
                return;
            }

            currentSummaryData = data;

            // Top Executive Banner
            const bannerRegion = document.getElementById('bannerRegionTitle');
            if (bannerRegion) {
                const scopeTitle = activeBranch !== 'ALL' ? `${activeBranch} NOP` : (region === 'MALUKU DAN PAPUA' ? 'PUMA' : region);
                bannerRegion.textContent = scopeTitle;
            }
            const bannerWeek = document.getElementById('bannerWeekNum');
            if (bannerWeek) bannerWeek.textContent = String(data.yearweek).substring(4);
            const bannerBase = document.getElementById('bannerBaseline');
            if (bannerBase) bannerBase.textContent = Number(data.baseline || 0.31).toFixed(2);
            const bannerTarget = document.getElementById('bannerTarget');
            if (bannerTarget) bannerTarget.textContent = Number(data.target || 0.23).toFixed(2);
            const bannerTargetLbl = document.getElementById('bannerTargetLabel');
            if (bannerTargetLbl) bannerTargetLbl.textContent = `Target (${data.target_label || 'Q3'})`;

            const bannerAch = document.getElementById('bannerAch');
            if (bannerAch) bannerAch.textContent = Number(data.red_optim_pct || 0).toFixed(2);

            const bannerGap = document.getElementById('bannerGap');
            if (bannerGap) {
                const gap = Number(data.ach_gap || 0);
                bannerGap.textContent = (gap >= 0 ? `+${gap.toFixed(2)}` : `${gap.toFixed(2)}`);
                bannerGap.style.color = gap >= 0 ? '#a7f3d0' : '#fecaca';
            }

            // Card 1: % Red Cov (with WoW delta)
            const cardRedCov = document.getElementById('cardRedCovPct');
            if (cardRedCov) cardRedCov.textContent = `${Number(data.red_cov_pct || 0).toFixed(2)}%`;
            const cardRedCovSub = document.getElementById('cardRedCovSub');
            if (cardRedCovSub) cardRedCovSub.textContent = `W${String(data.yearweek).substring(4)}: ${(data.total_red_cov || 0).toLocaleString()} Grids`;
            const cardRedCovWow = document.getElementById('cardRedCovWow');
            if (cardRedCovWow) {
                const d = data.diff_cov_prev_pp;
                if (d !== null && d !== undefined) {
                    const isImp = d <= 0; // lower red coverage is better
                    const sign = d > 0 ? `+${d.toFixed(2)}` : `${d.toFixed(2)}`;
                    const color = isImp ? '#059669' : '#dc2626';
                    cardRedCovWow.innerHTML = `<span style="color:${color};"><i class="fas fa-${d <= 0 ? 'arrow-down' : 'arrow-up'}"></i> ${sign} pp WoW</span>`;
                } else {
                    cardRedCovWow.innerHTML = `<span style="color:var(--text-muted);">- pp WoW</span>`;
                }
            }

            // Card 2: % Red Optim Ach. (with WoW delta)
            const cardRedOptim = document.getElementById('cardRedOptimPct');
            if (cardRedOptim) cardRedOptim.textContent = `${Number(data.red_optim_pct || 0).toFixed(2)}%`;
            const cardRedOptimSub = document.getElementById('cardRedOptimSub');
            if (cardRedOptimSub) cardRedOptimSub.textContent = `Optim: ${(data.total_red_optim || 0).toLocaleString()} Grids`;
            const cardRedOptimWow = document.getElementById('cardRedOptimWow');
            if (cardRedOptimWow) {
                const d = data.diff_prev_pp;
                if (d !== null && d !== undefined) {
                    const isImp = d <= 0; // lower red optim is better
                    const sign = d > 0 ? `+${d.toFixed(2)}` : `${d.toFixed(2)}`;
                    const color = isImp ? '#059669' : '#dc2626';
                    cardRedOptimWow.innerHTML = `<span style="color:${color};"><i class="fas fa-${d <= 0 ? 'arrow-down' : 'arrow-up'}"></i> ${sign} pp WoW</span>`;
                } else {
                    cardRedOptimWow.innerHTML = `<span style="color:var(--text-muted);">- pp WoW</span>`;
                }
            }

            // Card 3: Target Status (Shows current value, status, target, and solve gap)
            const targetCurrentVal = document.getElementById('targetCurrentVal');
            const targetBadge = document.getElementById('targetStatusBadge');
            const targetDesc = document.getElementById('targetStatusDesc');
            const targetSolveGrids = document.getElementById('targetSolveGrids');

            const currentOptimPct = Number(data.red_optim_pct || 0);
            const targetThreshold = Number(data.target || 0.23);

            if (targetCurrentVal) {
                targetCurrentVal.textContent = `${currentOptimPct.toFixed(2)}%`;
                targetCurrentVal.style.color = data.is_pass ? '#10b981' : '#ef4444';
            }

            if (targetBadge && targetDesc) {
                if (data.is_pass) {
                    targetBadge.className = 'badge-pass';
                    targetBadge.innerHTML = '<i class="fas fa-check-circle"></i> PASS';
                    const bufferPp = (targetThreshold - currentOptimPct).toFixed(2);
                    targetDesc.textContent = `Target: ≤ ${targetThreshold.toFixed(2)}% (Margin: ${bufferPp} pp)`;
                    if (targetSolveGrids) {
                        targetSolveGrids.innerHTML = `<span style="color:#10b981;"><i class="fas fa-shield-alt"></i> On Track (0 Grids to solve)</span>`;
                    }
                } else {
                    targetBadge.className = 'badge-fail';
                    targetBadge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> BREACH';
                    const excessPp = (currentOptimPct - targetThreshold).toFixed(2);
                    targetDesc.textContent = `Target: ≤ ${targetThreshold.toFixed(2)}% (+${excessPp} pp over)`;
                    if (targetSolveGrids) {
                        // Calculate excess grids if backend didn't compute, or use backend's exact figure
                        const totalGrids = Number(data.total_grids || 0);
                        const currentOptimGrids = Number(data.total_red_optim || 0);
                        const maxAllowed = Math.floor((targetThreshold * totalGrids) / 100.0);
                        const gridsToSolve = data.excess_optim_grids !== undefined ? data.excess_optim_grids : Math.max(0, currentOptimGrids - maxAllowed);
                        targetSolveGrids.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-tools"></i> Need to solve <strong>${gridsToSolve.toLocaleString()} grids</strong> to pass</span>`;
                    }
                }
            }

            // Card 4: Grid Stats Overview
            const elTotGrids = document.getElementById('statTotalGrids');
            if (elTotGrids) elTotGrids.textContent = (data.total_grids || 0).toLocaleString();
            const elGoodCov = document.getElementById('statGoodCov');
            if (elGoodCov) elGoodCov.textContent = `${(data.total_good_cov || 0).toLocaleString()} (${data.good_cov_pct}%)`;
            const elRedOptim = document.getElementById('statRedOptim');
            if (elRedOptim) elRedOptim.textContent = (data.total_red_optim || 0).toLocaleString();
            const elRedEng = document.getElementById('statRedEng');
            if (elRedEng) elRedEng.textContent = (data.total_red_eng || 0).toLocaleString();

            // Tab 2 Quality Stat Cards with Dynamic WoW
            updateQualityCards(data);

            // Render Benchmark Slider Track & Branch Chips Row like RHI
            renderBranchDistribution(data.regional_distribution, data.red_optim_pct, data.target, data.target_label);

            // Render Tab 2 Charts
            renderTab2Charts();

            // Executive Bullets
            const listEl = document.getElementById('execBulletsList');
            if (listEl && data.bullets && data.bullets.length) {
                listEl.innerHTML = data.bullets.map(b => {
                    // Highlight key numbers, region names, and action terms gracefully
                    let formatted = b
                        .replace(/\b(MALUKU DAN PAPUA|[A-Z]{3,}\s+NOP)\b/g, '<strong>$1</strong>')
                        .replace(/\b(\d+[\d,]*\s*grids)\b/gi, '<strong>$1</strong>')
                        .replace(/\b(\d+\.\d{2}%)\b/g, '<strong>$1</strong>')
                        .replace(/(degraded by [^)]+\))/gi, '<span style="color:#ef4444; font-weight:700;">$1</span>')
                        .replace(/(improved by [^)]+\))/gi, '<span style="color:#10b981; font-weight:700;">$1</span>')
                        .replace(/(Need to solve [^.]+\.)/gi, '<span style="color:#ef4444; font-weight:700;">$1</span>')
                        .replace(/(passing the target[^.]*\.)/gi, '<span style="color:#10b981; font-weight:700;">$1</span>')
                        .replace(/(breaching the target[^.]*\.)/gi, '<span style="color:#ef4444; font-weight:700;">$1</span>');
                    return `<li>${formatted}</li>`;
                }).join('');
            }

        } catch (e) {
            console.error('Error loading summary:', e);
        }
    }

    // ── Update Quality Stat Cards with Dynamic WoW in Tab 2 ──
    function updateQualityCards(data) {
        // Bad Tiles RSRP
        const elBadTiles = document.getElementById('statBadTiles');
        if (elBadTiles) elBadTiles.textContent = (data.total_bad_tiles || 0).toLocaleString();
        const elBadTilesWow = document.getElementById('statBadTilesWow');
        if (elBadTilesWow) {
            const p = data.diff_bad_tiles_pct;
            if (p !== null && p !== undefined) {
                const color = p <= 0 ? '#059669' : '#dc2626';
                const sign = p > 0 ? `+${p.toFixed(1)}%` : `${p.toFixed(1)}%`;
                elBadTilesWow.innerHTML = `<span style="color:${color};"><i class="fas fa-${p <= 0 ? 'arrow-down' : 'arrow-up'}"></i> ${sign} WoW</span>`;
            } else {
                elBadTilesWow.innerHTML = `<span style="color:var(--text-muted);">- WoW</span>`;
            }
        }

        // Grids > 3 Weeks
        const elMore3 = document.getElementById('statMore3Wks');
        if (elMore3) elMore3.textContent = (data.more_than_3_wks || 0).toLocaleString();
        const elMore3Wow = document.getElementById('statMore3WksWow');
        if (elMore3Wow) {
            const p = data.diff_more_3_wks_pct;
            if (p !== null && p !== undefined) {
                const color = p <= 0 ? '#059669' : '#dc2626';
                const sign = p > 0 ? `+${p.toFixed(1)}%` : `${p.toFixed(1)}%`;
                elMore3Wow.innerHTML = `<span style="color:${color};"><i class="fas fa-${p <= 0 ? 'arrow-down' : 'arrow-up'}"></i> ${sign} WoW</span>`;
            } else {
                elMore3Wow.innerHTML = `<span style="color:var(--text-muted);">- WoW</span>`;
            }
        }

        // Cluster Forming Grids
        const elFormCluster = document.getElementById('statFormingCluster');
        if (elFormCluster) elFormCluster.textContent = Number(data.forming_cluster || 0).toLocaleString();
        const elFormClusterWow = document.getElementById('statFormingClusterWow');
        if (elFormClusterWow) {
            const p = data.diff_forming_cluster_pct;
            if (p !== null && p !== undefined) {
                const color = p <= 0 ? '#059669' : '#dc2626';
                const sign = p > 0 ? `+${p.toFixed(1)}%` : `${p.toFixed(1)}%`;
                elFormClusterWow.innerHTML = `<span style="color:${color};"><i class="fas fa-${p <= 0 ? 'arrow-down' : 'arrow-up'}"></i> ${sign} WoW</span>`;
            } else {
                elFormClusterWow.innerHTML = `<span style="color:var(--text-muted);">- WoW</span>`;
            }
        }

        // Bad Non-Potential
        const elBadNonPot = document.getElementById('statBadNonPot');
        if (elBadNonPot) elBadNonPot.textContent = (data.total_bad_non_pot || 0).toLocaleString();
        const elBadNonPotWow = document.getElementById('statBadNonPotWow');
        if (elBadNonPotWow) {
            const p = data.diff_bad_non_pot_pct;
            if (p !== null && p !== undefined) {
                const color = p <= 0 ? '#059669' : '#dc2626';
                const sign = p > 0 ? `+${p.toFixed(1)}%` : `${p.toFixed(1)}%`;
                elBadNonPotWow.innerHTML = `<span style="color:${color};"><i class="fas fa-${p <= 0 ? 'arrow-down' : 'arrow-up'}"></i> ${sign} WoW</span>`;
            } else {
                elBadNonPotWow.innerHTML = `<span style="color:var(--text-muted);">- WoW</span>`;
            }
        }
    }

    // ── Branch Performance Distribution vs Target (Anti-Collision Fix + Black Dashed Target Line + Chips Row like RHI) ──
    function renderBranchDistribution(branchesData, regionalPct, target, targetLabel) {
        const wrap = document.getElementById('branchDistribWrap');
        if (!wrap) return;

        const qBadge = document.getElementById('distribQuarterBadge');
        if (qBadge) {
            qBadge.textContent = `${targetLabel || 'Target'}: ${Number(target).toFixed(2)}%`;
        }

        const branchList = (branchesData && branchesData.length) ? branchesData.slice() : [
            { name: 'AMBON', red_optim_pct: 0.14, is_above: true, red_cov: 1135, total_grid: 264142 },
            { name: 'TIMIKA', red_optim_pct: 0.14, is_above: true, red_cov: 570, total_grid: 243820 },
            { name: 'JAYAPURA', red_optim_pct: 0.26, is_above: false, red_cov: 935, total_grid: 192188 },
            { name: 'SORONG', red_optim_pct: 0.00, is_above: true, red_cov: 3, total_grid: 189889 }
        ];

        branchList.sort((a, b) => a.red_optim_pct - b.red_optim_pct);

        const allVals = [target, regionalPct || 0.14].concat(branchList.map(b => b.red_optim_pct));
        let minScale = Math.max(0, Math.floor(Math.min(...allVals) * 10) / 10 - 0.05);
        let maxScale = Math.ceil(Math.max(...allVals) * 10) / 10 + 0.05;
        if (maxScale - minScale < 0.2) {
            minScale = Math.max(0, minScale - 0.1);
            maxScale += 0.1;
        }
        const scaleRange = maxScale - minScale;

        function getLeftPct(val) {
            const clamped = Math.max(minScale, Math.min(maxScale, val));
            return ((clamped - minScale) / scaleRange) * 100;
        }

        const targetLeft = getLeftPct(target);
        const regionalLeft = getLeftPct(regionalPct || 0.14);

        // Render each branch marker individually - exactly like 2nd picture / RHI
        let branchPointsHtml = '';
        let lastLeft = -999;
        let lastTop = 20;

        // Sort by red_optim_pct ascending so adjacent positioning is consistent
        const sortedBranches = branchList.slice().sort((a, b) => a.red_optim_pct - b.red_optim_pct);

        sortedBranches.forEach((b, idx) => {
            const bLeft = getLeftPct(b.red_optim_pct);
            const isMet = b.red_optim_pct <= target; // Lower is better
            const valColor = isMet ? '#16a34a' : '#dc2626';
            const dotColor = isMet ? '#10b981' : '#ef4444';

            // Anti-collision: alternate top position if adjacent markers are within 11.5%
            let topOffset = 22;
            let nudgeX = 0;
            if (Math.abs(bLeft - lastLeft) < 11.5) {
                topOffset = (lastTop === 22) ? 6 : 22;
                // If extremely close (identical like Ambon 0.47% and Jayapura 0.47%), nudge horizontally slightly
                if (Math.abs(bLeft - lastLeft) < 1.0) {
                    nudgeX = (lastTop === 22) ? -2.8 : 2.8;
                }
            }
            lastLeft = bLeft;
            lastTop = topOffset;

            // Clamping left to avoid overflow on extreme edges
            const displayLeft = Math.max(3.5, Math.min(96.5, bLeft + nudgeX));
            const dotMarginTop = (topOffset === 6) ? '20px' : '4px';

            branchPointsHtml += `
                <div class="redcov-distrib-branch-top" style="left: ${displayLeft}%; top: ${topOffset}px;" title="${b.name}: ${Number(b.red_optim_pct).toFixed(2)}% (Optim: ${(b.red_optim || 0).toLocaleString()} | Eng: ${(b.red_eng || 0).toLocaleString()})">
                    <div class="redcov-branch-text">
                        <span class="redcov-branch-name">${b.name}</span>
                        <span class="redcov-branch-val" style="color: ${valColor};">${Number(b.red_optim_pct).toFixed(2)}%</span>
                    </div>
                    <div class="redcov-branch-dot" style="background: ${dotColor}; margin-top: ${dotMarginTop};"></div>
                </div>
            `;
        });

        // Axis Ticks
        let ticksHtml = '';
        const step = 0.05;
        for (let tickVal = minScale; tickVal <= maxScale + 0.001; tickVal += step) {
            const tickLeft = getLeftPct(tickVal);
            ticksHtml += `
                <div class="redcov-distrib-tick" style="left: ${tickLeft}%;">
                    <div class="redcov-distrib-tick-line"></div>
                    <span>${tickVal.toFixed(2)}</span>
                </div>
            `;
        }

        // Regional Marker at BOTTOM
        const isRegionalPass = (regionalPct || 0.14) <= target;
        const regionalColor = isRegionalPass ? '#16a34a' : '#dc2626';

        wrap.innerHTML = `
            <!-- Dual-colored track (soft green on left of target = pass, soft red on right = breach) -->
            <div class="redcov-distrib-track">
                <div class="redcov-distrib-track-pass" style="width: ${targetLeft}%;"></div>
                <div class="redcov-distrib-track-fail"></div>
            </div>

            <!-- Target Label on TOP (text color dark navy) & dashed line extending directly beneath it down across track -->
            <div class="redcov-distrib-target-label" style="left: ${targetLeft}%;">Target ${Number(target).toFixed(2)}%</div>
            <div class="redcov-distrib-target-line" style="left: ${targetLeft}%;"></div>

            <!-- All Branch Markers on TOP with dots sitting directly on the track -->
            ${branchPointsHtml}

            <!-- Axis Ticks below track -->
            <div class="redcov-distrib-ticks">
                ${ticksHtml}
            </div>

            <!-- Regional Marker on BOTTOM -->
            <div class="redcov-distrib-puma-bottom" style="left: ${regionalLeft}%;" title="Regional: ${regionalPct}%">
                <div style="width:0; height:0; border-left:4px solid transparent; border-right:4px solid transparent; border-bottom:5px solid ${regionalColor}; margin-bottom:2px;"></div>
                <div class="redcov-puma-pill" style="color:${regionalColor}; border-color:${regionalColor};">
                    REGIONAL ${regionalPct}%
                </div>
            </div>
        `;

        // Render 4 Branch Stat Chips below track like RHI!
        const statRow = document.getElementById('branchStatRow');
        if (statRow && branchList.length) {
            statRow.innerHTML = branchList.map(b => {
                const isMet = b.red_optim_pct <= target;
                const badgeClass = isMet ? 'badge-pass' : 'badge-fail';
                const badgeText = isMet ? 'PASS' : 'BREACH';
                const valColor = isMet ? '#16a34a' : '#dc2626';
                return `
                    <div class="redcov-branch-chip">
                        <div class="redcov-chip-top">
                            <span class="redcov-chip-name">${b.name}</span>
                            <span class="${badgeClass}" style="font-size:10px; padding:1px 5px;">${badgeText}</span>
                        </div>
                        <div class="redcov-chip-val" style="color:${valColor};">${Number(b.red_optim_pct).toFixed(2)}%</div>
                        <div class="redcov-chip-meta">Red: ${(b.red_cov || 0).toLocaleString()} | Total: ${(b.total_grid || 0).toLocaleString()}</div>
                        <div class="redcov-chip-counts">
                            <span style="color:#ea580c;">Optim: ${(b.red_optim || 0).toLocaleString()}</span> • <span style="color:var(--text-muted);">Eng: ${(b.red_eng || 0).toLocaleString()}</span>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    // ── Load Trend Data ──
    async function loadTrend() {
        const region = document.getElementById('filterRegion').value;
        const startWeek = document.getElementById('filterStartWeek').value;
        const endWeek = document.getElementById('filterWeek').value;
        const branchParam = activeBranch !== 'ALL' ? `&branch=${encodeURIComponent(activeBranch)}` : '';

        try {
            const res = await fetch(`/api/sow/redcov/trend?region=${encodeURIComponent(region)}&start_week=${startWeek}&end_week=${endWeek}${branchParam}`);
            const data = await res.json();
            if (data.status !== 'success') {
                console.error('Trend fetch error:', data.message);
                return;
            }

            currentTrendData = data;
            // Render Tab 1 Swapped Charts with Light Green Good Cov & Dark Red Segments + Value Labels
            renderCoverageTrendChart(data);
            renderRedBreakdownChart(data);

            // Render Tab 2 Charts
            renderTab2Charts(data);

        } catch (e) {
            console.error('Error loading trend:', e);
        }
    }

    // ── Tab 1 Top Chart: Trend Coverage PUMA (Light Green Good Cov, Dark Red Red Cov, Dark Red Line with Value Labels) ──
    function renderCoverageTrendChart(data) {
        const dom = document.getElementById('chartCoverageTrend');
        if (!dom) return;
        if (!chartCoverageTrend) chartCoverageTrend = echarts.init(dom);

        const th = getEChartsTheme();
        const isShareMode = coverageMetricMode === 'share';
        const goodData = isShareMode
            ? data.coverage_trend.total_grid.map((tg, i) => tg > 0 ? Number(((tg - data.coverage_trend.red_cov[i]) * 100 / tg).toFixed(2)) : 0)
            : data.coverage_trend.good_cov;
        const redData = isShareMode
            ? data.coverage_trend.total_grid.map((tg, i) => tg > 0 ? Number((data.coverage_trend.red_cov[i] * 100 / tg).toFixed(2)) : 0)
            : data.coverage_trend.red_cov;

        const option = {
            tooltip: {
                ...getTooltipStyle(th),
                trigger: 'axis',
                axisPointer: { type: 'cross', lineStyle: { color: th.textMuted, type: 'dashed' } },
                formatter: function (params) {
                    let s = `<div style="font-weight:700; margin-bottom:4px; font-size:12px;">${params[0].name}</div>`;
                    params.forEach(p => {
                        const valStr = typeof p.value === 'number'
                            ? (p.seriesName.includes('%') ? `${p.value.toFixed(2)}%` : p.value.toLocaleString())
                            : p.value;
                        s += `<div style="display:flex; justify-content:space-between; gap:16px; margin-top:3px;">
                            <span>${p.marker} ${p.seriesName}</span>
                            <span style="font-weight:700;">${valStr}</span>
                        </div>`;
                    });
                    return s;
                }
            },
            legend: {
                data: ['#Good Cov', '#Red Cov', '%_Red_Cov'],
                bottom: 0,
                itemWidth: 12,
                itemHeight: 7,
                itemGap: 16,
                icon: 'roundRect',
                textStyle: { fontSize: 11.5, fontWeight: 600, color: th.legendColor }
            },
            grid: { top: 35, right: 50, bottom: 42, left: 60 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { fontSize: 11, color: th.textMuted },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: [
                {
                    type: 'value',
                    name: isShareMode ? '% Share' : '#Grid',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: function (val) {
                            if (isShareMode) return `${val}%`;
                            return val >= 1000 ? `${Math.round(val / 1000)}k` : val;
                        },
                        fontSize: 11,
                        color: th.textMuted
                    },
                    splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
                },
                {
                    type: 'value',
                    name: '% Red Cov',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: '{value}%',
                        fontSize: 11,
                        color: th.textMuted
                    },
                    splitLine: { show: false }
                }
            ],
            series: [
                {
                    name: '#Good Cov',
                    type: 'bar',
                    stack: 'cov',
                    itemStyle: { color: THEME_COLORS.goodCov },
                    data: goodData
                },
                {
                    name: '#Red Cov',
                    type: 'bar',
                    stack: 'cov',
                    itemStyle: { color: THEME_COLORS.redCov, borderRadius: [2, 2, 0, 0] },
                    data: redData
                },
                {
                    name: '%_Red_Cov',
                    type: 'line',
                    yAxisIndex: 1,
                    smooth: 0.2,
                    itemStyle: { color: th.lineRedCov },
                    lineStyle: { width: 2.8, color: th.lineRedCov },
                    symbol: 'circle',
                    symbolSize: 6,
                    data: (data.coverage_trend.red_cov_pct || []).map(val => {
                        const v = Number(val);
                        return {
                            value: val,
                            label: {
                                show: true,
                                position: 'top',
                                distance: 6,
                                fontSize: 10,
                                fontWeight: 'bold',
                                color: th.lineRedCov,
                                backgroundColor: th.labelBg,
                                borderColor: th.labelBorder,
                                borderWidth: 1,
                                borderRadius: 4,
                                padding: [2, 4],
                                formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                            }
                        };
                    })
                }
            ]
        };

        chartCoverageTrend.setOption(option, true);
    }

    // ── Tab 1 Bottom Chart: Red Coverage Breakdown & Dynamic Target (Dark Red Bars + Value Labels like 2nd picture) ──
    function renderRedBreakdownChart(data) {
        const dom = document.getElementById('chartRedBreakdown');
        if (!dom) return;
        if (!chartRedBreakdown) chartRedBreakdown = echarts.init(dom);

        const th = getEChartsTheme();
        const targetSeries = data.breakdown_trend.target || [];

        const option = {
            tooltip: {
                ...getTooltipStyle(th),
                trigger: 'axis',
                axisPointer: { type: 'cross', lineStyle: { color: th.textMuted, type: 'dashed' } },
                formatter: function (params) {
                    let s = `<div style="font-weight:700; margin-bottom:4px; font-size:12px;">${params[0].name}</div>`;
                    params.forEach(p => {
                        const isPct = p.seriesName.includes('%') || p.seriesName.includes('Target');
                        const valStr = typeof p.value === 'number'
                            ? (isPct ? `${p.value.toFixed(2)}%` : p.value.toLocaleString())
                            : p.value;
                        s += `<div style="display:flex; justify-content:space-between; gap:16px; margin-top:3px;">
                            <span>${p.marker} ${p.seriesName}</span>
                            <span style="font-weight:700;">${valStr}</span>
                        </div>`;
                    });
                    return s;
                }
            },
            legend: {
                data: ['#Red Optim', '#Red Engineering', '%_Red_Optim', 'Target (Red Optim)'],
                bottom: 0,
                itemWidth: 12,
                itemHeight: 7,
                itemGap: 16,
                icon: 'roundRect',
                textStyle: { fontSize: 11.5, fontWeight: 600, color: th.legendColor }
            },
            grid: { top: 35, right: 50, bottom: 42, left: 60 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { fontSize: 11, color: th.textMuted },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: [
                {
                    type: 'value',
                    name: '#Grid',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: function (val) {
                            return val >= 1000 ? `${Math.round(val / 1000)}k` : val;
                        },
                        fontSize: 11,
                        color: th.textMuted
                    },
                    splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
                },
                {
                    type: 'value',
                    name: '% Optim',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: '{value}%',
                        fontSize: 11,
                        color: th.textMuted
                    },
                    splitLine: { show: false }
                }
            ],
            series: [
                {
                    name: '#Red Optim',
                    type: 'bar',
                    stack: 'redSplit',
                    itemStyle: { color: THEME_COLORS.redOptim }, // Dark Red (#8B0000)
                    data: data.breakdown_trend.red_optim
                },
                {
                    name: '#Red Engineering',
                    type: 'bar',
                    stack: 'redSplit',
                    itemStyle: { color: THEME_COLORS.redEng, borderRadius: [2, 2, 0, 0] }, // Deep Wine (#4c0519)
                    data: data.breakdown_trend.red_eng
                },
                {
                    name: '%_Red_Optim',
                    type: 'line',
                    yAxisIndex: 1,
                    smooth: 0.2,
                    itemStyle: { color: THEME_COLORS.redOptimLine },
                    lineStyle: { width: 2.8, color: THEME_COLORS.redOptimLine },
                    symbol: 'circle',
                    symbolSize: 6,
                    // Map objects per point with clear explicit styling so labels are 100% visible and match CEI/RHI!
                    data: (data.breakdown_trend.red_optim_pct || []).map((val, idx) => {
                        const v = Number(val);
                        const tgt = (targetSeries && targetSeries[idx] !== undefined) ? Number(targetSeries[idx]) : 0.23;
                        const meets = !isNaN(v) && v < tgt;
                        const labelColor = meets ? '#10b981' : '#ef4444';
                        return {
                            value: val,
                            label: {
                                show: true,
                                position: 'top',
                                distance: 6,
                                fontSize: 10,
                                fontWeight: 'bold',
                                color: labelColor,
                                backgroundColor: th.labelBg,
                                borderColor: meets ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
                                borderWidth: 1,
                                borderRadius: 4,
                                padding: [2, 4],
                                formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                            }
                        };
                    })
                },
                {
                    name: 'Target (Red Optim)',
                    type: 'line',
                    yAxisIndex: 1,
                    step: 'end',
                    itemStyle: { color: th.targetLineColor },
                    lineStyle: { width: 2.2, type: 'dashed', color: th.targetLineColor },
                    symbol: 'circle',
                    symbolSize: 3,
                    data: targetSeries
                }
            ]
        };

        chartRedBreakdown.setOption(option, true);
    }

    // ── Render Tab 2 Charts (Using Dedicated Tab 2 Filters) ──
    function renderTab2Charts(trendDataOverride, nopFilterOverride) {
        const trendData = trendDataOverride || currentTrendData;
        if (!currentSummaryData || !trendData) return;

        const metricType = document.getElementById('trendMetricType') ? document.getElementById('trendMetricType').value : 'optim';
        const nopFilter = nopFilterOverride || (document.getElementById('trendNopSelect') ? document.getElementById('trendNopSelect').value : 'ALL');
        const topLimitVal = document.getElementById('trendTopLimit') ? document.getElementById('trendTopLimit').value : '10';

        // 1. Update Chart Titles
        const metricLabels = {
            all_red: 'All Red Coverage',
            optim: 'Red Coverage Optimization',
            eng: 'Red Coverage Engineering'
        };
        const currentMetricLabel = metricLabels[metricType] || 'Red Coverage';

        const lblNopTrend = document.getElementById('lblNopTrendTitle');
        if (lblNopTrend) lblNopTrend.textContent = `${currentMetricLabel} Trend - NOP`;
        const lblTopContrib = document.getElementById('lblTopContribTitle');
        if (lblTopContrib) lblTopContrib.textContent = `Top Contributor ${currentMetricLabel} (Kabupaten)`;
        const lblNopWeekly = document.getElementById('lblNopWeeklyTitle');
        if (lblNopWeekly) lblNopWeekly.textContent = `NOP Weekly ${currentMetricLabel} Volume`;

        // 2. Chart 3: NOP Multi-Line Trend for Selected Metric
        renderTab2NopTrend(trendData, metricType);

        // 3. Chart 4: Top Contributor Kabupaten (175px left margin so SERAM BAGIAN BARAT is never cut off!)
        renderTab2TopContributors(currentSummaryData.all_contributors || currentSummaryData.top_contributors, metricType, nopFilter, topLimitVal);

        // 4. Chart 5: NOP Weekly Stacked Bar for Selected Metric
        renderTab2NopWeeklyBar(trendData, metricType);

        // 5. Chart 6: Grid Quality Indicators Trend (DUAL AXIS so trends are crystal clear!)
        renderQualityTrendChart(trendData);

        // 6. Populate Kabupaten Dropdown and Render Kabupaten Trend Coverage Chart
        populateKabupatenDropdown();
        loadKabupatenTrendChart();
    }

    // ── Tab 2 Chart 7: Trend Coverage Kabupaten Level ──
    function populateKabupatenDropdown() {
        const sel = document.getElementById('trendKabSelect');
        if (!sel || sel.options.length > 1) return;

        const kabs = (currentSummaryData && currentSummaryData.all_contributors)
            ? currentSummaryData.all_contributors.map(c => c.kabupaten).sort()
            : [];

        if (!kabs.length) return;

        sel.innerHTML = kabs.map(k => `<option value="${k}">${k}</option>`).join('');
    }

    window.loadKabupatenTrendCharts = async function () {
        const sel = document.getElementById('trendKabSelect');
        const kab = sel ? sel.value : '';
        if (!kab) return;

        const region = document.getElementById('filterRegion').value;
        const startWeek = document.getElementById('filterStartWeek').value;
        const endWeek = document.getElementById('filterWeek').value;

        try {
            const res = await fetch(`/api/sow/redcov/trend?region=${encodeURIComponent(region)}&start_week=${startWeek}&end_week=${endWeek}&kabupaten=${encodeURIComponent(kab)}`);
            const data = await res.json();
            if (data.status !== 'success') return;

            renderKabupatenTrendChart(data, kab);
            renderKabupatenBreakdownChart(data, kab);
        } catch (e) {
            console.error('Error loading Kabupaten trend:', e);
        }
    };

    window.loadKabupatenTrendChart = window.loadKabupatenTrendCharts;

    function renderKabupatenTrendChart(data, kabName) {
        const dom = document.getElementById('chartKabTrend');
        if (!dom) return;
        if (!chartKabTrend) chartKabTrend = echarts.init(dom);

        const th = getEChartsTheme();

        const option = {
            tooltip: {
                ...getTooltipStyle(th),
                trigger: 'axis',
                axisPointer: { type: 'cross', lineStyle: { color: th.textMuted, type: 'dashed' } }
            },
            legend: {
                data: ['#Good Cov', '#Red Cov', '%_Red_Cov'],
                bottom: 0,
                itemWidth: 12,
                itemHeight: 7,
                itemGap: 16,
                icon: 'roundRect',
                textStyle: { fontSize: 11.5, fontWeight: 600, color: th.legendColor }
            },
            grid: { top: 35, right: 55, bottom: 42, left: 65 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { fontSize: 11, color: th.textMuted },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: [
                {
                    type: 'value',
                    name: '#Grid',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: (v) => v >= 1000 ? `${Math.round(v/1000)}k` : v,
                        fontSize: 10.5,
                        color: th.textMuted
                    },
                    splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
                },
                {
                    type: 'value',
                    name: '% Red Cov',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: { formatter: '{value}%', fontSize: 10.5, color: th.textMuted },
                    splitLine: { show: false }
                }
            ],
            series: [
                {
                    name: '#Good Cov',
                    type: 'bar',
                    stack: 'kabCov',
                    itemStyle: { color: THEME_COLORS.goodCov },
                    data: data.coverage_trend.good_cov
                },
                {
                    name: '#Red Cov',
                    type: 'bar',
                    stack: 'kabCov',
                    itemStyle: { color: THEME_COLORS.redCov, borderRadius: [2, 2, 0, 0] },
                    data: data.coverage_trend.red_cov
                },
                {
                    name: '%_Red_Cov',
                    type: 'line',
                    yAxisIndex: 1,
                    smooth: 0.2,
                    itemStyle: { color: th.lineRedCov },
                    lineStyle: { width: 2.5, color: th.lineRedCov },
                    symbol: 'circle',
                    symbolSize: 6,
                    data: (data.coverage_trend.red_cov_pct || []).map(val => {
                        const v = Number(val);
                        return {
                            value: val,
                            label: {
                                show: true,
                                position: 'top',
                                distance: 6,
                                fontSize: 10,
                                fontWeight: 'bold',
                                color: th.lineRedCov,
                                backgroundColor: th.labelBg,
                                borderColor: th.labelBorder,
                                borderWidth: 1,
                                borderRadius: 4,
                                padding: [2, 4],
                                formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                            }
                        };
                    })
                }
            ]
        };

        chartKabTrend.setOption(option, true);
    }

    function renderKabupatenBreakdownChart(data, kabName) {
        const dom = document.getElementById('chartKabBreakdown');
        if (!dom) return;
        if (!chartKabBreakdown) chartKabBreakdown = echarts.init(dom);

        const th = getEChartsTheme();

        const option = {
            tooltip: {
                ...getTooltipStyle(th),
                trigger: 'axis',
                axisPointer: { type: 'cross', lineStyle: { color: th.textMuted, type: 'dashed' } }
            },
            legend: {
                data: ['#Red Optim', '#Red Engineering', '%_Red_Optim'],
                bottom: 0,
                itemWidth: 12,
                itemHeight: 7,
                itemGap: 16,
                icon: 'roundRect',
                textStyle: { fontSize: 11.5, fontWeight: 600, color: th.legendColor }
            },
            grid: { top: 35, right: 55, bottom: 42, left: 65 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { fontSize: 11, color: th.textMuted },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: [
                {
                    type: 'value',
                    name: '#Grid',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: (v) => v >= 1000 ? `${Math.round(v/1000)}k` : v,
                        fontSize: 10.5,
                        color: th.textMuted
                    },
                    splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
                },
                {
                    type: 'value',
                    name: '% Optim',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: { formatter: '{value}%', fontSize: 10.5, color: th.textMuted },
                    splitLine: { show: false }
                }
            ],
            series: [
                {
                    name: '#Red Optim',
                    type: 'bar',
                    stack: 'kabRedSplit',
                    itemStyle: { color: THEME_COLORS.redOptim },
                    data: data.breakdown_trend.red_optim
                },
                {
                    name: '#Red Engineering',
                    type: 'bar',
                    stack: 'kabRedSplit',
                    itemStyle: { color: THEME_COLORS.redEng, borderRadius: [2, 2, 0, 0] },
                    data: data.breakdown_trend.red_eng
                },
                {
                    name: '%_Red_Optim',
                    type: 'line',
                    yAxisIndex: 1,
                    smooth: 0.2,
                    itemStyle: { color: THEME_COLORS.redOptimLine },
                    lineStyle: { width: 2.5, color: THEME_COLORS.redOptimLine },
                    symbol: 'circle',
                    symbolSize: 6,
                    data: (data.breakdown_trend.red_optim_pct || []).map(val => {
                        const v = Number(val);
                        return {
                            value: val,
                            label: {
                                show: true,
                                position: 'top',
                                distance: 6,
                                fontSize: 10,
                                fontWeight: 'bold',
                                color: THEME_COLORS.redOptimLine,
                                backgroundColor: th.labelBg,
                                borderColor: th.labelBorder,
                                borderWidth: 1,
                                borderRadius: 4,
                                padding: [2, 4],
                                formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                            }
                        };
                    })
                }
            ]
        };

        chartKabBreakdown.setOption(option, true);
    }

    // ── Tab 2 Chart 3: NOP Multi-Line Trend ──
    function renderTab2NopTrend(data, metricType) {
        const dom = document.getElementById('chartNopTrend');
        if (!dom) return;
        if (!chartNopTrend) chartNopTrend = echarts.init(dom);

        const th = getEChartsTheme();
        const nops = ['AMBON', 'JAYAPURA', 'TIMIKA', 'SORONG'];
        const nopColors = {
            AMBON: THEME_COLORS.nopAmbon,
            JAYAPURA: THEME_COLORS.nopJayapura,
            TIMIKA: THEME_COLORS.nopTimika,
            SORONG: THEME_COLORS.nopSorong
        };

        const sourceSeries = metricType === 'all_red'
            ? data.nop_trend_red
            : (metricType === 'eng' ? (data.nop_trend_eng || data.nop_trend_red) : data.nop_trend_optim);

        const seriesList = nops.map(n => ({
            name: n,
            type: 'line',
            smooth: 0.25,
            symbol: 'circle',
            symbolSize: 5,
            lineStyle: { width: 2.2 },
            itemStyle: { color: nopColors[n] },
            data: (sourceSeries && sourceSeries[n]) ? sourceSeries[n] : []
        }));

        const option = {
            tooltip: {
                ...getTooltipStyle(th),
                trigger: 'axis',
                formatter: function (params) {
                    let s = `<div style="font-weight:700; margin-bottom:4px; font-size:12px;">${params[0].name} (Grids)</div>`;
                    params.forEach(p => {
                        s += `<div style="display:flex; justify-content:space-between; gap:16px; margin-top:2px;">
                            <span>${p.marker} ${p.seriesName}</span>
                            <span style="font-weight:700;">${p.value.toLocaleString()}</span>
                        </div>`;
                    });
                    return s;
                }
            },
            legend: {
                data: nops,
                bottom: 0,
                itemWidth: 12,
                itemHeight: 7,
                itemGap: 16,
                icon: 'roundRect',
                textStyle: { fontSize: 11.5, fontWeight: 600, color: th.legendColor }
            },
            grid: { top: 28, right: 28, bottom: 42, left: 55 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { fontSize: 11, color: th.textMuted },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { fontSize: 11, color: th.textMuted },
                splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
            },
            series: seriesList
        };

        chartNopTrend.setOption(option, true);
    }

    // ── Tab 2 Chart 4: Top Contributor Kabupaten (Left: 175px Margin Fix for SERAM BAGIAN BARAT) ──
    function renderTab2TopContributors(allContributors, metricType, nopFilter, topLimitVal) {
        const dom = document.getElementById('chartTopContributors');
        if (!dom) return;
        if (!chartTopContributors) chartTopContributors = echarts.init(dom);

        const th = getEChartsTheme();
        let list = (allContributors && allContributors.length) ? allContributors.slice() : [];

        // Filter by Tab 2 NOP filter
        if (nopFilter && nopFilter !== 'ALL') {
            list = list.filter(c => c.branch === nopFilter);
        }

        // Sort by the selected metric descending
        const sortProp = metricType === 'all_red' ? 'red_cov' : (metricType === 'eng' ? 'red_eng' : 'red_optim');
        const pctProp = metricType === 'all_red' ? 'red_cov_pct' : (metricType === 'eng' ? 'red_eng_pct' : 'red_optim_pct');

        list.sort((a, b) => (b[sortProp] || 0) - (a[sortProp] || 0));

        // Limit count
        const limit = topLimitVal === 'ALL' ? list.length : parseInt(topLimitVal, 10);
        const topSlice = list.slice(0, limit).reverse(); // reverse for horizontal bar

        const names = topSlice.map(c => c.kabupaten);
        const values = topSlice.map(c => c[sortProp] || 0);

        const option = {
            tooltip: {
                ...getTooltipStyle(th),
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                formatter: function (params) {
                    const item = params[0];
                    const raw = topSlice[item.dataIndex];
                    return `<div style="font-weight:700; margin-bottom:3px; font-size:12px;">${item.name} (${raw.branch})</div>
                        <div style="margin-top:2px;">${sortProp.replace('_', ' ').toUpperCase()}: <strong style="color:#f97316;">${item.value.toLocaleString()}</strong> grids (${raw[pctProp]}%)</div>
                        <div style="margin-top:2px; font-size:10.5px; opacity:0.8;">Total Red Cov: ${raw.red_cov.toLocaleString()} | Total Grids: ${raw.total_grid.toLocaleString()}</div>`;
                }
            },
            // Left margin widened to 175px so long names like SERAM BAGIAN BARAT are fully readable!
            grid: { top: 15, right: 65, bottom: 20, left: 175 },
            xAxis: {
                type: 'value',
                axisLabel: { fontSize: 10.5, color: th.textMuted },
                splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
            },
            yAxis: {
                type: 'category',
                data: names,
                axisLabel: { fontSize: 11, fontWeight: '700', color: th.textColor },
                axisTick: { show: false },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            series: [
                {
                    name: 'Grids',
                    type: 'bar',
                    barWidth: 14,
                    itemStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                            { offset: 0, color: th.isDark ? '#334155' : '#64748b' },
                            { offset: 1, color: '#dc2626' }
                        ]),
                        borderRadius: [0, 4, 4, 0]
                    },
                    label: {
                        show: true,
                        position: 'right',
                        fontSize: 10.5,
                        fontWeight: 'bold',
                        color: th.textColor,
                        formatter: function (p) {
                            const raw = topSlice[p.dataIndex];
                            return `${p.value.toLocaleString()} (${raw[pctProp]}%)`;
                        }
                    },
                    data: values
                }
            ]
        };

        chartTopContributors.setOption(option, true);
    }

    // ── Tab 2 Chart 5: NOP Weekly Stacked Bar ──
    function renderTab2NopWeeklyBar(data, metricType) {
        const dom = document.getElementById('chartNopWeeklyBar');
        if (!dom) return;
        if (!chartNopWeeklyBar) chartNopWeeklyBar = echarts.init(dom);

        const th = getEChartsTheme();
        const nops = ['AMBON', 'JAYAPURA', 'TIMIKA', 'SORONG'];
        const nopColors = [THEME_COLORS.nopAmbon, THEME_COLORS.nopJayapura, THEME_COLORS.nopTimika, THEME_COLORS.nopSorong];

        const sourceSeries = metricType === 'all_red'
            ? data.nop_trend_red
            : (metricType === 'eng' ? (data.nop_trend_eng || data.nop_trend_red) : data.nop_trend_optim);

        const seriesList = nops.map((n, i) => ({
            name: n,
            type: 'bar',
            stack: 'nopStack',
            itemStyle: { color: nopColors[i] },
            data: (sourceSeries && sourceSeries[n]) ? sourceSeries[n] : []
        }));

        const option = {
            tooltip: { ...getTooltipStyle(th), trigger: 'axis', axisPointer: { type: 'shadow' } },
            legend: {
                data: nops,
                bottom: 0,
                itemWidth: 12,
                itemHeight: 7,
                itemGap: 16,
                icon: 'roundRect',
                textStyle: { fontSize: 11.5, fontWeight: 600, color: th.legendColor }
            },
            grid: { top: 25, right: 28, bottom: 42, left: 55 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { fontSize: 11, color: th.textMuted },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { fontSize: 11, color: th.textMuted },
                splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
            },
            series: seriesList
        };

        chartNopWeeklyBar.setOption(option, true);
    }

    // ── Tab 2 Chart 6: Grid Quality Indicators Trend (DUAL AXIS Fix!) ──
    function renderQualityTrendChart(data) {
        const dom = document.getElementById('chartQualityTrend');
        if (!dom) return;
        if (!chartQualityTrend) chartQualityTrend = echarts.init(dom);

        const th = getEChartsTheme();

        const option = {
            tooltip: {
                ...getTooltipStyle(th),
                trigger: 'axis',
                axisPointer: { type: 'cross', lineStyle: { color: th.textMuted, type: 'dashed' } }
            },
            legend: {
                data: ['Bad Tiles RSRP', 'Grids > 3 Wks', 'Cluster Grids'],
                bottom: 0,
                itemWidth: 12,
                itemHeight: 7,
                itemGap: 16,
                icon: 'roundRect',
                textStyle: { fontSize: 11.5, fontWeight: 600, color: th.legendColor }
            },
            // Wide margins for dual Y-axes
            grid: { top: 32, right: 55, bottom: 42, left: 60 },
            xAxis: {
                type: 'category',
                data: data.labels,
                axisLabel: { fontSize: 11, color: th.textMuted },
                axisLine: { lineStyle: { color: th.axisLineColor } }
            },
            yAxis: [
                // Axis 0 (Left): Bad Tiles RSRP (in M or k)
                {
                    type: 'value',
                    name: 'Bad Tiles',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: function (val) {
                            return val >= 1000000 ? (val / 1000000).toFixed(1) + 'M' : (val >= 1000 ? Math.round(val / 1000) + 'k' : val);
                        },
                        fontSize: 10.5,
                        color: th.textMuted
                    },
                    splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
                },
                // Axis 1 (Right): Grids count (0 to 4000 scale so lines never look stuck at zero!)
                {
                    type: 'value',
                    name: 'Grids Count',
                    nameTextStyle: { fontSize: 11, fontWeight: 600, color: th.textMuted },
                    axisLabel: {
                        formatter: function (val) {
                            return val.toLocaleString();
                        },
                        fontSize: 10.5,
                        color: th.textMuted
                    },
                    splitLine: { show: false }
                }
            ],
            series: [
                {
                    name: 'Bad Tiles RSRP',
                    type: 'line',
                    yAxisIndex: 0,
                    smooth: 0.25,
                    itemStyle: { color: '#ef4444' },
                    lineStyle: { width: 2.4, color: '#ef4444' },
                    symbol: 'circle',
                    symbolSize: 5,
                    data: data.quality_trend.bad_tiles_rsrp
                },
                {
                    name: 'Grids > 3 Wks',
                    type: 'line',
                    yAxisIndex: 1, // On Right Axis!
                    smooth: 0.25,
                    itemStyle: { color: '#f59e0b' },
                    lineStyle: { width: 2.4, color: '#f59e0b' },
                    symbol: 'circle',
                    symbolSize: 5,
                    data: data.quality_trend.more_than_3_wks
                },
                {
                    name: 'Cluster Grids',
                    type: 'line',
                    yAxisIndex: 1, // On Right Axis!
                    smooth: 0.25,
                    itemStyle: { color: '#a855f7' },
                    lineStyle: { width: 2.4, color: '#a855f7' },
                    symbol: 'circle',
                    symbolSize: 5,
                    data: data.quality_trend.forming_cluster
                }
            ]
        };

        chartQualityTrend.setOption(option, true);
    }

    // ── Tab 3: Comparison Tables (Table 1: NOP Level, Table 2: Kabupaten Level) ──
    window.loadComparisonTable = async function () {
        const region = document.getElementById('filterRegion').value;
        const currWeek = document.getElementById('compCurrWeek').value;
        const prevWeek = document.getElementById('compPrevWeek').value;

        try {
            const res = await fetch(`/api/sow/redcov/comparison?region=${encodeURIComponent(region)}&week=${currWeek}&compare_week=${prevWeek}`);
            const data = await res.json();
            if (data.status !== 'success') {
                console.error('Comparison fetch error:', data.message);
                return;
            }

            rawComparisonData = data.rows || [];
            rawNopComparisonData = data.nop_rows || [];
            rawTotalNopData = data.total_nop_row || null;

            const badge = document.getElementById('tableTargetBadge');
            if (badge) badge.textContent = `Target: ${Number(data.target || 0.23).toFixed(2)}%`;
            const nopBadge = document.getElementById('nopTableTargetBadge');
            if (nopBadge) nopBadge.textContent = `Target: ${Number(data.target || 0.23).toFixed(2)}%`;

            // Render Table 1: NOP Level Table
            renderNopComparisonTable();

            // Render Table 2: Kabupaten Level Table
            filterComparisonTable();

        } catch (e) {
            console.error('Error loading comparison tables:', e);
        }
    };

    // ── Render Table 1: NOP Level Table ──
    function renderNopComparisonTable() {
        const tbody = document.getElementById('nopTableBody');
        if (!tbody) return;

        if (!rawNopComparisonData.length) {
            tbody.innerHTML = '<tr><td colspan="14" style="text-align:center; padding:15px;">No NOP data available.</td></tr>';
            return;
        }

        let html = rawNopComparisonData.map(r => {
            const deltaColor = r.wow_ro_delta_pp < 0 ? '#10b981' : (r.wow_ro_delta_pp > 0 ? '#ef4444' : 'inherit');
            const deltaSign = r.wow_ro_delta_pp > 0 ? `+${r.wow_ro_delta_pp.toFixed(2)}` : `${r.wow_ro_delta_pp.toFixed(2)}`;
            const targetBadge = r.is_pass
                ? '<span class="badge-pass" style="font-size:10.5px; padding:2px 7px;">PASS</span>'
                : '<span class="badge-fail" style="font-size:10.5px; padding:2px 7px;">BREACH</span>';
            const wowBadge = r.wow_status === 'Improved'
                ? '<span style="color:#10b981; font-weight:700;"><i class="fas fa-arrow-down"></i> Improved</span>'
                : (r.wow_status === 'Degraded'
                    ? '<span style="color:#ef4444; font-weight:700;"><i class="fas fa-arrow-up"></i> Degraded</span>'
                    : '<span style="color:var(--text-muted); font-weight:600;">Stable</span>');

            return `
                <tr>
                    <td style="text-align:left; font-weight:700; color:var(--text-main); font-size:11px;">${r.branch}</td>
                    <td>${r.total_grid.toLocaleString()}</td>
                    <td>${r.red_cov.toLocaleString()}</td>
                    <td>${r.red_cov_pct.toFixed(2)}%</td>
                    <td style="font-weight:600; color:#ea580c;">${r.red_optim.toLocaleString()}</td>
                    <td style="font-weight:700; color:${r.is_pass ? '#059669' : '#dc2626'};">${r.red_optim_pct.toFixed(2)}%</td>
                    <td>${r.red_eng.toLocaleString()}</td>
                    <td>${r.red_eng_pct.toFixed(2)}%</td>
                    <td>${r.prev_red_optim.toLocaleString()}</td>
                    <td>${r.prev_red_optim_pct.toFixed(2)}%</td>
                    <td style="color:${deltaColor}; font-weight:700;">${deltaSign}</td>
                    <td>${Number(r.target).toFixed(2)}%</td>
                    <td style="text-align:center;">${targetBadge}</td>
                    <td style="text-align:center;">${wowBadge}</td>
                </tr>
            `;
        }).join('');

        // Append Total Region Row
        if (rawTotalNopData) {
            const t = rawTotalNopData;
            const deltaColor = t.wow_ro_delta_pp < 0 ? '#10b981' : (t.wow_ro_delta_pp > 0 ? '#ef4444' : 'inherit');
            const deltaSign = t.wow_ro_delta_pp > 0 ? `+${t.wow_ro_delta_pp.toFixed(2)}` : `${t.wow_ro_delta_pp.toFixed(2)}`;
            const targetBadge = t.is_pass
                ? '<span class="badge-pass" style="font-size:10px; padding:1px 6px;">PASS</span>'
                : '<span class="badge-fail" style="font-size:10px; padding:1px 6px;">BREACH</span>';
            const wowBadge = t.wow_status === 'Improved'
                ? '<span style="color:#10b981; font-weight:700;"><i class="fas fa-arrow-down"></i> Improved</span>'
                : (t.wow_status === 'Degraded'
                    ? '<span style="color:#ef4444; font-weight:700;"><i class="fas fa-arrow-up"></i> Degraded</span>'
                    : '<span style="color:var(--text-muted); font-weight:600;">Stable</span>');

            html += `
                <tr style="background:var(--secondary); font-weight:800; border-top:2px solid var(--border);">
                    <td style="text-align:left; font-size:11px; color:#8B0000;">${t.branch}</td>
                    <td>${t.total_grid.toLocaleString()}</td>
                    <td>${t.red_cov.toLocaleString()}</td>
                    <td>${t.red_cov_pct.toFixed(2)}%</td>
                    <td style="color:#ea580c;">${t.red_optim.toLocaleString()}</td>
                    <td style="color:${t.is_pass ? '#059669' : '#dc2626'}; font-size:11px;">${t.red_optim_pct.toFixed(2)}%</td>
                    <td>${t.red_eng.toLocaleString()}</td>
                    <td>${t.red_eng_pct.toFixed(2)}%</td>
                    <td>${t.prev_red_optim.toLocaleString()}</td>
                    <td>${t.prev_red_optim_pct.toFixed(2)}%</td>
                    <td style="color:${deltaColor}; font-size:11px;">${deltaSign}</td>
                    <td>${Number(t.target).toFixed(2)}%</td>
                    <td style="text-align:center;">${targetBadge}</td>
                    <td style="text-align:center;">${wowBadge}</td>
                </tr>
            `;
        }

        tbody.innerHTML = html;
    }

    // ── Render Table 2: Kabupaten Level Table (With inline selectors) ──
    window.filterComparisonTable = function () {
        const branchEl = document.getElementById('kabFilterBranch');
        const statusEl = document.getElementById('kabFilterStatus');
        const searchEl = document.getElementById('kabSearchInput');

        const branchFilter = branchEl ? branchEl.value : 'ALL';
        const statusFilter = statusEl ? statusEl.value : 'ALL';
        const searchInput = (searchEl ? searchEl.value : '').trim().toUpperCase();

        let filtered = rawComparisonData.filter(r => {
            const matchBranch = branchFilter === 'ALL' || r.branch === branchFilter;
            const matchStatus = statusFilter === 'ALL' || (statusFilter === 'PASS' ? r.is_pass : !r.is_pass);
            const matchSearch = !searchInput || r.kabupaten.toUpperCase().includes(searchInput);
            return matchBranch && matchStatus && matchSearch;
        });

        // Apply sorting
        filtered.sort((a, b) => {
            let va = a[sortColumn];
            let vb = b[sortColumn];
            if (typeof va === 'string') {
                return sortDirection === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
            }
            va = Number(va || 0);
            vb = Number(vb || 0);
            return sortDirection === 'asc' ? va - vb : vb - va;
        });

        const tbody = document.getElementById('kabTableBody');
        const tfoot = document.getElementById('kabTableFoot');
        if (!tbody) return;

        if (!filtered.length) {
            tbody.innerHTML = '<tr><td colspan="15" style="text-align:center; padding:22px; color:var(--text-muted); font-size:12.5px;">No matching records found.</td></tr>';
            if (tfoot) tfoot.innerHTML = '';
            return;
        }

        let totGrid = 0, totRed = 0, totOptim = 0, totEng = 0, totPrevOptim = 0;

        tbody.innerHTML = filtered.map(r => {
            totGrid += r.total_grid;
            totRed += r.red_cov;
            totOptim += r.red_optim;
            totEng += r.red_eng;
            totPrevOptim += r.prev_red_optim;

            const deltaColor = r.wow_ro_delta_pp < 0 ? '#10b981' : (r.wow_ro_delta_pp > 0 ? '#ef4444' : 'inherit');
            const deltaSign = r.wow_ro_delta_pp > 0 ? `+${r.wow_ro_delta_pp}` : `${r.wow_ro_delta_pp}`;
            const badge = r.is_pass
                ? '<span class="badge-pass" style="font-size:10px; padding:1px 6px;">PASS</span>'
                : '<span class="badge-fail" style="font-size:10px; padding:1px 6px;">BREACH</span>';

            return `
                <tr>
                    <td style="text-align:left; font-weight:700; color:var(--text-main); font-size:11px;">${r.branch}</td>
                    <td style="text-align:left; font-weight:600; font-size:11px;">${r.kabupaten}</td>
                    <td>${r.total_grid.toLocaleString()}</td>
                    <td>${r.red_cov.toLocaleString()}</td>
                    <td>${r.red_cov_pct.toFixed(2)}%</td>
                    <td style="font-weight:600; color:#ea580c;">${r.red_optim.toLocaleString()}</td>
                    <td style="font-weight:700; color:${r.is_pass ? '#059669' : '#dc2626'};">${r.red_optim_pct.toFixed(2)}%</td>
                    <td>${r.red_eng.toLocaleString()}</td>
                    <td>${r.red_eng_pct.toFixed(2)}%</td>
                    <td>${r.prev_red_optim.toLocaleString()}</td>
                    <td>${r.prev_red_optim_pct.toFixed(2)}%</td>
                    <td style="color:${deltaColor}; font-weight:700;">${deltaSign}</td>
                    <td>${r.more_than_3_wks.toLocaleString()}</td>
                    <td>${r.forming_cluster.toFixed(1)}</td>
                    <td style="text-align:center;">${badge}</td>
                </tr>
            `;
        }).join('');

        if (tfoot) {
            const totRedPct = totGrid > 0 ? (totRed * 100 / totGrid).toFixed(2) : '0.00';
            const totOptimPct = totGrid > 0 ? (totOptim * 100 / totGrid).toFixed(2) : '0.00';
            const totEngPct = totGrid > 0 ? (totEng * 100 / totGrid).toFixed(2) : '0.00';
            tfoot.innerHTML = `
                <tr>
                    <td colspan="2" style="text-align:left; font-size:11px;">TOTAL / AGGREGATION (${filtered.length} KAB)</td>
                    <td>${totGrid.toLocaleString()}</td>
                    <td>${totRed.toLocaleString()}</td>
                    <td>${totRedPct}%</td>
                    <td>${totOptim.toLocaleString()}</td>
                    <td style="color:#059669;">${totOptimPct}%</td>
                    <td>${totEng.toLocaleString()}</td>
                    <td>${totEngPct}%</td>
                    <td>${totPrevOptim.toLocaleString()}</td>
                    <td colspan="5"></td>
                </tr>
            `;
        }

        updateSortIndicators();
    };

    // ── Table Column Sorting ──
    window.sortTableBy = function (col) {
        if (sortColumn === col) {
            sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            sortColumn = col;
            sortDirection = 'desc';
        }
        filterComparisonTable();
    };

    function updateSortIndicators() {
        document.querySelectorAll('.sort-icon').forEach(icon => {
            icon.textContent = '';
        });
        const activeIcon = document.getElementById(`sort-${sortColumn}`);
        if (activeIcon) {
            activeIcon.textContent = sortDirection === 'asc' ? ' ▲' : ' ▼';
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Multi-File Batch Queue Importer for Redcov
    // ══════════════════════════════════════════════════════════════════
    let redcovFileQueue = [];
    let isRedcovQueueRunning = false;
    let redcovQueueAborted = false;

    window.openRedcovImportModal = function () {
        const modal = document.getElementById('redcovImportModal');
        if (modal) modal.style.display = 'flex';
        initRedcovDropZoneEvents();
    };

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

    window.closeRedcovImportModal = function () {
        if (isRedcovQueueRunning) {
            if (!confirm('An import queue is currently running. Are you sure you want to cancel and close?')) {
                return;
            }
            redcovQueueAborted = true;
        }
        const hadSuccess = redcovFileQueue.some(f => f.status === 'done');
        const modal = document.getElementById('redcovImportModal');
        if (modal) modal.style.display = 'none';
        resetRedcovImportState();
        if (hadSuccess) {
            window.location.reload();
        }
    };

    function resetRedcovImportState() {
        redcovFileQueue = [];
        isRedcovQueueRunning = false;
        redcovQueueAborted = false;
        const fileInput = document.getElementById('redcovFileInput');
        if (fileInput) fileInput.value = '';
        renderRedcovQueueUI();
        const alertBox = document.getElementById('redcovImportAlert');
        if (alertBox) {
            alertBox.style.display = 'none';
            alertBox.innerHTML = '';
        }
        const prog = document.getElementById('redcovQueueOverallProgress');
        if (prog) prog.style.display = 'none';
        const curFileStage = document.getElementById('redcovCurrentFileStage');
        if (curFileStage) curFileStage.textContent = 'Ready';
        const curFilePct = document.getElementById('redcovCurrentFilePct');
        if (curFilePct) curFilePct.textContent = '--';
        const overallBar = document.getElementById('redcovOverallProgressBar');
        if (overallBar) overallBar.style.width = '0%';
        const overallPct = document.getElementById('redcovOverallPct');
        if (overallPct) overallPct.textContent = '0%';
        const overallStage = document.getElementById('redcovOverallStage');
        if (overallStage) overallStage.textContent = 'Overall Queue: 0 of 0';
    }

    window.clearRedcovQueue = function () {
        if (isRedcovQueueRunning) return;
        resetRedcovImportState();
    };

    function initRedcovDropZoneEvents() {
        const dropZone = document.getElementById('redcovDropZone');
        if (!dropZone || dropZone._hasEvents) return;
        dropZone._hasEvents = true;

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.style.background = 'rgba(139, 0, 0, 0.08)';
                dropZone.style.borderColor = '#8B0000';
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
                addFilesToRedcovQueue(dt.files);
            }
        }, false);
    }

    window.handleRedcovFileSelect = function (input) {
        if (input.files && input.files.length) {
            addFilesToRedcovQueue(input.files);
            input.value = '';
        }
    };

    function addFilesToRedcovQueue(files) {
        if (isRedcovQueueRunning) return;
        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const ext = f.name.toLowerCase().split('.').pop();
            if (!['xlsx', 'xls', 'csv'].includes(ext)) {
                continue;
            }
            if (redcovFileQueue.some(item => item.name === f.name && item.size === f.size)) {
                continue;
            }
            redcovFileQueue.push({
                id: 'redcov_q_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
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
        renderRedcovQueueUI();
    }

    function renderRedcovQueueUI() {
        const sec = document.getElementById('redcovQueueSection');
        const list = document.getElementById('redcovQueueListContainer');
        const countEl = document.getElementById('redcovQueueTotalCount');
        const sizeEl = document.getElementById('redcovQueueTotalSize');
        const btnCount = document.getElementById('redcovQueueBtnCount');
        const submitBtn = document.getElementById('redcovImportBtn');
        const addMoreBtn = document.getElementById('btnAddMoreRedcovFiles');
        const clearBtn = document.getElementById('btnClearRedcovQueue');

        if (!redcovFileQueue.length) {
            if (sec) sec.style.display = 'none';
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-upload"></i> Upload & Import (0)';
            }
            if (addMoreBtn) addMoreBtn.style.display = 'none';
            return;
        }

        if (sec) sec.style.display = 'block';
        if (addMoreBtn) addMoreBtn.style.display = isRedcovQueueRunning ? 'none' : 'inline-block';
        if (clearBtn) clearBtn.style.display = isRedcovQueueRunning ? 'none' : 'inline-block';

        const totalBytes = redcovFileQueue.reduce((acc, f) => acc + f.size, 0);
        const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);

        if (countEl) countEl.textContent = redcovFileQueue.length;
        if (sizeEl) sizeEl.textContent = `${totalMb} MB`;

        if (submitBtn && !isRedcovQueueRunning) {
            const allDone = redcovFileQueue.length > 0 && redcovFileQueue.every(f => f.status === 'done');
            if (allDone) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Import Complete (Close & Refresh)';
                submitBtn.onclick = function () {
                    closeRedcovImportModal();
                };
            } else {
                const pendingCount = redcovFileQueue.filter(f => f.status !== 'done').length;
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<i class="fas fa-upload"></i> Upload & Import (${pendingCount})`;
            }
        }

        if (list) {
            list.innerHTML = redcovFileQueue.map((item, idx) => {
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
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(139,0,0,0.12); color:#8B0000; font-weight:700;">
                        <i class="fas fa-arrow-up"></i> ${item.pct || 0}% (${elapsed})
                    </span>`;
                } else if (item.status === 'processing') {
                    const elapsed = formatDuration(item.elapsed_s || 0);
                    badgeHtml = `<span style="font-size:10.5px; padding:2px 8px; border-radius:12px; background:rgba(139,0,0,0.12); color:#8B0000; font-weight:700;">
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
                                <i class="fas fa-file-excel" style="color:#8B0000; flex-shrink:0;"></i>
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

    window.startRedcovQueueImport = async function () {
        if (!redcovFileQueue.length || isRedcovQueueRunning) return;

        isRedcovQueueRunning = true;
        redcovQueueAborted = false;

        const submitBtn = document.getElementById('redcovImportBtn');
        const addMoreBtn = document.getElementById('btnAddMoreRedcovFiles');
        const clearBtn = document.getElementById('btnClearRedcovQueue');
        const alertBox = document.getElementById('redcovImportAlert');
        const overallProg = document.getElementById('redcovQueueOverallProgress');
        const overallBar = document.getElementById('redcovOverallProgressBar');
        const overallStage = document.getElementById('redcovOverallStage');
        const overallPct = document.getElementById('redcovOverallPct');
        const curFileStage = document.getElementById('redcovCurrentFileStage');
        const curFilePct = document.getElementById('redcovCurrentFilePct');

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

        const totalFiles = redcovFileQueue.length;
        const queueStartTime = Date.now();

        for (let i = 0; i < totalFiles; i++) {
            if (redcovQueueAborted) break;

            const item = redcovFileQueue[i];
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
                    renderRedcovQueueUI();
                }
            }, 1000);

            renderRedcovQueueUI();

            try {
                const formData = new FormData();
                formData.append('file', item.file);

                if (curFileStage) curFileStage.textContent = `Uploading ${item.name}...`;
                if (curFilePct) curFilePct.textContent = '5%';

                const uploadRes = await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', '/api/sow/redcov/import', true);

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
                            renderRedcovQueueUI();
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
                    renderRedcovQueueUI();

                    await new Promise((resolve) => {
                        const poll = setInterval(async () => {
                            if (redcovQueueAborted) {
                                clearInterval(poll);
                                clearInterval(fileTimer);
                                resolve();
                                return;
                            }
                            try {
                                const pres = await fetch('/api/sow/redcov/import/progress/' + data.job_id);
                                const pdata = await pres.json();

                                if (pdata.status !== 'queued') {
                                    item.pct = pdata.pct || 15;
                                    item.message = pdata.message || pdata.status;
                                    item.elapsed_s = Math.round((Date.now() - fileStartTime) / 1000);
                                    if (curFileStage) curFileStage.textContent = `${item.name}: ${pdata.message || pdata.status}`;
                                    if (curFilePct) curFilePct.textContent = `${pdata.pct || 0}%`;
                                    renderRedcovQueueUI();
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
                                    renderRedcovQueueUI();
                                    resolve();
                                } else if (pdata.status === 'error') {
                                    clearInterval(poll);
                                    clearInterval(fileTimer);
                                    item.status = 'error';
                                    item.duration_s = Math.round((Date.now() - fileStartTime) / 1000);
                                    item.duration_str = formatDuration(item.duration_s);
                                    item.message = pdata.message || 'Import error';
                                    failCount++;
                                    renderRedcovQueueUI();
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
                                renderRedcovQueueUI();
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
                    renderRedcovQueueUI();
                }
            } catch (err) {
                clearInterval(fileTimer);
                item.status = 'error';
                item.duration_s = Math.round((Date.now() - fileStartTime) / 1000);
                item.duration_str = formatDuration(item.duration_s);
                item.message = err.message || 'Network error';
                failCount++;
                renderRedcovQueueUI();
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

        isRedcovQueueRunning = false;
        renderRedcovQueueUI();

        if (submitBtn) {
            if (successCount > 0) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Import Complete (Close & Refresh)';
                submitBtn.onclick = function () {
                    closeRedcovImportModal();
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
        fetch('/api/sow/redcov/summary?refresh=1').catch(() => {});
    };

    // ── Chart Enlarge Modal Handlers ──
    window.openChartEnlargeModal = function (chartType) {
        if (!currentTrendData) return;
        currentEnlargedType = chartType;

        const th = getEChartsTheme();
        const modal = document.getElementById('chartEnlargeModal');
        const titleEl = document.getElementById('enlargeModalTitle');
        const subtitleEl = document.getElementById('enlargeModalSubtitle');
        const container = document.getElementById('enlargedChartContainer');
        if (!modal || !container) return;

        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        if (chartEnlargedInstance) {
            chartEnlargedInstance.dispose();
        }
        chartEnlargedInstance = echarts.init(container);

        if (chartType === 'coverage') {
            titleEl.innerHTML = '<i class="fas fa-chart-area" style="color:#8B0000;"></i> Trend Coverage PUMA';
            subtitleEl.textContent = 'Total Good Coverage vs Total Red Coverage & Percentage Red Coverage Trend';

            const isShareMode = coverageMetricMode === 'share';
            const goodData = isShareMode
                ? currentTrendData.coverage_trend.total_grid.map((tg, i) => tg > 0 ? Number(((tg - currentTrendData.coverage_trend.red_cov[i]) * 100 / tg).toFixed(2)) : 0)
                : currentTrendData.coverage_trend.good_cov;
            const redData = isShareMode
                ? currentTrendData.coverage_trend.total_grid.map((tg, i) => tg > 0 ? Number((currentTrendData.coverage_trend.red_cov[i] * 100 / tg).toFixed(2)) : 0)
                : currentTrendData.coverage_trend.red_cov;

            const opt = {
                tooltip: {
                    ...getTooltipStyle(th),
                    trigger: 'axis',
                    axisPointer: { type: 'cross', lineStyle: { color: th.textMuted, type: 'dashed' } }
                },
                legend: {
                    data: ['#Good Cov', '#Red Cov', '%_Red_Cov'],
                    bottom: 10,
                    textStyle: { fontSize: 13, fontWeight: 600, color: th.legendColor }
                },
                grid: { top: 40, right: 65, bottom: 65, left: 75 },
                xAxis: {
                    type: 'category',
                    data: currentTrendData.labels,
                    axisLabel: { fontSize: 12, color: th.textMuted },
                    axisLine: { lineStyle: { color: th.axisLineColor } }
                },
                yAxis: [
                    {
                        type: 'value',
                        name: isShareMode ? '% Share' : '#Grid',
                        nameTextStyle: { fontSize: 12, fontWeight: 600, color: th.textMuted },
                        axisLabel: {
                            formatter: (v) => isShareMode ? `${v}%` : (v >= 1000 ? `${Math.round(v/1000)}k` : v),
                            fontSize: 12,
                            color: th.textMuted
                        },
                        splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
                    },
                    {
                        type: 'value',
                        name: '% Red Cov',
                        nameTextStyle: { fontSize: 12, fontWeight: 600, color: th.textMuted },
                        axisLabel: { formatter: '{value}%', fontSize: 12, color: th.textMuted },
                        splitLine: { show: false }
                    }
                ],
                series: [
                    {
                        name: '#Good Cov',
                        type: 'bar',
                        stack: 'cov',
                        itemStyle: { color: THEME_COLORS.goodCov },
                        data: goodData
                    },
                    {
                        name: '#Red Cov',
                        type: 'bar',
                        stack: 'cov',
                        itemStyle: { color: THEME_COLORS.redCov, borderRadius: [3, 3, 0, 0] },
                        data: redData
                    },
                    {
                        name: '%_Red_Cov',
                        type: 'line',
                        yAxisIndex: 1,
                        smooth: 0.2,
                        itemStyle: { color: th.lineRedCov },
                        lineStyle: { width: 3, color: th.lineRedCov },
                        symbol: 'circle',
                        symbolSize: 7,
                        data: (currentTrendData.coverage_trend.red_cov_pct || []).map(val => {
                            const v = Number(val);
                            return {
                                value: val,
                                label: {
                                    show: true,
                                    position: 'top',
                                    distance: 8,
                                    fontSize: 11,
                                    fontWeight: 'bold',
                                    color: th.lineRedCov,
                                    backgroundColor: th.labelBg,
                                    borderColor: th.labelBorder,
                                    borderWidth: 1,
                                    borderRadius: 4,
                                    padding: [2, 4],
                                    formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                                }
                            };
                        })
                    }
                ]
            };
            chartEnlargedInstance.setOption(opt);

        } else if (chartType === 'breakdown') {
            titleEl.innerHTML = '<i class="fas fa-layer-group" style="color:#8B0000;"></i> Red Coverage Breakdown & Target';
            subtitleEl.textContent = 'Optimization vs Engineering Breakdown & % Red Optim Trend with Dynamic Target Threshold';

            const targetSeries = currentTrendData.breakdown_trend.target || [];

            const opt = {
                tooltip: {
                    ...getTooltipStyle(th),
                    trigger: 'axis',
                    axisPointer: { type: 'cross', lineStyle: { color: th.textMuted, type: 'dashed' } }
                },
                legend: {
                    data: ['#Red Optim', '#Red Engineering', '%_Red_Optim', 'Target (Red Optim)'],
                    bottom: 10,
                    textStyle: { fontSize: 13, fontWeight: 600, color: th.legendColor }
                },
                grid: { top: 40, right: 65, bottom: 65, left: 75 },
                xAxis: {
                    type: 'category',
                    data: currentTrendData.labels,
                    axisLabel: { fontSize: 12, color: th.textMuted },
                    axisLine: { lineStyle: { color: th.axisLineColor } }
                },
                yAxis: [
                    {
                        type: 'value',
                        name: '#Grid',
                        nameTextStyle: { fontSize: 12, fontWeight: 600, color: th.textMuted },
                        axisLabel: {
                            formatter: (v) => v >= 1000 ? `${Math.round(v/1000)}k` : v,
                            fontSize: 12,
                            color: th.textMuted
                        },
                        splitLine: { lineStyle: { color: th.splitLineColor, type: 'dashed' } }
                    },
                    {
                        type: 'value',
                        name: '% Optim',
                        nameTextStyle: { fontSize: 12, fontWeight: 600, color: th.textMuted },
                        axisLabel: { formatter: '{value}%', fontSize: 12, color: th.textMuted },
                        splitLine: { show: false }
                    }
                ],
                series: [
                    {
                        name: '#Red Optim',
                        type: 'bar',
                        stack: 'redSplit',
                        itemStyle: { color: THEME_COLORS.redOptim },
                        data: currentTrendData.breakdown_trend.red_optim
                    },
                    {
                        name: '#Red Engineering',
                        type: 'bar',
                        stack: 'redSplit',
                        itemStyle: { color: THEME_COLORS.redEng, borderRadius: [3, 3, 0, 0] },
                        data: currentTrendData.breakdown_trend.red_eng
                    },
                    {
                        name: '%_Red_Optim',
                        type: 'line',
                        yAxisIndex: 1,
                        smooth: 0.2,
                        itemStyle: { color: THEME_COLORS.redOptimLine },
                        lineStyle: { width: 3, color: THEME_COLORS.redOptimLine },
                        symbol: 'circle',
                        symbolSize: 7,
                        data: (currentTrendData.breakdown_trend.red_optim_pct || []).map((val, idx) => {
                            const v = Number(val);
                            const tgt = (targetSeries && targetSeries[idx] !== undefined) ? Number(targetSeries[idx]) : 0.23;
                            const meets = !isNaN(v) && v < tgt;
                            const labelColor = meets ? '#10b981' : '#ef4444';
                            return {
                                value: val,
                                label: {
                                    show: true,
                                    position: 'top',
                                    distance: 8,
                                    fontSize: 11,
                                    fontWeight: 'bold',
                                    color: labelColor,
                                    backgroundColor: th.labelBg,
                                    borderColor: meets ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
                                    borderWidth: 1,
                                    borderRadius: 4,
                                    padding: [2, 4],
                                    formatter: isNaN(v) ? '' : `${v.toFixed(2)}%`
                                }
                            };
                        })
                    },
                    {
                        name: 'Target (Red Optim)',
                        type: 'line',
                        yAxisIndex: 1,
                        step: 'end',
                        itemStyle: { color: th.targetLineColor },
                        lineStyle: { width: 2.2, type: 'dashed', color: th.targetLineColor },
                        symbol: 'circle',
                        symbolSize: 4,
                        data: targetSeries
                    }
                ]
            };
            chartEnlargedInstance.setOption(opt);
        }

        setTimeout(() => {
            if (chartEnlargedInstance) chartEnlargedInstance.resize();
        }, 120);
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
        const url = chartEnlargedInstance.getDataURL({
            pixelRatio: 2,
            backgroundColor: '#ffffff'
        });
        const a = document.createElement('a');
        a.download = `OKR_Redcov_${currentEnlargedType || 'chart'}_enlarged.png`;
        a.href = url;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

})();
