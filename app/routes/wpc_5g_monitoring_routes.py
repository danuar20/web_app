"""WPC 5G Monitoring Routes — /wpc_5g_monitoring"""
from flask import Blueprint, render_template, request, session, make_response, flash, jsonify
from app import cache
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query
from datetime import datetime, timedelta
import psycopg2
import psycopg2.errors

wpc_5g_monitoring = Blueprint("wpc_5g_monitoring", __name__)

def make_post_cache_key(*args, **kwargs):
    import hashlib
    import json
    data = request.get_json() or {}
    key = f"{request.path}:{json.dumps(data, sort_keys=True)}"
    return "post_cache_" + hashlib.md5(key.encode('utf-8')).hexdigest()

@wpc_5g_monitoring.route("/wpc_5g_monitoring")
@login_required
def wpc_5g_monitoring_page():
    today = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=6)).strftime("%Y-%m-%d")

    from_date = request.args.get("from_date", default_fr)
    to_date   = request.args.get("to_date", default_to)

    nsa_city_map = {}
    subnet_list = set()

    try:
        with db_query() as (conn, cur):
            cur.execute("""
                SELECT DISTINCT nsa, city, subnetwork_name 
                FROM "5g_kpi_zte"
                WHERE nsa IS NOT NULL
                ORDER BY nsa, city, subnetwork_name
            """)
            for row in cur.fetchall():
                nsa, city, subnet = row[0], row[1], row[2]
                if nsa:
                    if nsa not in nsa_city_map:
                        nsa_city_map[nsa] = set()
                    if city:
                        nsa_city_map[nsa].add(city)
                if subnet:
                    subnet_list.add(subnet)
    except Exception as e:
        flash(f"Error fetching topology: {str(e)}", "danger")

    nsa_city_map_list = {k: sorted(v) for k, v in nsa_city_map.items()}
    sub_list_sorted = sorted(subnet_list)

    return _no_cache(make_response(render_template(
        "wpc_5g_monitoring.html",
        username=session.get("username"),
        from_date=from_date,
        to_date=to_date,
        default_fr=default_fr,
        default_to=default_to,
        nsa_city_map=nsa_city_map_list,
        sub_list=sub_list_sorted
    )))

@wpc_5g_monitoring.route("/api/wpc_5g/wpc_data", methods=["POST"])
@login_required
@cache.cached(timeout=21600, key_prefix=make_post_cache_key)
def api_wpc_5g_data():
    data = request.get_json()
    from_date = data.get("from_date")
    to_date = data.get("to_date")
    level = data.get("level", "site")
    
    if not all([from_date, to_date]):
        return jsonify({"error": "Missing parameters"}), 400
        
    try:
        with db_query() as (conn, cur):
            cur.execute("SET work_mem = '1GB'")
            cur.execute("SET jit = off")
            
            if level == 'cell':
                sql = """
                    SELECT 
                        cell_du_name AS cell_name,
                        nsa,
                        city,
                        subnetwork_name AS subnet,
                        SUM(num_availability_xhj) as avail_num,
                        SUM(denum_availability_xhj) as avail_denum,
                        SUM(num_sn_setup_success_rate_xhj) as acc_num,
                        SUM(number_of_sn_add_requests) as acc_denum,
                        SUM(num_nr_retainability_xhj) as ret_num,
                        SUM(denum_nr_retainability_xhj) as ret_denum,
                        SUM(nr_mobility_success_rate_num) as mob_num,
                        SUM(nr_mobility_success_rate_denum) as mob_denum,
                        SUM(num_packet_loss_xhj) as pl_num,
                        SUM(denum_packet_loss_xhj) as pl_denum
                    FROM "5g_kpi_zte"
                    WHERE date >= %s::date AND date <= %s::date
                      AND cell_du_name IS NOT NULL
                    GROUP BY cell_du_name, nsa, city, subnetwork_name
                """
            else:
                sql = """
                    SELECT 
                        siteid,
                        nsa,
                        city,
                        subnetwork_name AS subnet,
                        SUM(num_availability_xhj) as avail_num,
                        SUM(denum_availability_xhj) as avail_denum,
                        SUM(num_sn_setup_success_rate_xhj) as acc_num,
                        SUM(number_of_sn_add_requests) as acc_denum,
                        SUM(num_nr_retainability_xhj) as ret_num,
                        SUM(denum_nr_retainability_xhj) as ret_denum,
                        SUM(nr_mobility_success_rate_num) as mob_num,
                        SUM(nr_mobility_success_rate_denum) as mob_denum,
                        SUM(num_packet_loss_xhj) as pl_num,
                        SUM(denum_packet_loss_xhj) as pl_denum
                    FROM "5g_kpi_zte"
                    WHERE date >= %s::date AND date <= %s::date
                      AND siteid IS NOT NULL
                    GROUP BY siteid, nsa, city, subnetwork_name
                """
                
            cur.execute(sql, (from_date, to_date))
            rows = cur.fetchall()
            
            result = []
            for r in rows:
                result.append({
                    "siteid" if level == 'site' else "cell_name": r[0],
                    "nsa": r[1],
                    "city": r[2],
                    "subnet": r[3],
                    "avail_num": float(r[4]) if r[4] is not None else 0,
                    "avail_denum": float(r[5]) if r[5] is not None else 0,
                    "acc_num": float(r[6]) if r[6] is not None else 0,
                    "acc_denum": float(r[7]) if r[7] is not None else 0,
                    "ret_num": float(r[8]) if r[8] is not None else 0,
                    "ret_denum": float(r[9]) if r[9] is not None else 0,
                    "mob_num": float(r[10]) if r[10] is not None else 0,
                    "mob_denum": float(r[11]) if r[11] is not None else 0,
                    "pl_num": float(r[12]) if r[12] is not None else 0,
                    "pl_denum": float(r[13]) if r[13] is not None else 0,
                })
                
            return jsonify({"raw_data": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
