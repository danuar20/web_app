"""NetTilt 3D Routes — /nettilt3d"""
from flask import Blueprint, render_template, session, make_response
from ._utils import login_required, _no_cache

nettilt3d = Blueprint("nettilt3d", __name__)


@nettilt3d.route("/nettilt3d")
@login_required
def nettilt3d_page():
    """NetTilt 3D - Antenna Tilt Calculator & Visualizer"""
    return _no_cache(make_response(render_template(
        "nettilt3d.html",
        username=session["username"]
    )))
