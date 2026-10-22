"""PPTX export endpoint for the Dashboard 4G chart export modal.

The browser captures each selected chart from its Chart.js canvas and posts the
PNG data URLs as JSON (see ``exportPptxReport`` in templates/dashboard_4g.html).
This module owns transport concerns only — limits, auth, CSRF, error codes —
while ``app.services.dashboard_pptx`` builds the actual deck.
"""
from __future__ import annotations

import io
import logging
import os
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

from app.routes._utils import login_required
from app.services.dashboard_pptx import (
    PayloadError,
    build_dashboard_pptx,
)

dashboard_pptx = Blueprint("dashboard_pptx", __name__)
logger = logging.getLogger(__name__)

PPTX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
# base64 inflates images by ~4/3; leave headroom for the JSON envelope
MAX_REQUEST_BYTES = 52 * 1024 * 1024


@dashboard_pptx.route("/api/dashboard_4g/export-pptx-templates", methods=["GET"])
@login_required
def get_dashboard_4g_pptx_templates():
    """List available PPTX templates for the export modal."""
    templates = [
        {
            "id": "infra_2026",
            "name": "Infra 2026",
            "description": "Standard corporate Network Benchmarking presentation layout (16:9)",
            "is_default": True
        },
        {
            "id": "fb_share",
            "name": "FB Share Reference",
            "description": "Crowdsource FB Share benchmarking layout",
            "is_default": False
        }
    ]
    return jsonify({"status": "success", "templates": templates})


@dashboard_pptx.route("/api/dashboard_4g/export-pptx", methods=["POST"])
@login_required
def export_dashboard_4g_pptx():
    """Render the selected Dashboard 4G charts into a multi-slide PPTX."""
    declared = request.content_length or 0
    if declared > MAX_REQUEST_BYTES:
        return jsonify({
            "status": "error",
            "message": (
                f"Export payload is {declared / 1048576:.1f} MB; limit is "
                f"{MAX_REQUEST_BYTES // 1048576} MB. Deselect some charts or "
                "lower the export resolution."
            ),
        }), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "message": "Expected a JSON body with the captured chart images",
        }), 400

    try:
        template_choice = str(payload.get("template") or "infra_2026").lower().strip()
        custom_path = None
        if template_choice in ("fb_share", "fb"):
            custom_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "resources", "report_templates", "fb_share.pptx",
            )
        elif template_choice in ("infra_2026", "infra"):
            custom_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "resources", "report_templates", "infra_2026.pptx",
            )
        blob, meta = build_dashboard_pptx(payload, template_path=custom_path)
    except PayloadError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        logger.exception("Error rendering Dashboard 4G PPTX export")
        return jsonify({
            "status": "error",
            "message": "Failed to render the PowerPoint export",
        }), 500

    section = re.sub(r"[^a-z0-9]+", "_", str(payload.get("section") or "kpi").lower())
    section = section.strip("_")[:40] or "kpi"
    filename = f"dashboard_4g_{section}_{datetime.now():%Y%m%d_%H%M}.pptx"
    response = send_file(
        io.BytesIO(blob),
        mimetype=PPTX_MIMETYPE,
        as_attachment=True,
        download_name=filename,
    )
    response.headers["X-Pptx-Charts"] = str(meta["charts"])
    response.headers["X-Pptx-Slides"] = str(meta["slides"])
    return response
