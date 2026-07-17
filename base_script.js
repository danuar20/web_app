
/* ── Mobile Dropdown Backdrop Helper ── */
function closeMobileDropdowns() {
    document.querySelectorAll('.dropdown-menu').forEach(function(m) {
        m.style.display = 'none';
    });
    var bd = document.getElementById('mobileDropdownBackdrop');
    if (bd) bd.classList.remove('active');
}

/* Patch all dropdown toggles to also show/hide the backdrop on mobile */
document.addEventListener('DOMContentLoaded', function() {
    /* Watch for any dropdown-menu display changes on mobile */
    function updateBackdrop() {
        if (!document.body.classList.contains('mobile-view')) return;
        var anyOpen = Array.from(document.querySelectorAll('.dropdown-menu')).some(function(m) {
            return m.style.display && m.style.display !== 'none';
        });
        var bd = document.getElementById('mobileDropdownBackdrop');
        if (bd) bd.classList.toggle('active', anyOpen);
    }

    /* Observe display changes on dropdown menus */
    document.querySelectorAll('.dropdown-menu').forEach(function(menu) {
        var observer = new MutationObserver(updateBackdrop);
        observer.observe(menu, { attributes: true, attributeFilter: ['style'] });
    });
});

/* ── Theme ── */
function updateThemeIcon(){
    var t = document.documentElement.getAttribute("data-theme");
    var ic = document.getElementById("themeIcon");
    if(ic){ ic.className = t === "dark" ? "fas fa-sun" : "fas fa-moon"; }
}
function toggleTheme(){
    var next = document.documentElement.getAttribute("data-theme")==="dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch(e){}
    updateThemeIcon();
    setTimeout(function(){ 
        if(typeof updateAllChartsTheme === "function") updateAllChartsTheme();
    }, 80);
}
window.addEventListener("DOMContentLoaded", updateThemeIcon);

function updateAllChartsTheme(){
    if (typeof Chart === 'undefined' || !Chart.instances) return;
    var theme = document.documentElement.getAttribute("data-theme") || "dark";
    var gridColor = theme === "dark" ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)";
    var textColor = theme === "dark" ? "rgba(200,208,224,0.6)" : "rgba(0,0,0,0.6)";

    var charts = Object.values(Chart.instances);
    var i = 0;
    
    function updateNext() {
        if (i >= charts.length) return;
        var chart = charts[i++];
        if (chart.options && chart.options.scales) {
            if (chart.options.scales.x) {
                if (chart.options.scales.x.grid) chart.options.scales.x.grid.color = gridColor;
                if (chart.options.scales.x.ticks) chart.options.scales.x.ticks.color = textColor;
            }
            if (chart.options.scales.y) {
                if (chart.options.scales.y.grid) chart.options.scales.y.grid.color = gridColor;
                if (chart.options.scales.y.ticks) chart.options.scales.y.ticks.color = textColor;
                if (chart.options.scales.y.title) chart.options.scales.y.title.color = textColor;
            }
            if (chart.options.scales.y1 && chart.options.scales.y1.grid) {
                chart.options.scales.y1.grid.color = gridColor;
            }
        }
        if (chart.options && chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
            chart.options.plugins.legend.labels.color = textColor;
        }
        chart.update('none');
        requestAnimationFrame(updateNext);
    }
    updateNext();
}

/* ── View Mode (sidebar show/hide) ── */
function toggleViewMode(){
    var settings = JSON.parse(localStorage.getItem("appSettings") || "{}");
    var isMobile = settings.viewMode === "mobile";
    var next = isMobile ? "desktop" : "mobile";
    settings.viewMode = next;
    localStorage.setItem("appSettings", JSON.stringify(settings));
    applyViewMode(next);
}
function applyViewMode(mode){
    var sb = document.getElementById("sidebar");
    var shell = document.querySelector(".app-shell");
    var isMobile = mode === "mobile";

    if(sb) sb.classList.toggle("mobile-hidden", isMobile);
    if(shell) shell.classList.toggle("sidebar-hidden", isMobile);
    document.body.classList.toggle("mobile-view", isMobile);
    var tBtn = document.getElementById("sidebarToggleBtn");
    if(tBtn){
        tBtn.innerHTML = '<svg class="view-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">' +
            '<rect x="1" y="3" width="15" height="12" rx="2" ry="2"/>' +
            '<path d="M5 21h14M8 21v-2M16 21v-2"/>' +
            '<rect x="18" y="7" width="5" height="9" rx="1.5" ry="1.5"/>' +
            '</svg>';
        tBtn.title = isMobile ? "Switch to Desktop" : "Switch to Mobile";
    }

    // Resize charts after layout change
    setTimeout(function(){
        Object.values(chartInstances).forEach(function(ch){
            if(ch && typeof ch.resize === 'function'){ ch.resize(); ch.update(); }
        });
    }, 100);
}

/* ════════════════ SETTINGS POPUP ════════════════ */
var SETTINGS_STAGED_KEY = "settingsStaged";

function loadStaged(){
    return JSON.parse(sessionStorage.getItem(SETTINGS_STAGED_KEY) || "{}");
}
function saveStaged(staged){
    sessionStorage.setItem(SETTINGS_STAGED_KEY, JSON.stringify(staged));
}

function stageChange(key, value){
    var staged = loadStaged();
    staged[key] = value;
    saveStaged(staged);
    // Preview compact mode immediately
    if(key === "compactMode"){
        document.getElementById("pref-compact").checked = value;
        document.body.classList.toggle("compact-mode", value);
    } else if(key === "showFlash"){
        document.getElementById("pref-flash").checked = value;
    } else if(key === "soundAlerts"){
        document.getElementById("pref-sound").checked = value;
    } else if(key === "tableRows"){
        document.getElementById("pref-tableRows").value = value;
    } else if(key === "autoRefresh"){
        document.getElementById("pref-autoRefresh").value = value;
    } else if(key === "kpiAlertEnabled"){
        document.getElementById("pref-alert-enabled").checked = value;
    }
}

/* ── KPI Threshold staging (per-KPI min/max/enabled) ── */
function stageKpiThreshold(kpiId, field, value){
    var staged = loadStaged();
    if(!staged.kpiThresholds) staged.kpiThresholds = {};
    if(!staged.kpiThresholds[kpiId]){
        // Clone current saved state (if any) to avoid losing it
        var saved = JSON.parse(localStorage.getItem("appSettings") || "{}");
        var existing = (saved.kpiThresholds && saved.kpiThresholds[kpiId]) ? saved.kpiThresholds[kpiId] : {};
        staged.kpiThresholds[kpiId] = {
            enabled: existing.enabled !== undefined ? existing.enabled : true,
            min: existing.min,
            max: existing.max
        };
    }
    staged.kpiThresholds[kpiId][field] = value;
    saveStaged(staged);
    // Apply breach highlighting to active table cells
    applyKPIPreCheck();
}

function highlightDateBtn(btn){
    document.querySelectorAll(".date-btn-pop").forEach(function(b){ b.classList.remove("active"); });
    btn.classList.add("active");
}

function applyStaged(){
    var staged = loadStaged();
    var settings = JSON.parse(localStorage.getItem("appSettings") || "{}");
    for(var k in staged){
        settings[k] = staged[k];
    }
    // Also merge nested kpiThresholds before persisting
    if(staged.kpiThresholds){
        settings.kpiThresholds = Object.assign(settings.kpiThresholds || {}, staged.kpiThresholds);
    }
    localStorage.setItem("appSettings", JSON.stringify(settings));
    sessionStorage.removeItem(SETTINGS_STAGED_KEY);

    closeSettingsPopup();
    showSettingsToast();
    // Re-run any page-specific threshold checks
    if(typeof applyKPIPreCheck === "function") applyKPIPreCheck();
}

function discardStaged(){
    sessionStorage.removeItem(SETTINGS_STAGED_KEY);
    loadSettingsIntoUI();
}

function showSettingsToast(){
    var t = document.getElementById("settingsToast");
    t.style.display = "block";
    t.style.animation = "none";
    t.offsetHeight;
    t.style.animation = "toastFade 2s ease forwards";
}

function loadSettingsIntoUI(){
    var settings = JSON.parse(localStorage.getItem("appSettings") || "{}");
    // Apply all saved settings to UI
    var compact = settings.compactMode || false;
    document.getElementById("pref-compact").checked = compact;
    document.body.classList.toggle("compact-mode", compact);
    document.getElementById("pref-flash").checked = settings.showFlash !== undefined ? settings.showFlash : true;
    document.getElementById("pref-sound").checked = settings.soundAlerts || false;

    // KPI Alerts master toggle
    document.getElementById("pref-alert-enabled").checked = settings.kpiAlertEnabled !== false;

    // Build threshold rows from static KPI list
    var kpiDefaults = [
        {id:"payloadChart",    label:"Payload",         unit:"MB",     defaultMin:null,defaultMax:null},
        {id:"cssrChart",       label:"CSSR",              unit:"%",      defaultMin:85,  defaultMax:100},
        {id:"volteChart",      label:"VoLTE Traffic",     unit:"Erl",    defaultMin:null,defaultMax:null},
        {id:"maxRrcChart",     label:"Max RRC",           unit:"Users",  defaultMin:null,defaultMax:null},
        {id:"activeUserChart", label:"Active User",       unit:"Users",  defaultMin:null,defaultMax:null},
        {id:"dlPrbChart",      label:"DL PRB",            unit:"%",      defaultMin:0,   defaultMax:75},
        {id:"ulPrbChart",      label:"UL PRB",            unit:"%",      defaultMin:0,   defaultMax:75},
        {id:"dlThpChart",      label:"User DL Thp",       unit:"Mbps",   defaultMin:5,   defaultMax:null},
        {id:"ulThpChart",      label:"User UL Thp",       unit:"Mbps",   defaultMin:2,   defaultMax:null},
        {id:"availChart",      label:"Availability",      unit:"%",      defaultMin:95,  defaultMax:100},
        {id:"erabSrChart",     label:"ERAB SR",            unit:"%",      defaultMin:85,  defaultMax:100},
        {id:"rrcSrChart",      label:"RRC SR",             unit:"%",      defaultMin:85,  defaultMax:100},
        {id:"s1SrChart",       label:"S1 SR",             unit:"%",      defaultMin:95,  defaultMax:100},
        {id:"sdrChart",        label:"SDR",               unit:"%",      defaultMin:0,   defaultMax:5},
        {id:"ifhoChart",       label:"IFHO",              unit:"%",      defaultMin:90,  defaultMax:100},
        {id:"csfbChart",       label:"CSFB",              unit:"%",      defaultMin:85,  defaultMax:100},
        {id:"seChart",         label:"SE",                unit:"",       defaultMin:null,defaultMax:null},
        {id:"cqiChart",        label:"CQI",               unit:"",       defaultMin:0,   defaultMax:15},
    ];

    var tbody = document.getElementById("kpiThresholdRows");
    if(tbody){
        tbody.innerHTML = "";
        var kpiThresholds = settings.kpiThresholds || {};
        kpiDefaults.forEach(function(kpi){
            var cfg = kpiThresholds[kpi.id] || {enabled: true, min: kpi.defaultMin, max: kpi.defaultMax};
            var row = document.createElement("tr");
            row.style.borderBottom = "1px solid rgba(79,172,254,0.06)";
            var minVal = cfg.min !== undefined && cfg.min !== null ? cfg.min : (kpi.defaultMin !== null ? kpi.defaultMin : "");
            var maxVal = cfg.max !== undefined && cfg.max !== null ? cfg.max : (kpi.defaultMax !== null ? kpi.defaultMax : "");
            row.innerHTML = [
                '<td style="padding:4px 6px;color:inherit;font-size:10px;">' + kpi.label + '</td>',
                '<td style="padding:4px; text-align:center;">',
                    '<label class="toggle-switch" style="transform:scale(0.75);transform-origin:center">',
                        '<input type="checkbox" id="kt-en-' + kpi.id + '" ' + (cfg.enabled ? 'checked' : '') + ' ',
                            'onchange="stageKpiThreshold(\'' + kpi.id + '\', \'enabled\', this.checked)">',
                        '<span class="toggle-slider"></span>',
                    '</label>',
                '</td>',
                '<td style="padding:4px; text-align:right;">',
                    '<input type="number" id="kt-min-' + kpi.id + '" value="' + minVal + '" ',
                        'style="width:44px;padding:3px 4px;border-radius:4px;border:1px solid rgba(79,172,254,0.15);',
                        'background:rgba(79,172,254,0.05);color:inherit;font-size:9px;text-align:right;" ',
                        'onchange="stageKpiThreshold(\'' + kpi.id + '\', \'min\', parseFloat(this.value)||null)" ',
                        'placeholder="—" title="Min threshold">',
                '</td>',
                '<td style="padding:4px; text-align:right;">',
                    '<input type="number" id="kt-max-' + kpi.id + '" value="' + maxVal + '" ',
                        'style="width:44px;padding:3px 4px;border-radius:4px;border:1px solid rgba(79,172,254,0.15);',
                        'background:rgba(79,172,254,0.05);color:inherit;font-size:9px;text-align:right;" ',
                        'onchange="stageKpiThreshold(\'' + kpi.id + '\', \'max\', parseFloat(this.value)||null)" ',
                        'placeholder="—" title="Max threshold">',
                '</td>'
            ].join('');
            tbody.appendChild(row);
        });
    }

    document.getElementById("pref-tableRows").value = settings.tableRows || "50";
    document.getElementById("pref-autoRefresh").value = settings.autoRefresh || "0";
    var fmt = settings.dateFormat || "YYYY-MM-DD";
    document.querySelectorAll(".date-btn-pop").forEach(function(b){
        b.classList.toggle("active", b.textContent.trim() === fmt);
    });
}

function openSettingsPopup(){
    loadSettingsIntoUI();
    sessionStorage.removeItem(SETTINGS_STAGED_KEY);
    document.getElementById("accountDropdown").classList.remove("open");
    document.getElementById("settingsOverlay").classList.add("open");
}

function closeSettingsPopup(){
    var staged = loadStaged();
    if(Object.keys(staged).length > 0){
        if(!confirm("Discard unsaved changes?")) return;
        sessionStorage.removeItem(SETTINGS_STAGED_KEY);
    }
    document.getElementById("settingsOverlay").classList.remove("open");
    if(!document.getElementById('chartModalOverlay').classList.contains('open')){
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
    }
}

// ESC key closes settings popup
document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && document.getElementById("settingsOverlay").classList.contains("open")){
        closeSettingsPopup();
    }
});

/* ── Username fill from session (passed via template var) ── */
(function(){
    var u = "{{ username | default('') }}";
    if(u){
        document.querySelectorAll("#accountName").forEach(function(el){ el.textContent = u; });
        document.querySelectorAll("#dropName").forEach(function(el){ el.textContent = u; });
        document.querySelectorAll("#avatarLetters").forEach(function(el){ el.textContent = u.substring(0,2).toUpperCase(); });
    }
})();

/* ── Account dropdown ── */
var _accountChip = document.getElementById("accountChip");
var _accountDropdown = document.getElementById("accountDropdown");
if(_accountChip){
    _accountChip.addEventListener("click", function(e){
        e.stopPropagation();
        if(_accountDropdown) _accountDropdown.classList.toggle("open");
    });
}
document.addEventListener("click", function(){
    if(_accountDropdown) _accountDropdown.classList.remove("open");
    document.querySelectorAll(".ms-dropdown").forEach(function(d){ d.classList.remove("open"); });
});

/* ── Mobile Bottom Nav — auto-detect active page ── */
(function(){
    if(!document.body.classList.contains("mobile-view")) return;
    var path = window.location.pathname;
    var navItems = document.querySelectorAll(".mob-nav-item");
    navItems.forEach(function(item){
        var href = item.getAttribute("href") || "";
        if(path === href || (href !== "/" && path.startsWith(href))){
            item.classList.add("active");
        }
    });
})();

/* ── Sidebar collapse ── */
function toggleSidebar(){
    var sb = document.getElementById("sidebar");
    var ic = document.getElementById("toggleIcon");
    var txt = document.getElementById("toggleText");
    var collapsed = sb.classList.toggle("collapsed");
    if(ic) {
        ic.className = collapsed ? "fas fa-indent" : "fas fa-outdent";
        ic.style.transform = "rotate(0deg)";
    }
    if(txt) txt.textContent = collapsed ? "Expand sidebar" : "Collapse sidebar";
    document.getElementById("sidebarToggle").title = collapsed ? "Expand sidebar" : "Collapse sidebar";
    localStorage.setItem("sidebarCollapsed", collapsed ? "1" : "0");
    /* Directly resize every chart after transition */
    setTimeout(function(){
        Object.values(chartInstances).forEach(function(ch){
            if(ch && typeof ch.resize === 'function'){ ch.resize(); }
        });
    }, 380);
}

/* ── Chart Modal Popup Functions ── */
var chartInstances = window.chartInstances || {};
var modalChart = null;

/* ResizeObserver removed: Chart.js built-in responsiveness handles resizing efficiently. 
   The manual observer caused extreme lag by forcefully updating all charts simultaneously. */

function popupTickCallback(value, index){
    var label = value;
    if(typeof value === 'number' && Array.isArray(this.labels)){
        label = this.labels[value] || value;
    }
    if(typeof label === 'string' && label.indexOf(' ') > -1){
        var parts = label.split(' ');
        var dateParts = parts[0].split('-');
        if(dateParts.length === 3){
            var day = dateParts[2];
            var month = parseInt(dateParts[1], 10) - 1;
            var monthNames = ["Jan","Feb","Mar","Apr","Mei","Jun","Jul","Agt","Sep","Okt","Nov","Des"];
            return day + ' ' + monthNames[month];
        }
    }
    return label;
}

function buildModalConfig(sourceChart, titleText){
    var baseOptions = JSON.parse(JSON.stringify(sourceChart.options || {}));
    baseOptions.maintainAspectRatio = false;
    baseOptions.animation = { duration: 0 };   // custom rAF draw animation below — no Chart.js default
    baseOptions.plugins = baseOptions.plugins || {};
    baseOptions.plugins.zoom = {
        pan: { enabled: true, mode: 'x' },
        zoom: { wheel: { enabled: true }, pinch: { enabled: true }, drag: { enabled: true }, mode: 'x' },
        limits: { x: { min: 'original', max: 'original' }, y: { min: 'original', max: 'original' } }
    };
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    baseOptions.plugins.title = {
        display: false,
        text: titleText || '',
        padding: { top: 6, bottom: 10 },
        color: isDark ? '#c8d0e0' : '#1e293b',
        font: { size: 14, weight: '600' }
    };
    baseOptions.plugins.legend = Object.assign({}, baseOptions.plugins.legend || {}, {
      display: true,
      position: 'bottom',
      labels: Object.assign({
        usePointStyle: false,
        boxWidth: 12,
        padding: 6,
        font: { size: 10 },
        filter: function(item, chart) {
            return !chart.datasets[item.datasetIndex].hidden;
        }
      }, (baseOptions.plugins.legend && baseOptions.plugins.legend.labels) || {})
    });
    baseOptions.scales = baseOptions.scales || {};
    // Apply consistent modal x-axis: day + month name (e.g. 19 Mei)
    var _origX = baseOptions.scales.x ? Object.assign({}, baseOptions.scales.x) : {};
    baseOptions.scales.x = Object.assign(_origX, {
        ticks: Object.assign({}, (_origX.ticks || {}), {
            maxRotation: 0,
            minRotation: 0,
            autoSkip: true,
            maxTicksLimit: 10,
            autoSkipPadding: 16,
            callback: function(value){
                var tickLabel = value;
                if(typeof value === 'number' && Array.isArray(sourceChart.data.labels)){
                    tickLabel = sourceChart.data.labels[value] || value;
                }
                if(typeof tickLabel === 'string' && tickLabel.indexOf(' ') > -1){
                    var parts = tickLabel.split(' ');
                    var dateParts = parts[0].split('-');
                    if(dateParts.length === 3){
                        var day = dateParts[2];
                        var month = parseInt(dateParts[1], 10) - 1;
                        var monthNames = ["Jan","Feb","Mar","Apr","Mei","Jun","Jul","Agt","Sep","Okt","Nov","Des"];
                        return day + ' ' + monthNames[month];
                    }
                }
                return tickLabel;
            }
        })
    });
    return {
        type: sourceChart.config.type,
        data: {
            labels: sourceChart.data.labels,
            datasets: sourceChart.data.datasets.map(function(ds){
                return Object.assign({}, ds, { pointRadius: 0, pointHoverRadius: 6, borderWidth: 2 });
            })
        },
        options: baseOptions
    };
}

// Y-Axis Scale Controls
var _modalYOverride = null;   // {min, max} or null (auto)
function applyModalYScale(){
    if(!modalChart) return;
    var minEl = document.getElementById('modalYMin');
    var maxEl = document.getElementById('modalYMax');
    if(!minEl || !maxEl) return;
    var mmin = minEl.value === '' ? undefined : parseFloat(minEl.value);
    var mmax = maxEl.value === '' ? undefined : parseFloat(maxEl.value);
    _modalYOverride = {min: mmin, max: mmax};
    modalChart.options.scales.y ? (modalChart.options.scales.y.min = mmin, modalChart.options.scales.y.max = mmax) : null;
    if(modalChart.isEditable && modalChart.update) modalChart.update();
    else if(modalChart.update) modalChart.update();
}

function initYBar(chart){
    var bar = document.getElementById('modalYBar');
    var autoBtn = document.getElementById('modalYAutoBtn');
    var applyBtn = document.getElementById('modalYApplyBtn');
    var minIn = document.getElementById('modalYMin');
    var maxIn = document.getElementById('modalYMax');
    if(!bar) return;
    bar.classList.add('open');
    if(minIn) minIn.value = '';
    if(maxIn) maxIn.value = '';
    _modalYOverride = null;
    if(chart && chart.options && chart.options.scales && chart.options.scales.y){
        // Pre-fill with current auto scale from source chart (before modal override applied)
        var yOpts = chart.options.scales.y;
        if(minIn) minIn.placeholder = (yOpts.min !== undefined ? yOpts.min : 'Auto');
        if(maxIn) maxIn.placeholder = (yOpts.max !== undefined ? yOpts.max : 'Auto');
    }
    // Reset zoom on open
    if(chart && typeof chart.resetZoom === 'function') chart.resetZoom();
    // Attach enter-key on inputs
    [minIn, maxIn].forEach(function(inp){
        if(!inp) return;
        inp.onkeydown = function(e){ if(e.key === 'Enter') applyModalYScale(); };
        inp.style.opacity = '';
    });
}

function closeYBar(){
    var bar = document.getElementById('modalYBar');
    if(bar) bar.classList.remove('open');
}

function openChartModal(chartEl){
    var card = chartEl.closest('.card') || chartEl.closest('.dash-chart-card') || chartEl.closest('.chart-box') || chartEl.closest('.glass-card');
    if(!card) return;
    var title = card.querySelector('.card-title') || card.querySelector('.dash-chart-title') || card.querySelector('h3');
    var titleInput = card.querySelector('.chart-title-input');
    var titleText = title ? title.textContent.replace(/\s+/g, ' ').trim() : (titleInput ? titleInput.value.replace(/\s+/g, ' ').trim() : 'Chart Preview');
    var chartId = chartEl.id;
    if(!chartId || !chartInstances[chartId]) return;
    var sourceChart = chartInstances[chartId];
    var ctx = document.getElementById('modalChartCanvas');
    if(!ctx) return;

    if(modalChart) {
        modalChart.destroy();
        modalChart = null;
    }

    // Copy full datasets (needed for chart build)
    var fullDatasets = sourceChart.data.datasets.map(function(ds){
        return {
            label: ds.label,
            data: ds.data ? ds.data.slice() : [],
            borderColor: ds.borderColor,
            backgroundColor: ds.backgroundColor,
            hidden: ds.hidden || false,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 6,
            tension: typeof ds.tension !== 'undefined' ? ds.tension : 0.3,
            fill: ds.fill || false,
            yAxisID: ds.yAxisID || 'y'
        };
    });

    // Build modal config with full data (clip-path animation handles reveal)
    var config = buildModalConfig(sourceChart, titleText);
    config.data.labels = sourceChart.data.labels ? sourceChart.data.labels.slice() : [];
    config.data.datasets = fullDatasets;

    modalChart = new Chart(ctx, config);
    document.getElementById('modalTitle').textContent = titleText;
    document.getElementById('chartModalOverlay').classList.add('open');
    var scrollBarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.paddingRight = scrollBarWidth + 'px';
    document.body.style.overflow = 'hidden';
    // ── Custom draw animation: progressive reveal left-to-right using CSS clip-path ──
    // Start with 0% visible, ramp to 100% over 2s with easeOutQuart
    var drawStart = null;
    var drawDuration = 2000;   // ms
    var ease = function(t){ return 1 - Math.pow(1 - t, 4); };

    // Begin with chart hidden (clip-path at 0%)
    ctx.style.opacity = '0';

    function animateDraw(ts){
        if (!modalChart) return;
        if (!drawStart) drawStart = ts;
        var elapsed = ts - drawStart;
        var raw = Math.min(elapsed / drawDuration, 1);
        var pct = Math.round(ease(raw) * 100);
        // Reveal from left (0%) to right (100%) via inset clip
        ctx.style.clipPath = 'inset(0 ' + (100 - pct) + '% 0 0)';
        ctx.style.opacity = '1';
        if (raw < 1) {
            requestAnimationFrame(animateDraw);
        } else {
            // Animation done — remove clip, show full chart
            ctx.style.clipPath = 'none';
            ctx.style.opacity = '1';
        }
    }

    setTimeout(function(){
        if (modalChart) requestAnimationFrame(animateDraw);
    }, 120);  // let modal CSS transition finish first
}

function closeChartModal(){
    var overlay = document.getElementById('chartModalOverlay');
    if(!overlay) return;
    overlay.classList.remove('open');
    document.body.style.paddingRight = '';
    document.body.style.overflow = '';
    if(modalChart && typeof modalChart.resetZoom === 'function'){
        modalChart.resetZoom();
    }
}

function attachChartModalHandlers(){
    var closeBtn = document.getElementById('closeModalBtn');
    if(closeBtn) closeBtn.onclick = closeChartModal;

    var resetZoomBtn = document.getElementById('resetZoomBtn');
    if(resetZoomBtn) resetZoomBtn.onclick = function(){
        if(modalChart && typeof modalChart.resetZoom === 'function'){
            modalChart.resetZoom();
        }
    };

    var exportPngBtn = document.getElementById('exportPngBtn');
    if(exportPngBtn) exportPngBtn.onclick = downloadModalImage;

    var exportCsvBtn = document.getElementById('exportCsvBtn');
    if(exportCsvBtn) exportCsvBtn.onclick = downloadModalCSV;

    var overlay = document.getElementById('chartModalOverlay');
    if(overlay) overlay.onclick = function(e){
        if(e.target === overlay) closeChartModal();
    };
}

function downloadModalImage() {
    if(!modalChart) return;
    var titleText = document.getElementById('modalTitle').textContent || 'Chart';
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    
    var ratio = 1;
    if (modalChart.canvas.clientWidth > 0) {
        ratio = modalChart.canvas.width / modalChart.canvas.clientWidth;
    }
    
    var padTop = 50 * ratio;
    
    var tempCanvas = document.createElement('canvas');
    tempCanvas.width = modalChart.canvas.width;
    tempCanvas.height = modalChart.canvas.height + padTop;
    var ctx = tempCanvas.getContext('2d');
    
    ctx.fillStyle = isDark ? '#1a1a2e' : '#ffffff';
    ctx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
    
    ctx.fillStyle = isDark ? '#c8d0e0' : '#1e293b';
    ctx.font = 'bold ' + (16 * ratio) + 'px "Inter", "Segoe UI", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(titleText, tempCanvas.width / 2, 32 * ratio);
    
    ctx.drawImage(modalChart.canvas, 0, padTop);
    
    var a = document.createElement('a');
    a.href = tempCanvas.toDataURL('image/png');
    a.download = titleText + '.png';
    a.click();
}

function downloadModalCSV() {
    if(!modalChart) return;
    var labels = modalChart.data.labels;
    var visibleDatasets = modalChart.data.datasets.filter(function(ds) { return !ds.hidden; });
    var csvContent = "\uFEFFLabel";
    visibleDatasets.forEach(function(ds) { csvContent += "," + '"' + ds.label.replace(/"/g, '""') + '"'; });
    csvContent += "\r\n";
    for (var i = 0; i < labels.length; i++) {
        var row = ['"' + String(labels[i]).replace(/"/g, '""') + '"'];
        visibleDatasets.forEach(function(ds) {
            var val = ds.data[i];
            row.push((val !== null && val !== undefined) ? val : "");
        });
        csvContent += row.join(",") + "\r\n";
    }
    var blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var title = document.getElementById('modalTitle').textContent || 'Chart';
    a.download = title + '.csv';
    a.click();
    URL.revokeObjectURL(url);
}

document.addEventListener('DOMContentLoaded', attachChartModalHandlers);

/* ── CSV Download for Chart Data ── */
function downloadChartData(canvasId, filename){
    if(!chartInstances[canvasId]) return;
    var chart = chartInstances[canvasId];
    var labels = chart.data.labels || [];
    var datasets = chart.data.datasets || [];
    var headers = ["Timestamp"];
    datasets.forEach(function(ds){ headers.push(ds.label || "Series"); });
    var rows = [headers.join(",")];
    for(var i = 0; i < labels.length; i++){
        var row = [labels[i] || ""];
        datasets.forEach(function(ds){
            row.push(ds.data[i] !== undefined ? ds.data[i] : "");
        });
        rows.push(row.join(","));
    }
    var csvContent = rows.join("\n");
    var blob = new Blob(['\ufeff' + csvContent], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = (filename || canvasId) + ".csv";
    link.click();
    URL.revokeObjectURL(url);
}

/* ── Sub-menu accordion ── */
function toggleSub(id, el){
    var sub = document.getElementById(id);
    var isOpen = sub.classList.contains("open");
    /* Close all */
    document.querySelectorAll(".sub-menu").forEach(function(s){ s.classList.remove("open"); });
    document.querySelectorAll(".menu-item").forEach(function(m){ m.classList.remove("sub-open"); });
    if(!isOpen){ sub.classList.add("open"); el.classList.add("sub-open"); }
}

/* ── Multi-select helpers ── */
function msToggle(id){ document.getElementById(id).classList.toggle("open"); }
function msUpdateLabel(wrapId, inputName, placeholder){
    var checked = Array.from(document.querySelectorAll("[name='" + inputName + "']:checked")).map(function(b){ return b.value; });
    var label;
    if(checked.length === 0) label = placeholder || "Semua";
    else label = checked.slice(0,2).join(", ") + (checked.length > 2 ? " +" + (checked.length-2) : "");
    var btn = document.querySelector("[data-ms-btn='" + wrapId + "']");
    if(btn) btn.textContent = label;
}

/* ── Select All Checkboxes ── */
function toggleAllCheckboxes(containerId, selectAllCheckbox){
    var container = document.getElementById(containerId);
    var checkboxes = container.querySelectorAll("input[type='checkbox']");
    checkboxes.forEach(function(cb){ cb.checked = selectAllCheckbox.checked; });
}

/* ── Initialize on page load ── */
document.addEventListener("DOMContentLoaded", function(){
    setTimeout(function(){
        document.body.classList.remove("preload");
    }, 100);
    var settings = {};
    try { settings = JSON.parse(localStorage.getItem("appSettings") || "{}"); } catch(e){}
    
    setTimeout(function(){ 
        if(typeof updateAllChartsTheme === "function") updateAllChartsTheme();
    }, 150);
    
    // Auto-collapse bottom sheet accordions
    document.querySelectorAll('.bottom-sheet').forEach(function(sheet) {
        var accordions = sheet.querySelectorAll('details.bs-accordion');
        accordions.forEach(function(acc) {
            acc.addEventListener('toggle', function() {
                if (this.open) {
                    accordions.forEach(function(otherAcc) {
                        if (otherAcc !== acc) {
                            otherAcc.removeAttribute('open');
                        }
                    });
                }
            });
        });
    });
});

/* ── Mobile Bottom Sheets ── */
function openSheet(id){
    document.body.classList.add("bs-open");
    document.getElementById(id).classList.add("open");
}
function closeAllSheets(){
    document.body.classList.remove("bs-open");
    document.querySelectorAll(".bottom-sheet").forEach(function(s){ s.classList.remove("open"); });
}

/* ── Restore sidebar state ── */
(function(){
    if(localStorage.getItem("sidebarCollapsed")==="1"){
        var sb = document.getElementById("sidebar");
        if (sb) sb.classList.add("collapsed");
        var ic = document.getElementById("toggleIcon");
        if(ic) { ic.className = "fas fa-indent"; ic.style.transform = "rotate(0deg)"; }
        var txt = document.getElementById("toggleText");
        if(txt) txt.textContent = "Expand sidebar";
        var btn = document.getElementById("sidebarToggle");
        if(btn) btn.title = "Expand sidebar";
    }
})();

/* ── Auto-collapse sidebar on medium screens ── */
(function(){
    var mq = window.matchMedia("(min-width: 769px) and (max-width: 1024px)");
    function handleMediaChange(e){
        var sb = document.getElementById("sidebar");
        if(!sb || sb.classList.contains("mobile-hidden")) return;
        if(e.matches){
            sb.classList.add("collapsed");
            var ic = document.getElementById("toggleIcon");
            if(ic) { ic.className = "fas fa-indent"; ic.style.transform = "rotate(0deg)"; }
            var txt = document.getElementById("toggleText");
            if(txt) txt.textContent = "Expand sidebar";
        } else {
            if(localStorage.getItem("sidebarCollapsed") !== "1"){
                sb.classList.remove("collapsed");
                var ic = document.getElementById("toggleIcon");
                if(ic) { ic.className = "fas fa-outdent"; ic.style.transform = "rotate(0deg)"; }
                var txt = document.getElementById("toggleText");
                if(txt) txt.textContent = "Collapse sidebar";
            }
        }
        /* Re-render charts after layout change */
        setTimeout(function(){
            Object.values(chartInstances).forEach(function(ch){
                if(ch && typeof ch.resize === 'function'){ ch.resize(); ch.update(); }
            });
        }, 350);
    }
    if(mq.addEventListener){
        mq.addEventListener("change", handleMediaChange);
    }
    /* Apply on initial load */
    handleMediaChange(mq);
})();

/* ── Auto-detect mobile view ── */
(function(){
    var mqMobile = window.matchMedia("(max-width: 768px)");
    
    if(mqMobile.addEventListener){
        mqMobile.addEventListener("change", function(e){
            var settings = {};
            try { settings = JSON.parse(localStorage.getItem("appSettings") || "{}"); } catch(e){}
            if(!settings.viewMode) {
                applyViewMode(e.matches ? "mobile" : "desktop");
            }
        });
    }
    
    // Apply immediately on load
    var initSettings = {};
    try { initSettings = JSON.parse(localStorage.getItem("appSettings") || "{}"); } catch(e){}
    if(initSettings.viewMode) {
        applyViewMode(initSettings.viewMode);
    } else {
        applyViewMode(mqMobile.matches ? "mobile" : "desktop");
    }
})();

/* ── Mobile sidebar: auto-close when a nav link is clicked ── */
document.addEventListener("DOMContentLoaded", function(){
    document.querySelectorAll(".sidebar a").forEach(function(link){
        link.addEventListener("click", function(){
            if(document.body.classList.contains("mobile-view")){
                document.body.classList.remove("sidebar-drawer-open");
            }
        });
    });
});

/* ── Global Filter Panel Toggle (matches Dashboard 4G pattern) ── */
function toggleFilters() {
    var card = document.getElementById('filterContainer');
    var btn = document.getElementById('filterToggleBtn');
    if (!card || !btn) return;
    
    if (card.style.display === 'none') {
        card.style.display = '';
        btn.innerHTML = '<i class="fas fa-chevron-up"></i> Hide Filters';
    } else {
        card.style.display = 'none';
        btn.innerHTML = '<i class="fas fa-chevron-down"></i> Show Filters';
    }
}

/* ── Generic Table CSV Export ── */
function exportTableCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const quote = value => '"' + String(value ?? '').replace(/(\r\n|\n|\r)/gm, ' ').replace(/\s\s/g, ' ').trim().replace(/"/g, '""') + '"';
    let csv = [];
    const rows = table.querySelectorAll('tr');

    if (tableId === 'compareTable') {
        let currentGroup = '';
        let groupTitle = 'Group';
        let headerWritten = false;

        rows.forEach(rowEl => {
            const ths = rowEl.querySelectorAll('th');
            const tds = rowEl.querySelectorAll('td');
            const cells = rowEl.querySelectorAll('td, th');

            if (cells.length === 1 && cells[0].hasAttribute('colspan')) {
                const text = cells[0].innerText.replace(/(\r\n|\n|\r)/gm, ' ').trim();
                const parts = text.split(':');
                if (parts.length > 1) {
                    groupTitle = parts[0].trim();
                    currentGroup = parts.slice(1).join(':').trim();
                } else {
                    currentGroup = text;
                }
                return;
            }

            if (ths.length > 0 && !headerWritten) {
                let row = [quote(groupTitle)];
                ths.forEach(th => row.push(quote(th.innerText)));
                csv.push(row.join(','));
                headerWritten = true;
                return;
            }

            if (tds.length > 0) {
                let row = [quote(currentGroup)];
                tds.forEach(td => row.push(quote(td.innerText)));
                csv.push(row.join(','));
            }
        });
    } else {
        for (let i = 0; i < rows.length; i++) {
            let row = [], cols = rows[i].querySelectorAll('td, th');
            for (let j = 0; j < cols.length; j++) {
                let data = cols[j].innerText.replace(/(\r\n|\n|\r)/gm, ' ').replace(/"/g, '""');
                row.push('"' + data + '"');
            }
            csv.push(row.join(','));
        }
    }

    const blob = new Blob(['\ufeff' + csv.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename + '.csv';
    a.click();
    URL.revokeObjectURL(url);
}

/* ── Generic Table Filter ── */
function filterTable(tbodyId, searchTerm) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    const term = searchTerm.toLowerCase();
    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        if (text.indexOf(term) > -1) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}
