"""PowerPoint export for the Crowdsource FB Share report.

Assembles the weekly report payload from the same builders the dashboard API uses
(``build_fb_share_compare`` / ``build_fb_share_trend``) and renders it through the
``fb_share.pptx`` template kept in ``app/resources/report_templates``.

Comparison weeks follow the dashboard rule: when the nominal WoW / MoM / YoY week
carries no data (blank upload), the closest earlier week with data is used instead.
"""
from __future__ import annotations

import io
import os

from flask import Blueprint, jsonify, request, send_file

from app.routes._utils import db_query, login_required
from app.routes.sow_routes import (
    _fb_ref_yearweek,
    build_fb_share_compare,
    build_fb_share_trend,
    get_cached_fb_yearweeks,
    get_postgres_connection,
    logger,
    resolve_fb_compare_weeks,
)
from app.services.fb_share_pptx import build_fb_share_pptx

fb_pptx = Blueprint("fb_pptx", __name__)

PPTX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "report_templates", "fb_share.pptx",
)
TREND_START_YW = 202501


def _template_path():
    return _TEMPLATE_PATH


def _city_last_week():
    """{kabupaten: last yearweek carrying numbers} — drives 'no data since Wnn'."""
    try:
        with db_query(get_postgres_connection) as (conn, cur):
            cur.execute(
                """
                SELECT kabupaten, MAX(yearweek)
                FROM sow.fb_share
                WHERE kabupaten IS NOT NULL AND kabupaten <> ''
                  AND (telkomsel IS NOT NULL OR isat3 IS NOT NULL
                       OR xl IS NOT NULL OR smartfren IS NOT NULL)
                GROUP BY kabupaten
                """
            )
            return {r[0]: int(r[1]) for r in cur.fetchall() if r[1] is not None}
    except Exception as e:
        logger.exception("Error loading fb_share last week per city: %s", e)
        return {}


def build_fb_share_report(ref_yw, threshold=95.0):
    """Assemble everything the deck needs for *ref_yw*."""
    compare = build_fb_share_compare(ref_yw, threshold)
    trend = build_fb_share_trend(min(TREND_START_YW, ref_yw), ref_yw)
    regional_row = next(
        (r for r in compare["branch_table"] if r.get("is_regional")), None
    ) or {}
    summary = compare.get("summary") or {}
    return {
        "yearweek": ref_yw,
        "region_label": compare.get("region_label") or trend.get("region_label"),
        "threshold": summary.get("threshold", threshold),
        "share": {
            "tsel": summary.get("regional_tsel"),
            "ioh": summary.get("regional_ioh"),
            "xls": summary.get("regional_xls"),
        },
        "wow": (regional_row.get("wow") or {}),
        "compare": {
            key: {
                "week": compare.get("compare_weeks", {}).get(key),
                "nominal": compare.get("compare_nominal", {}).get(key),
                "shift": compare.get("compare_shift", {}).get(key, 0),
            }
            for key in ("wow", "mom", "yoy")
        },
        "branch_table": compare.get("branch_table") or [],
        "city_table": compare.get("city_table") or [],
        "summary": summary,
        "trend": trend,
        "city_last_week": _city_last_week(),
    }


@fb_pptx.route("/api/sow/fb-share/compare-weeks", methods=["GET"])
@login_required
def api_fb_share_compare_weeks():
    """Preview which WoW / MoM / YoY weeks a report for ``week`` will compare against."""
    ref_yw = _fb_ref_yearweek(request.args.get("week"))
    if not ref_yw:
        return jsonify({"status": "error", "message": "No yearweek available"}), 400
    resolved = resolve_fb_compare_weeks(ref_yw)
    return jsonify({
        "status": "success",
        "yearweek": ref_yw,
        "weeks": {k: v["week"] for k, v in resolved.items()},
        "nominal": {k: v["nominal"] for k, v in resolved.items()},
        "shift": {k: v["shift"] for k, v in resolved.items()},
    })


@fb_pptx.route("/export/sow/fb-share-pptx", methods=["GET"])
@login_required
def export_fb_share_pptx():
    """Download the FB Share PowerPoint report for a week (default: latest)."""
    ref_yw = _fb_ref_yearweek(request.args.get("week"))
    if not ref_yw:
        return jsonify({"status": "error", "message": "No yearweek available"}), 400

    try:
        threshold = float(request.args.get("threshold", 95))
    except (TypeError, ValueError):
        threshold = 95.0

    try:
        report = build_fb_share_report(ref_yw, threshold)
    except LookupError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception:
        logger.exception("Error building FB share report data for %s", ref_yw)
        return jsonify({"status": "error", "message": "Failed to build FB share report"}), 500

    try:
        blob = build_fb_share_pptx(_template_path(), report)
    except FileNotFoundError:
        logger.exception("FB Share pptx template missing: %s", _template_path())
        return jsonify({"status": "error", "message": "Report template not found"}), 500
    except Exception:
        logger.exception("Error rendering FB share pptx for %s", ref_yw)
        return jsonify({"status": "error", "message": "Failed to render FB share report"}), 500

    year, week = divmod(ref_yw, 100)
    filename = f"crowdsource_fb_share_{year}w{week:02d}.pptx"
    return send_file(
        io.BytesIO(blob),
        mimetype=PPTX_MIMETYPE,
        as_attachment=True,
        download_name=filename,
    )
