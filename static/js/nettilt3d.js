(function() {
// Global variables
var map = null;
var siteMarker = null;
var sectorPolygons = [];
var streetLayer = null;
var satelliteLayer = null;
var scene, camera, renderer, antenna, beam;
var threeZoomFactor = 1.0;
var threeTheta = 0.8; // horizontal angle
var threePhi = 0.6;   // vertical angle
var isDragging = false;
var lastMouse = { x: 0, y: 0 };
var isDark = true;

// Current parameters
var params = {
    height: 30,
    mechTilt: 3,
    elecTilt: 6,
    azimuth: 0,
    hBeam: 65,
    vBeam: 10,
    lat: -6.2,
    lon: 106.8
};

// Initialize everything
document.addEventListener('DOMContentLoaded', function() {
    isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    initThreeJS();
    initLeaflet();
    updateAll();
    switchTab('mapTab');

    // Observe theme changes
    var themeObserver = new MutationObserver(function() {
        isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        updateSVG();
    });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
});

function resizeThreeCanvas() {
    if (!renderer || !camera) return;
    var canvas = document.getElementById('threeCanvas');
    var w = canvas.clientWidth || canvas.parentElement.clientWidth || 400;
    var h = canvas.clientHeight || 480;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
    renderThreeScene();
}

function renderThreeScene() {
    if (renderer && scene && camera) {
        renderer.render(scene, camera);
    }
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-content').forEach(function(content) {
        content.classList.toggle('active', content.id === tabId);
    });

    if (tabId === 'visualTab') {
        setTimeout(function() {
            resizeThreeCanvas();
            update3DView();
        }, 50);
    }
}

window.switchTab = switchTab;

function syncHeight() {
    var val = document.getElementById('heightNum').value;
    document.getElementById('heightRange').value = val;
    document.getElementById('hVal').textContent = val;
    updateAll();
}

window.syncHeight = syncHeight;

function syncAzimuth() {
    var val = document.getElementById('azimuthNum').value;
    document.getElementById('azimuthRange').value = val;
    document.getElementById('azVal').textContent = val;
    updateAll();
}

window.syncAzimuth = syncAzimuth;

function updateAll() {
    // Get values from inputs
    params.height = parseFloat(document.getElementById('heightRange').value);
    params.mechTilt = parseFloat(document.getElementById('mechTilt').value) || 0;
    params.elecTilt = parseFloat(document.getElementById('elecTilt').value) || 0;
    params.azimuth = parseFloat(document.getElementById('azimuthRange').value);
    params.hBeam = parseFloat(document.getElementById('hBeam').value) || 65;
    params.vBeam = parseFloat(document.getElementById('vBeam').value) || 10;
    params.lat = parseFloat(document.getElementById('latInput').value) || -6.2;
    params.lon = parseFloat(document.getElementById('lonInput').value) || 106.8;

    // Update labels
    document.getElementById('hVal').textContent = params.height;
    document.getElementById('azVal').textContent = params.azimuth;
    document.getElementById('heightNum').value = params.height;
    document.getElementById('azimuthNum').value = params.azimuth;

    // Calculate total tilt
    var totalTilt = params.mechTilt + params.elecTilt;
    document.getElementById('totalTilt').textContent = totalTilt.toFixed(1) + '°';

    // Calculate coverage distances
    var tiltRad = totalTilt * Math.PI / 180;
    var centerDist = params.height / Math.tan(tiltRad);
    var halfVBW = params.vBeam / 2;
    var nearDist = params.height / Math.tan((totalTilt + halfVBW) * Math.PI / 180);
    var farDist = params.height / Math.tan((totalTilt - halfVBW) * Math.PI / 180);

    // Update results
    document.getElementById('centerDist').textContent = centerDist.toFixed(0) + 'm';
    document.getElementById('nearDist').textContent = nearDist.toFixed(0) + 'm';
    document.getElementById('farDist').textContent = farDist.toFixed(0) + 'm';

    // Sector area
    var sectorArea = (params.hBeam / 360) * Math.PI * Math.pow(centerDist / 1000, 2);
    document.getElementById('sectorArea').textContent = sectorArea.toFixed(2) + 'km²';

    // Update status
    updateStatus(totalTilt);

    // Update visualizations
    update3DView();
    updateSVG();
    updateMapPolygon();
}

window.updateAll = updateAll;

// Update tilt status indicator
function updateStatus(totalTilt) {
    var dot = document.getElementById('statusDot');
    var text = document.getElementById('statusText');

    if (totalTilt >= 6 && totalTilt <= 12) {
        dot.className = 'status-dot optimal';
        text.textContent = 'Optimal Coverage';
    } else if (totalTilt < 6) {
        dot.className = 'status-dot warning';
        text.textContent = 'Under-Tilted';
    } else {
        dot.className = 'status-dot critical';
        text.textContent = 'Over-Tilted';
    }
}

// Initialize Three.js
function initThreeJS() {
    var canvas = document.getElementById('threeCanvas');
    scene = new THREE.Scene();

    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';

    // theme-aware background
    function applyThreeTheme() {
        var t = document.documentElement.getAttribute('data-theme') || 'dark';
        isDark = t !== 'light';
        if (isDark) {
            scene.background = new THREE.Color(0x0a1520);
        } else {
            scene.background = new THREE.Color(0xf0f4f8);
        }
        update3DView();
    }
    applyThreeTheme();

    camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);

    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(isDark ? 0x0a1520 : 0xf0f4f8);
    resizeThreeCanvas();

    var ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    var directionalLight = new THREE.DirectionalLight(0xffffff, 0.7);
    directionalLight.position.set(100, 200, 100);
    scene.add(directionalLight);

    // Tower - realistic proportions
    var towerHeight = 30;
    var towerGeo = new THREE.CylinderGeometry(0.5, 0.8, towerHeight, 8);
    var towerMat = new THREE.MeshPhongMaterial({ color: isDark ? 0x5a6a7a : 0x8899aa });
    var tower = new THREE.Mesh(towerGeo, towerMat);
    tower.position.y = towerHeight / 2;
    scene.add(tower);

    // Antenna panel
    var antennaGeo = new THREE.BoxGeometry(1.5, 10, 2);
    var antennaMat = new THREE.MeshPhongMaterial({ color: isDark ? 0x4facfe : 0x2563eb });
    antenna = new THREE.Mesh(antennaGeo, antennaMat);
    antenna.position.y = towerHeight + 3;
    scene.add(antenna);

    // Ground plane - large for distance visualization
    var groundGeo = new THREE.CircleGeometry(2000, 64);
    var groundMat = new THREE.MeshPhongMaterial({ color: isDark ? 0x1a2a3a : 0xe8eef4, transparent: true, opacity: 0.9 });
    var ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = 0;
    scene.add(ground);

    // Grid helper for scale reference
    var gridHelper = new THREE.GridHelper(2000, 20, isDark ? 0x2a3a4a : 0xc8d8e8, isDark ? 0x1a2a3a : 0xd8e8f0);
    scene.add(gridHelper);

    // Create beam group for dynamic updates
    beam = new THREE.Group();
    scene.add(beam);

    window.addEventListener('resize', resizeThreeCanvas);

    // Mouse / touch controls for rotation
    canvas.addEventListener('mousedown', function(e) {
        isDragging = true; lastMouse.x = e.clientX; lastMouse.y = e.clientY;
    });
    window.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        var dx = (e.clientX - lastMouse.x) * 0.005;
        var dy = (e.clientY - lastMouse.y) * 0.005;
        threeTheta -= dx; threePhi = Math.max(0.15, Math.min(1.3, threePhi - dy));
        lastMouse.x = e.clientX; lastMouse.y = e.clientY;
        update3DView();
    });
    window.addEventListener('mouseup', function() { isDragging = false; });
    // touch
    canvas.addEventListener('touchstart', function(e){ if(e.touches && e.touches[0]){ lastMouse.x = e.touches[0].clientX; lastMouse.y = e.touches[0].clientY; isDragging = true; } });
    canvas.addEventListener('touchmove', function(e){ if(!isDragging || !e.touches) return; var t = e.touches[0]; var dx = (t.clientX - lastMouse.x) * 0.005; var dy = (t.clientY - lastMouse.y) * 0.005; threeTheta -= dx; threePhi = Math.max(0.15, Math.min(1.3, threePhi - dy)); lastMouse.x = t.clientX; lastMouse.y = t.clientY; update3DView(); e.preventDefault(); }, {passive:false});
    canvas.addEventListener('touchend', function(){ isDragging = false; });

    // wheel to zoom
    canvas.addEventListener('wheel', function(e){ e.preventDefault(); var delta = e.deltaY > 0 ? 0.08 : -0.08; zoom3D(delta); }, {passive:false});

    // observe theme changes
    var mo = new MutationObserver(function(){ applyThreeTheme(); });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

// Update 3D view based on parameters
function update3DView() {
    if (!antenna || !beam || !camera) return;

    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';

    // Theme-aware colors
    var mainBeamColor = 0x4facfe;
    var centerBeamColor = 0x00f2fe;
    var coverageColor = 0x4facfe;
    var groundColor = isDark ? 0x1a2a3a : 0xe8eef4;
    var gridColor = isDark ? 0x2a3a4a : 0xc8d8e8;
    var towerColor = isDark ? 0x5a6a7a : 0x8899aa;

    var totalTilt = params.mechTilt + params.elecTilt;
    var tiltRad = -totalTilt * Math.PI / 180;
    var azRad = -params.azimuth * Math.PI / 180;

    // Rotate antenna based on tilt and azimuth
    antenna.rotation.z = tiltRad;
    antenna.rotation.y = azRad;
    antenna.material.color.setHex(towerColor);

    // Clear existing beam elements
    while(beam.children.length > 0) {
        beam.remove(beam.children[0]);
    }

    // Calculate coverage distances
    var tiltAngle = totalTilt * Math.PI / 180;
    var halfHBW = (params.hBeam / 2) * Math.PI / 180;
    var halfVBW = (params.vBeam / 2) * Math.PI / 180;

    // Center beam distance
    var centerDist = params.height / Math.tan(Math.abs(tiltAngle));
    // Far edge (upper beam)
    var farAngle = tiltAngle + halfVBW;
    var farDist = params.height / Math.tan(Math.abs(farAngle));
    // Near edge (lower beam)
    var nearAngle = tiltAngle - halfVBW;
    var nearDist = params.height / Math.tan(Math.abs(nearAngle));

    // Scale factor: 1 unit = 1 meter, scale for visualization
    var scale = 0.5;
    var towerTop = params.height;

    // Antenna position
    var antennaY = towerTop;

    // Create beam coverage visualization
    var beamGroup = beam;

    // Main beam cone (semi-transparent)
    var beamLength = farDist * scale;
    var beamWidth = beamLength * Math.tan(halfHBW) * 2;

    // Create beam using custom geometry for better visualization
    var beamGeo = new THREE.ConeGeometry(beamWidth / 2, beamLength, 32, 1, true);
    var beamMat = new THREE.MeshPhongMaterial({
        color: mainBeamColor,
        transparent: true,
        opacity: isDark ? 0.25 : 0.3,
        side: THREE.DoubleSide
    });
    var mainBeam = new THREE.Mesh(beamGeo, beamMat);
    // Position beam so it starts from antenna and points down/tilted
    mainBeam.position.y = antennaY - beamLength / 2;
    mainBeam.rotation.x = tiltAngle;
    beamGroup.add(mainBeam);

    // Inner beam (more visible center)
    var innerGeo = new THREE.ConeGeometry(beamWidth * 0.35, beamLength * 0.85, 32, 1, true);
    var innerMat = new THREE.MeshPhongMaterial({
        color: centerBeamColor,
        transparent: true,
        opacity: isDark ? 0.4 : 0.5,
        side: THREE.DoubleSide
    });
    var innerBeam = new THREE.Mesh(innerGeo, innerMat);
    innerBeam.position.y = antennaY - beamLength * 0.4;
    innerBeam.rotation.x = tiltAngle;
    beamGroup.add(innerBeam);

    // Ground coverage ellipse
    var ellipseGeo = new THREE.CircleGeometry(beamWidth / 2, 32);
    var ellipseMat = new THREE.MeshPhongMaterial({
        color: coverageColor,
        transparent: true,
        opacity: isDark ? 0.2 : 0.25,
        side: THREE.DoubleSide
    });
    var ellipse = new THREE.Mesh(ellipseGeo, ellipseMat);
    ellipse.rotation.x = -Math.PI / 2;
    ellipse.position.y = 0.2;
    ellipse.position.x = beamLength * Math.sin(tiltAngle);
    ellipse.position.z = -beamLength * Math.cos(tiltAngle);
    beamGroup.add(ellipse);

    // Distance markers
    var markerDistances = [100, 200, 500, 1000];
    var markerColor = isDark ? 0x4facfe : 0x2563eb;
    markerDistances.forEach(function(dist) {
        if (dist <= farDist * 1.3 && dist > 0) {
            var markerRadius = dist * scale * Math.tan(halfHBW);
            var markerY = 0.3;
            var markerX = dist * scale * Math.sin(tiltAngle);
            var markerZ = -dist * scale * Math.cos(tiltAngle);

            // Ring marker
            var ringGeo = new THREE.RingGeometry(Math.max(0.1, markerRadius - 3), markerRadius, 32);
            var ringMat = new THREE.MeshBasicMaterial({ color: markerColor, transparent: true, opacity: isDark ? 0.5 : 0.6, side: THREE.DoubleSide });
            var ring = new THREE.Mesh(ringGeo, ringMat);
            ring.rotation.x = -Math.PI / 2;
            ring.position.set(markerX, markerY, markerZ);
            beamGroup.add(ring);

            // Distance text marker (small box as visual placeholder)
            var labelGeo = new THREE.BoxGeometry(markerRadius * 0.15, 2, 2);
            var labelMat = new THREE.MeshBasicMaterial({ color: markerColor, transparent: true, opacity: 0.8 });
            var label = new THREE.Mesh(labelGeo, labelMat);
            label.position.set(markerX, 6, markerZ);
            beamGroup.add(label);
        }
    });

    // Apply rotations to entire beam group
    beamGroup.rotation.y = azRad;

    // Compute camera position from spherical coords
    var viewDist = Math.max(farDist * scale * 2.5, 500) * threeZoomFactor;
    var x = viewDist * Math.cos(threePhi) * Math.cos(threeTheta);
    var y = viewDist * Math.sin(threePhi) + towerTop * 0.5;
    var z = viewDist * Math.cos(threePhi) * Math.sin(threeTheta);
    camera.position.set(x, y, z);
    camera.lookAt(0, towerTop * 0.4, 0);

    // Update ground and grid colors
    scene.traverse(function(obj) {
        if (obj.geometry) {
            if (obj.geometry.type === 'CircleGeometry') {
                obj.material.color.setHex(groundColor);
            }
            if (obj.geometry.type === 'GridHelper') {
                obj.material.color.setHex(gridColor);
                obj.material.opacity = isDark ? 0.4 : 0.6;
            }
        }
    });

    renderThreeScene();
}

function zoom3D(delta) {
    threeZoomFactor = Math.min(2.0, Math.max(0.4, threeZoomFactor + delta));
    update3DView();
    resizeThreeCanvas();
}

window.zoom3D = zoom3D;

function reset3DView() {
    threeZoomFactor = 1.0;
    threeTheta = 0.8;
    threePhi = 0.6;
    update3DView();
    resizeThreeCanvas();
}

window.reset3DView = reset3DView;

// Initialize Leaflet map
function initLeaflet() {
    var mapContainer = document.getElementById('leafletMap');
    map = L.map(mapContainer).setView([params.lat, params.lon], 15);

    streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 19
    });

    satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: '© Esri',
        maxZoom: 19
    });

    streetLayer.addTo(map);

    // Add site marker
    var towerIcon = L.divIcon({
        html: '<div style="background:#ff8c00;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.5);"><i class="fas fa-broadcast-tower" style="color:#000;font-size:12px;"></i></div>',
        className: '',
        iconSize: [24, 24],
        iconAnchor: [12, 12]
    });

    siteMarker = L.marker([params.lat, params.lon], { icon: towerIcon }).addTo(map)
        .bindPopup('<b>' + escapeXML(document.getElementById('siteName').value) + '</b><br>H: ' + params.height + 'm<br>Tilt: ' + (params.mechTilt + params.elecTilt) + '°');
        
    // Use ResizeObserver for Map to handle tab switching
    if (window.ResizeObserver) {
        var resizeObserver = new ResizeObserver(function() {
            if (map) {
                map.invalidateSize();
                if (sectorPolygons.length > 0 && document.getElementById('mapTab').classList.contains('active')) {
                    var group = new L.featureGroup(sectorPolygons);
                    map.fitBounds(group.getBounds(), { padding: [30, 30] });
                }
            }
        });
        resizeObserver.observe(mapContainer);
    }
}

function setBaseLayer(type) {
    if (!map) return;

    // Update button states
    document.getElementById('btnStreetMap').classList.toggle('active', type === 'street');
    document.getElementById('btnSatellite').classList.toggle('active', type === 'satellite');

    if (type === 'street') {
        if (map.hasLayer(satelliteLayer)) {
            map.removeLayer(satelliteLayer);
        }
        streetLayer.addTo(map);
    } else {
        if (map.hasLayer(streetLayer)) {
            map.removeLayer(streetLayer);
        }
        satelliteLayer.addTo(map);
    }
}

window.setBaseLayer = setBaseLayer;

// Update map polygon
function updateMapPolygon() {
    if (!map) return;

    // Remove existing polygons
    sectorPolygons.forEach(function(p) {
        map.removeLayer(p);
    });
    sectorPolygons = [];

    var totalTilt = params.mechTilt + params.elecTilt;
    var halfVBW = params.vBeam / 2;
    var tiltRad = totalTilt * Math.PI / 180;
    
    var centerDist = params.height / Math.tan(tiltRad);
    var nearDist = params.height / Math.tan((totalTilt + halfVBW) * Math.PI / 180);
    var farDist = params.height / Math.tan((totalTilt - halfVBW) * Math.PI / 180);

    // Read checkboxes
    var showNear = document.getElementById('chkNear') ? document.getElementById('chkNear').checked : false;
    var showCenter = document.getElementById('chkCenter') ? document.getElementById('chkCenter').checked : true;
    var showFar = document.getElementById('chkFar') ? document.getElementById('chkFar').checked : false;

    // Helper to add polygon
    function addPoly(dist, color) {
        if (dist > 0 && dist < 50000) { // sanity check
            var coords = generateSectorCoords(dist);
            var p = L.polygon(coords, {
                color: color,
                fillColor: color,
                fillOpacity: 0.3,
                weight: 2
            }).addTo(map);
            sectorPolygons.push(p);
        }
    }

    if (showFar) addPoly(farDist, '#ff5555');
    if (showCenter) addPoly(centerDist, '#4facfe');
    if (showNear) addPoly(nearDist, '#00c853');

    // Fit map to polygons if the tab is visible
    if (sectorPolygons.length > 0 && document.getElementById('mapTab').classList.contains('active')) {
        var group = new L.featureGroup(sectorPolygons);
        map.fitBounds(group.getBounds());
    }

    // Update marker position
    siteMarker.setLatLng([params.lat, params.lon]);
    siteMarker.setPopupContent('<b>' + escapeXML(document.getElementById('siteName').value) + '</b><br>H: ' + params.height + 'm<br>Tilt: ' + totalTilt.toFixed(1) + '°<br>Azimuth: ' + params.azimuth + '°');
}

window.updateMapPolygon = updateMapPolygon;

// Expose updateMap for HTML onclick
window.updateMap = updateAll;

// Generate sector polygon coordinates
function generateSectorCoords(distance) {
    var lat = params.lat;
    var lon = params.lon;
    var az = params.azimuth;
    var hbw = params.hBeam / 2;

    // Approximate degrees per meter
    var latDegPerM = 1 / 111000;
    var lonDegPerM = 1 / (111000 * Math.cos(lat * Math.PI / 180));

    var coords = [[lat, lon]];
    var numPoints = 36;
    var startAz = az - hbw;
    var endAz = az + hbw;
    var step = (endAz - startAz) / numPoints;

    for (var i = 0; i <= numPoints; i++) {
        var a = (startAz + i * step) * Math.PI / 180;
        var dlat = distance * Math.cos(a) * latDegPerM;
        var dlon = distance * Math.sin(a) * lonDegPerM;
        coords.push([lat + dlat, lon + dlon]);
    }

    coords.push([lat, lon]);
    return coords;
}

// Update SVG sector diagram
function updateSVG() {
    var svg = document.getElementById('sectorSvg');
    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    var cx = 150, cy = 140;
    var maxR = 110;
    var hbw = params.hBeam / 2;
    var totalTilt = params.mechTilt + params.elecTilt;

    // Theme-aware colors
    var gridColor = isDark ? '#334455' : '#c0c8d0';
    var textColor = isDark ? '#cfe8ff' : '#1e293b';
    var markerColor = '#4facfe';
    var arrowColor = '#ff8c00';

    // Determine coverage color based on tilt status
    var coverColor = totalTilt >= 6 && totalTilt <= 12 ? '#22c55e' : (totalTilt < 6 ? '#facc15' : '#ef4444');

    // Calculate distances
    var tiltRad = totalTilt * Math.PI / 180;
    var centerDist = params.height / Math.tan(Math.abs(tiltRad));
    var scale = maxR / Math.max(centerDist, 100);

    var centerR = Math.min(centerDist * scale, maxR);
    var hbwRad = hbw * Math.PI / 180;
    var startAngle = -Math.PI / 2 - hbwRad;
    var endAngle = -Math.PI / 2 + hbwRad;

    // Build sector path
    var pathD = 'M ' + cx + ' ' + cy;
    pathD += ' L ' + (cx + centerR * Math.cos(startAngle)) + ' ' + (cy + centerR * Math.sin(startAngle));
    pathD += ' A ' + centerR + ' ' + centerR + ' 0 0 1 ' + (cx + centerR * Math.cos(endAngle)) + ' ' + (cy + centerR * Math.sin(endAngle));
    pathD += ' Z';

    // Distance marker positions
    var distMarkers = [];
    [50, 100, 200, 500].forEach(function(d) {
        var r = d * scale;
        if (r <= maxR && d <= centerDist * 1.2) {
            distMarkers.push({dist: d, r: r});
        }
    });

    var distMarkersSvg = distMarkers.map(function(m) {
        return '<circle cx="' + cx + '" cy="' + cy + '" r="' + m.r + '" fill="none" stroke="' + gridColor + '" stroke-width="1" stroke-dasharray="3"/>';
    }).join('');

    svg.innerHTML = `
        <!-- Grid circles -->
        ${distMarkersSvg}
        <circle cx="${cx}" cy="${cy}" r="${maxR}" fill="none" stroke="${gridColor}" stroke-width="1" stroke-dasharray="4"/>

        <!-- Coverage sector -->
        <path d="${pathD}" fill="${coverColor}" fill-opacity="0.35" stroke="${coverColor}" stroke-width="2"/>

        <!-- Site marker -->
        <circle cx="${cx}" cy="${cy}" r="8" fill="${markerColor}" stroke="#fff" stroke-width="2"/>

        <!-- Direction arrow -->
        <line x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy - 25}" stroke="${arrowColor}" stroke-width="3" stroke-linecap="round"/>
        <polygon points="${cx},${cy - 35} ${cx - 5},${cy - 25} ${cx + 5},${cy - 25}" fill="${arrowColor}"/>

        <!-- Distance label -->
        <text x="${cx + 10}" y="${cy - centerR + 15}" fill="${textColor}" font-size="10" font-weight="600">${centerDist.toFixed(0)}m</text>

        <!-- HBW label -->
        <text x="${cx}" y="${cy + maxR + 18}" fill="${textColor}" font-size="9" text-anchor="middle">HBW: ${params.hBeam}°</text>

        <!-- Title -->
        <text x="${cx}" y="15" fill="${textColor}" font-size="9" text-anchor="middle" font-weight="600">Sector Footprint</text>
    `;
}

function escapeXML(unsafe) {
    return String(unsafe).replace(/[<>&'"]/g, function (c) {
        switch (c) {
            case '<': return '&lt;';
            case '>': return '&gt;';
            case '&': return '&amp;';
            case '\'': return '&apos;';
            case '"': return '&quot;';
            default: return c;
        }
    });
}

// Export KML
function exportKML() {
    var rawSiteName = document.getElementById('siteName').value || 'Site_001';
    var siteName = escapeXML(rawSiteName);
    var lat = params.lat;
    var lon = params.lon;
    var height = params.height;
    var az = params.azimuth;
    var totalTilt = params.mechTilt + params.elecTilt;
    var hbw = params.hBeam;
    var halfVBW = params.vBeam / 2;
    
    var centerDist = height / Math.tan(totalTilt * Math.PI / 180);
    var nearDist = height / Math.tan((totalTilt + halfVBW) * Math.PI / 180);
    var farDist = height / Math.tan((totalTilt - halfVBW) * Math.PI / 180);

    // Generate coordinate strings
    function getCoordsStr(dist) {
        if (dist <= 0 || dist > 50000) return "";
        var coords = generateSectorCoords(dist);
        return coords.map(function(c) { return c[1] + ',' + c[0] + ',0'; }).join(' ');
    }

    var centerStr = getCoordsStr(centerDist);
    var nearStr = getCoordsStr(nearDist);
    var farStr = getCoordsStr(farDist);

    // Colors: KML uses AABBGGRR format
    var styleFar = '<Style id="styleFar"><LineStyle><color>ff5555ff</color><width>2</width></LineStyle><PolyStyle><color>4d5555ff</color><fill>1</fill></PolyStyle></Style>';
    var styleCenter = '<Style id="styleCenter"><LineStyle><color>fffeac4f</color><width>2</width></LineStyle><PolyStyle><color>4dfeac4f</color><fill>1</fill></PolyStyle></Style>';
    var styleNear = '<Style id="styleNear"><LineStyle><color>ff53c800</color><width>2</width></LineStyle><PolyStyle><color>4d53c800</color><fill>1</fill></PolyStyle></Style>';

    var kml = '<?xml version="1.0" encoding="UTF-8"?>\n' +
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n' +
        '  <Document>\n' +
        '    <name>' + siteName + ' - NetTilt 3D</name>\n' +
        styleFar + '\n' + styleCenter + '\n' + styleNear + '\n' +
        '    <Folder>\n' +
        '      <name>Site: ' + siteName + '</name>\n' +
        '      <Placemark>\n' +
        '        <name>' + siteName + '</name>\n' +
        '        <description>Antenna Parameters: Height=' + height + 'm, Tilt=' + totalTilt.toFixed(1) + '°, Azimuth=' + az + '°, HBW=' + hbw + '°</description>\n' +
        '        <Point><coordinates>' + lon + ',' + lat + ',0</coordinates></Point>\n' +
        '      </Placemark>\n';
        
    if (farStr) {
        kml += '      <Placemark>\n' +
               '        <name>Far Edge Coverage</name>\n' +
               '        <styleUrl>#styleFar</styleUrl>\n' +
               '        <Polygon><outerBoundaryIs><LinearRing><coordinates>' + farStr + '</coordinates></LinearRing></outerBoundaryIs></Polygon>\n' +
               '      </Placemark>\n';
    }
    if (centerStr) {
        kml += '      <Placemark>\n' +
               '        <name>Center Coverage</name>\n' +
               '        <styleUrl>#styleCenter</styleUrl>\n' +
               '        <Polygon><outerBoundaryIs><LinearRing><coordinates>' + centerStr + '</coordinates></LinearRing></outerBoundaryIs></Polygon>\n' +
               '      </Placemark>\n';
    }
    if (nearStr) {
        kml += '      <Placemark>\n' +
               '        <name>Near Edge Coverage</name>\n' +
               '        <styleUrl>#styleNear</styleUrl>\n' +
               '        <Polygon><outerBoundaryIs><LinearRing><coordinates>' + nearStr + '</coordinates></LinearRing></outerBoundaryIs></Polygon>\n' +
               '      </Placemark>\n';
    }

    kml += '    </Folder>\n' +
        '  </Document>\n' +
        '</kml>';

    var blob = new Blob([kml], { type: 'application/vnd.google-earth.kml+xml' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'NetTilt3D_export.kml';
    a.click();
    URL.revokeObjectURL(url);
}

window.exportKML = exportKML;

})();
