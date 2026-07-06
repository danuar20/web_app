"""4G KPI API & Export Routes — /api/kpi_4g_hourly, /export/kpi_4g_hourly"""
from flask import Blueprint, request
from app.db.db_webapp import get_postgres_connection, get_site_list_4g
from ._utils import login_required, json_response, csv_response, validate_date_params, db_query
import psycopg2
import psycopg2.errors

kpi4g_api = Blueprint("kpi4g_api", __name__)

# ── API: 4G KPI Hourly (JSON) ──────────────────────────────────────────────────
@kpi4g_api.route("/api/kpi_4g_hourly")
@login_required
def api_kpi_4g_hourly():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    valid, err = validate_date_params(from_date, to_date)
    if from_date and to_date and not valid:
        return json_response({"error": err}, 400)
    if not all([from_date, to_date, sel_sites]):
        return json_response({"error": "Missing required parameters: from_date, to_date, site"}, 400)

    try:
        with db_query() as (conn, cur):
            cur.execute("""
                SELECT
                    datehour, siteid,
                    SUM("4g_payload_mb") AS payload_mb,
                    CASE WHEN SUM(cssr_denum)>0
                         THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100.0)::numeric,2) ELSE NULL END AS cssr_pct,
                    SUM(volte_traffic) AS volte_traffic,
                    SUM(max_rrc_conn_user) AS max_rrc_conn_user,
                    SUM(new_active_users) AS active_users,
                    CASE WHEN SUM(dl_prb_util_denum)>0
                         THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100.0)::numeric,2) ELSE NULL END AS dl_prb_util_pct,
                    CASE WHEN SUM(ul_prb_util_denum)>0
                         THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100.0)::numeric,2) ELSE NULL END AS ul_prb_util_pct,
                    CASE WHEN SUM(user_dl_thp_denum)>0
                         THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000.0)::numeric,2) ELSE NULL END AS user_dl_thp_mbps,
                    CASE WHEN SUM(user_ul_thp_denum)>0
                         THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000.0)::numeric,2) ELSE NULL END AS user_ul_thp_mbps,
                    CASE WHEN SUM(avail_denum)>0
                         THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100.0)::numeric,2) ELSE NULL END AS avail_pct,
                    CASE WHEN SUM(erab_setup_denum)>0
                         THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100.0)::numeric,2) ELSE NULL END AS erab_sr_pct,
                    CASE WHEN SUM(rrc_setup_denum)>0
                         THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100.0)::numeric,2) ELSE NULL END AS rrc_sr_pct,
                    CASE WHEN SUM(s1_signaling_sr_denum)>0
                         THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100.0)::numeric,2) ELSE NULL END AS s1_sr_pct,
                    CASE WHEN SUM(sdr_denum)>0
                         THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100.0)::numeric,2) ELSE NULL END AS sdr_pct,
                    CASE WHEN SUM(ifho_denum)>0
                         THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100.0)::numeric,2) ELSE NULL END AS ifho_pct,
                    CASE WHEN SUM(csfb_denum)>0
                         THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100.0)::numeric,2) ELSE NULL END AS csfb_pct,
                    CASE WHEN SUM(se_v3_denum)>0
                         THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END AS se,
                    CASE WHEN SUM(denum_average_cqi)>0
                         THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END AS cqi
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid=ANY(%s)
                GROUP BY datehour, siteid
                ORDER BY datehour, siteid
            """, [from_date, to_date, sel_sites])

            rows = []
            for r in cur.fetchall():
                rows.append({
                    "datehour": r[0].isoformat() if r[0] else None,
                    "siteid": r[1],
                    "payload_mb": round(float(r[2]), 2) if r[2] is not None else None,
                    "cssr_pct": float(r[3]) if r[3] is not None else None,
                    "volte_traffic": float(r[4]) if r[4] is not None else None,
                    "max_rrc_conn_user": float(r[5]) if r[5] is not None else None,
                    "active_users": float(r[6]) if r[6] is not None else None,
                    "dl_prb_util_pct": float(r[7]) if r[7] is not None else None,
                    "ul_prb_util_pct": float(r[8]) if r[8] is not None else None,
                    "dl_thp_mbps": float(r[9]) if r[9] is not None else None,
                    "ul_thp_mbps": float(r[10]) if r[10] is not None else None,
                    "avail_pct": float(r[11]) if r[11] is not None else None,
                    "erab_sr_pct": float(r[12]) if r[12] is not None else None,
                    "rrc_sr_pct": float(r[13]) if r[13] is not None else None,
                    "s1_sr_pct": float(r[14]) if r[14] is not None else None,
                    "sdr_pct": float(r[15]) if r[15] is not None else None,
                    "ifho_pct": float(r[16]) if r[16] is not None else None,
                    "csfb_pct": float(r[17]) if r[17] is not None else None,
                    "se": float(r[18]) if r[18] is not None else None,
                    "cqi": float(r[19]) if r[19] is not None else None,
                })

            cur.execute('SELECT MAX(datehour::date) FROM "4g_kpi_zte"')
            raw_last = cur.fetchone()
            last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
            return json_response({"data": rows, "last_update": last_update, "count": len(rows)})
    except psycopg2.OperationalError:
        return json_response({"error": "Database connection failed."}, 503)
    except Exception as e:
        return json_response({"error": str(e)}, 500)

# ── Export: 4G KPI Hourly (CSV) ─────────────────────────────────────────────────
@kpi4g_api.route("/export/kpi_4g_hourly")
@login_required
def export_kpi_4g_hourly():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")

    valid, err = validate_date_params(from_date, to_date)
    if from_date and to_date and not valid:
        return json_response({"error": err}, 400)
    if not all([from_date, to_date, sel_sites]):
        return json_response({"error": "Missing required parameters"}, 400)

    try:
        with db_query() as (conn, cur):
            cur.execute("""
                SELECT
                    datehour, siteid,
                    SUM("4g_payload_mb") AS payload_mb,
                    CASE WHEN SUM(cssr_denum)>0
                         THEN ROUND((SUM(cssr_num)/SUM(cssr_denum)*100.0)::numeric,2) ELSE NULL END AS cssr_pct,
                    SUM(volte_traffic), SUM(max_rrc_conn_user), SUM(new_active_users),
                    CASE WHEN SUM(dl_prb_util_denum)>0
                         THEN ROUND((SUM(dl_prb_util_num)/SUM(dl_prb_util_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(ul_prb_util_denum)>0
                         THEN ROUND((SUM(ul_prb_util_num)/SUM(ul_prb_util_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(user_dl_thp_denum)>0
                         THEN ROUND((SUM(user_dl_thp_num)/SUM(user_dl_thp_denum)/1000.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(user_ul_thp_denum)>0
                         THEN ROUND((SUM(user_ul_thp_num)/SUM(user_ul_thp_denum)/1000.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(avail_denum)>0
                         THEN ROUND((SUM(avail_num)/SUM(avail_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(erab_setup_denum)>0
                         THEN ROUND((SUM(erab_setup_num)/SUM(erab_setup_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(rrc_setup_denum)>0
                         THEN ROUND((SUM(rrc_setup_num)/SUM(rrc_setup_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(s1_signaling_sr_denum)>0
                         THEN ROUND((SUM(s1_signaling_sr_num)/SUM(s1_signaling_sr_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(sdr_denum)>0
                         THEN ROUND((SUM(sdr_num)/SUM(sdr_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(ifho_denum)>0
                         THEN ROUND((SUM(ifho_num)/SUM(ifho_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(csfb_denum)>0
                         THEN ROUND((SUM(csfb_num)/SUM(csfb_denum)*100.0)::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(se_v3_denum)>0
                         THEN ROUND((SUM(se_v3_num)/SUM(se_v3_denum))::numeric,2) ELSE NULL END,
                    CASE WHEN SUM(denum_average_cqi)>0
                         THEN ROUND((SUM(num_average_cqi)/SUM(denum_average_cqi))::numeric,2) ELSE NULL END
                FROM "4g_kpi_zte"
                WHERE date BETWEEN %s AND %s AND siteid=ANY(%s)
                GROUP BY datehour, siteid
                ORDER BY datehour, siteid
            """, [from_date, to_date, sel_sites])

            headers = [
                "datehour","siteid","payload_mb","cssr_pct","volte_traffic",
                "max_rrc_conn_user","active_users","dl_prb_util_pct","ul_prb_util_pct",
                "dl_thp_mbps","ul_thp_mbps","avail_pct","erab_sr_pct","rrc_sr_pct",
                "s1_sr_pct","sdr_pct","ifho_pct","csfb_pct","se","cqi"
            ]
            rows = []
            for r in cur.fetchall():
                rows.append([
                    r[0].isoformat() if r[0] else "",
                    r[1] or "",
                    *[round(float(v), 2) if v is not None else "" for v in r[2:]],
                ])
            return csv_response(rows, headers, f"kpi_4g_hourly_{from_date}_{to_date}.csv")
    except psycopg2.OperationalError:
        return json_response({"error": "Database connection failed."}, 503)
    except Exception as e:
        return json_response({"error": str(e)}, 500)