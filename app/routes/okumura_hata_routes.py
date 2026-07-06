"""Okumura-Hata Model Routes — /okumura_hata"""
from flask import Blueprint, render_template, request, session, make_response
from ._utils import login_required, _no_cache, db_query
import math

okumura_hata = Blueprint("okumura_hata", __name__)


def calculate_okumura_hata(frequency_mhz, hb, hm, env_type):
    """
    Okumura-Hata propagation model

    Parameters:
    - frequency_mhz: Frequency in MHz (150-1500)
    - hb: Base station antenna height (m)
    - hm: Mobile station antenna height (m)
    - env_type: 'urban', 'suburban', or 'rural'

    Returns path loss at1 km and model constants
    """
    # Okumura-Hata works for:
    # f: 150-1500 MHz
    # hb: 30-200 m
    # hm: 1-10 m
    # d: 1-20 km

    a_hm = (1.1 * math.log10(frequency_mhz) - 0.7) * hm - (1.56 * math.log10(frequency_mhz) - 0.8)

    if env_type == "urban":
        # Large city
        if frequency_mhz <= 300:
            a_hm = 8.29 * (math.log10(1.54 * frequency_mhz) ** 2) - 1.1
        else:
            a_hm = 3.2 * (math.log10(11.75 * hm) ** 2) - 4.97
        # Path loss
        L_u = 69.55 + 26.16 * math.log10(frequency_mhz) - 13.82 * math.log10(hb) - a_hm
        L_1km = L_u + 26.16 * math.log10(frequency_mhz) - 65.55  # Simplified PL at 1km
        confidence =0.85
        env_label = "Urban"
    elif env_type == "suburban":
        L_u = 69.55 + 26.16 * math.log10(frequency_mhz) - 13.82 * math.log10(hb) - a_hm
        L_sub = L_u - 2 * (math.log10(frequency_mhz / 28) ** 2) - 5.4
        L_1km = L_sub + 26.16 * math.log10(frequency_mhz) - 65.55
        confidence = 0.80
        env_label = "Suburban"
    else:  # rural
        L_u = 69.55 + 26.16 * math.log10(frequency_mhz) - 13.82 * math.log10(hb) - a_hm
        L_rur = L_u - 4.78 * (math.log10(frequency_mhz) ** 2) + 18.33 * math.log10(frequency_mhz) - 40.94
        L_1km = L_rur + 26.16 * math.log10(frequency_mhz) - 65.55
        confidence = 0.75
        env_label = "Rural"

    return {
        "pl_1km": L_1km,
        "a_hm": a_hm,
        "confidence": confidence,
        "env_label": env_label
    }


def calculate_coverage(frequency_mhz, hb, hm, tx_power_dbm, gain_dbi,
                       elec_tilt, mech_tilt, v_beamwidth, h_beamwidth,
                       rx_sensitivity, cable_loss, env_type):
    """
    Calculate complete coverage parameters using Okumura-Hata model
    """
    total_tilt = elec_tilt + mech_tilt
    total_tilt_rad = math.radians(total_tilt)

    # EIRP = TX Power + Gain - Cable Loss
    eirp = tx_power_dbm + gain_dbi - cable_loss

    # Max allowable path loss = EIRP - RX Sensitivity
    max_pl = eirp - rx_sensitivity

    # Get Okumura-Hata parameters
    oh = calculate_okumura_hata(frequency_mhz, hb, hm, env_type)
    pl_1km = oh["pl_1km"]

    # Coverage radius from max allowable path loss
    # L = pl_1km + 42.5*log10(d_km) for COST-231 variant, simplified:
    # d = 10^((max_pl - pl_1km) / (42.5 + 26*log10(f)))
    # Using standard Okumura-Hata: d = 10^((max_pl - L_1km) / (35.2))
    exponent = (max_pl - pl_1km) / 35.2
    coverage_radius_km = 10 ** exponent if exponent > 0 else 0.1

    # Boresight distance (from tilt)
    if abs(total_tilt) > 0.5:
        boresight_dist = hb / math.tan(abs(total_tilt_rad))
    else:
        boresight_dist = coverage_radius_km * 1000

    # Vertical beam edges: define near (upper) and far (lower) consistently
    half_vbw = v_beamwidth / 2
    # Near edge angle = total_tilt + half_vbw (upper beam edge — larger angle -> closer)
    near_angle = total_tilt + half_vbw
    if near_angle > 0 and near_angle < 90:
        near_dist = hb / math.tan(math.radians(near_angle))
    elif near_angle >= 90:
        # beam points almost straight down; near edge effectively at antenna
        near_dist = 0
    else:
        near_dist = boresight_dist * 0.5

    # Far edge angle = abs(total_tilt) - half_vbw (lower beam edge — smaller angle -> farther)
    far_angle = abs(total_tilt) - half_vbw
    if far_angle > 0:
        far_dist = hb / math.tan(math.radians(far_angle))
    else:
        # very far if beam near-horizontal
        far_dist = boresight_dist * 1000

    # Sector area (approximate, in km²)
    # Area ≈ (HBW/360) * π * r²
    half_hbw = h_beamwidth / 2
    sector_fraction = h_beamwidth / 360.0
    sector_area = sector_fraction * math.pi * (coverage_radius_km ** 2)

    # Three zones (for visualization)
    near_radius_m = min(near_dist, coverage_radius_km * 1000)
    boresight_radius_m = min(boresight_dist, coverage_radius_km * 1000)
    far_radius_m = min(far_dist, coverage_radius_km * 1000)

    return {
        "eirp": round(eirp, 2),
        "max_pl": round(max_pl, 2),
        "coverage_radius_km": round(coverage_radius_km, 3),
        "sector_area_km2": round(sector_area, 3),
        "total_tilt": round(total_tilt, 2),
        "boresight_distance_m": round(boresight_dist, 2),
        "near_distance_m": round(near_dist, 2),
        "far_distance_m": round(far_dist, 2),
        "near_radius_m": round(near_radius_m, 2),
        "boresight_radius_m": round(boresight_radius_m, 2),
        "far_radius_m": round(far_radius_m, 2),
        "pl_1km": round(pl_1km, 2),
        "confidence": oh["confidence"],
        "env_label": oh["env_label"],
        "valid": True
    }


@okumura_hata.route("/okumura_hata")
@login_required
def okumura_hata_page():
    """Okumura-Hata Model page"""
    # Default values
    frequency = request.args.get("frequency", type=float, default=2100)
    hb = request.args.get("hb", type=float, default=30.0)
    gain = request.args.get("gain", type=float, default=18.0)
    tx_power = request.args.get("tx_power", type=float, default=43.0)
    elec_tilt = request.args.get("elec_tilt", type=float, default=6.0)
    mech_tilt = request.args.get("mech_tilt", type=float, default=3.0)
    v_beamwidth = request.args.get("v_beamwidth", type=float, default=10.0)
    h_beamwidth = request.args.get("h_beamwidth", type=float, default=65.0)
    env_type = request.args.get("env_type", default="urban")
    hm = request.args.get("hm", type=float, default=1.5)
    rx_sensitivity = request.args.get("rx_sensitivity", type=float, default=-102.0)
    cable_loss = request.args.get("cable_loss", type=float, default=2.0)

    # Calculate coverage
    results = calculate_coverage(
        frequency_mhz=frequency,
        hb=hb,
        hm=hm,
        tx_power_dbm=tx_power,
        gain_dbi=gain,
        elec_tilt=elec_tilt,
        mech_tilt=mech_tilt,
        v_beamwidth=v_beamwidth,
        h_beamwidth=h_beamwidth,
        rx_sensitivity=rx_sensitivity,
        cable_loss=cable_loss,
        env_type=env_type
    )

    return _no_cache(make_response(render_template(
        "okumura_hata.html",
        username=session["username"],
        frequency=frequency,
        hb=hb,
        gain=gain,
        tx_power=tx_power,
        elec_tilt=elec_tilt,
        mech_tilt=mech_tilt,
        v_beamwidth=v_beamwidth,
        h_beamwidth=h_beamwidth,
        env_type=env_type,
        hm=hm,
        rx_sensitivity=rx_sensitivity,
        cable_loss=cable_loss,
        results=results
    )))
