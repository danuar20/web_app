"""Coverage Simulation Routes — /coverage_simulation"""
from flask import Blueprint, render_template, request, session, make_response
from ._utils import login_required, _no_cache, json_response, db_query
import math

coverage = Blueprint("coverage", __name__)


def deg_to_rad(deg):
    """Convert degrees to radians"""
    return deg * math.pi / 180


def calculate_coverage(antenna_height, mechanical_tilt, electrical_tilt,
                       v_beamwidth, h_beamwidth, frequency=None, elevation=None):
    """
    Calculate RF antenna coverage parameters

    Parameters:
    - antenna_height: Height in meters
    - mechanical_tilt: Mechanical tilt in degrees
    - electrical_tilt: Electrical tilt in degrees
    - v_beamwidth: Vertical beamwidth in degrees
    - h_beamwidth: Horizontal beamwidth in degrees
    - frequency: Optional frequency in MHz
    - elevation: Optional site ground elevation in meters

    Returns dict with calculated values
    """
    results = {
        "total_tilt": 0,
        "near_distance": 0,
        "center_distance": 0,
        "far_distance": 0,
        "coverage_width": 0,
        "coverage_area": 0,
        "valid": True,
        "error": None
    }

    try:
        # Validate inputs
        if antenna_height <= 0:
            results["valid"] = False
            results["error"] = "Antenna height must be greater than 0"
            return results

        if mechanical_tilt < -90 or mechanical_tilt > 90:
            results["valid"] = False
            results["error"] = "Mechanical tilt must be between -90 and 90 degrees"
            return results

        if electrical_tilt < -90 or electrical_tilt > 90:
            results["valid"] = False
            results["error"] = "Electrical tilt must be between -90 and 90 degrees"
            return results

        # Calculate total tilt
        total_tilt = mechanical_tilt + electrical_tilt
        results["total_tilt"] = round(total_tilt, 2)

        # Handle edge case where tilt is 0 (beam points horizontally)
        if abs(total_tilt) < 0.001:
            results["valid"] = False
            results["error"] = "Total tilt cannot be 0 degrees"
            return results

        # Convert to radians for calculations
        total_tilt_rad = deg_to_rad(total_tilt)
        half_v_beam = v_beamwidth / 2
        half_h_beam = h_beamwidth / 2

        # Calculate distances using trigonometry
        # D = H / tan(theta)
        h = antenna_height

        # Center distance (beam center reaches ground)
        if abs(total_tilt) > 0.01 and abs(total_tilt) < 89:
            results["center_distance"] = round(h / math.tan(abs(total_tilt_rad)), 2)
        elif abs(total_tilt) >= 89:
            results["center_distance"] = round(h / math.tan(deg_to_rad(89)), 2)

        # Near edge distance (upper beam edge reaches ground)
        near_angle = total_tilt + half_v_beam
        if near_angle > 0 and near_angle < 90:
            results["near_distance"] = round(h / math.tan(deg_to_rad(near_angle)), 2)
        elif near_angle >= 90:
            results["near_distance"] = 0  # Beam points downward, near edge is right at antenna
        else:
            results["near_distance"] = 0

        # Far edge distance (lower beam edge reaches ground)
        far_angle = abs(total_tilt) - half_v_beam
        if far_angle > 0:
            results["far_distance"] = round(h / math.tan(deg_to_rad(far_angle)), 2)
        else:
            results["far_distance"] = round(h / math.tan(deg_to_rad(0.1)), 2)  # Very far if nearly horizontal

        # Coverage width at far edge (horizontal)
        # Width = 2 * far_distance * tan(half horizontal beamwidth)
        results["coverage_width"] = round(2 * results["far_distance"] * math.tan(deg_to_rad(half_h_beam)), 2)

        # Coverage area estimate (assuming sector shape)
        # Approximate as: average_width * depth
        avg_width = 2 * results["center_distance"] * math.tan(deg_to_rad(half_h_beam)) if results["center_distance"] > 0 else 0
        depth = results["far_distance"] - results["near_distance"]
        results["coverage_area"] = round((results["coverage_width"] + avg_width) / 2 * depth / 10000, 2)  # Convert to hectares

    except Exception as e:
        results["valid"] = False
        results["error"] = str(e)

    return results


@coverage.route("/coverage_simulation")
def coverage_simulation():
    """Coverage Simulation page"""
    # Get parameters from request
    antenna_height = request.args.get("antenna_height", type=float)
    mechanical_tilt = request.args.get("mechanical_tilt", type=float)
    electrical_tilt = request.args.get("electrical_tilt", type=float)
    v_beamwidth = request.args.get("v_beamwidth", type=float)
    h_beamwidth = request.args.get("h_beamwidth", type=float)
    frequency = request.args.get("frequency", type=float)
    elevation = request.args.get("elevation", type=float)

    # Basic dev bypass: allow ?dev=1 to view without login for local testing
    from flask import redirect, url_for
    if "username" not in session and request.args.get('dev') != '1':
        return redirect(url_for('auth.login'))
    # if dev flag present, create a temporary session username for templates
    if "username" not in session and request.args.get('dev') == '1':
        session['username'] = 'dev'

    # Default values
    if antenna_height is None:
        antenna_height = 30.0
    if mechanical_tilt is None:
        mechanical_tilt = 3.0
    if electrical_tilt is None:
        electrical_tilt = 6.0
    if v_beamwidth is None:
        v_beamwidth = 10.0
    if h_beamwidth is None:
        h_beamwidth = 65.0

    # Calculate coverage
    results = calculate_coverage(
        antenna_height=antenna_height,
        mechanical_tilt=mechanical_tilt,
        electrical_tilt=electrical_tilt,
        v_beamwidth=v_beamwidth,
        h_beamwidth=h_beamwidth,
        frequency=frequency,
        elevation=elevation
    )

    return _no_cache(make_response(render_template(
        "coverage_simulation.html",
        username=session.get("username", "dev"),
        antenna_height=antenna_height,
        mechanical_tilt=mechanical_tilt,
        electrical_tilt=electrical_tilt,
        v_beamwidth=v_beamwidth,
        h_beamwidth=h_beamwidth,
        frequency=frequency,
        elevation=elevation,
        results=results
    )))