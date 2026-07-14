"""4G Optim Analysis Routes — /optim_4g"""
from flask import Blueprint, render_template, request, session, jsonify
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, db_query, viewer_blocked
from datetime import datetime, timedelta
import psycopg2
from collections import defaultdict
import json

optim_4g = Blueprint("optim_4g", __name__)

@optim_4g.route("/optim_4g")
@login_required
@viewer_blocked
def optim_4g_main():
    today = datetime.now().date()
    default_to = today.strftime("%Y-%m-%d")
    default_fr = (today - timedelta(days=29)).strftime("%Y-%m-%d")

    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    submitted = request.args.get("submitted", "0") == "1"

    last_update = None
    data_payload_json = "{}"

    if submitted and from_date and to_date:
        conn = None
        cur = None
        try:
            with db_query() as (conn, cur):
                # Get max date
                try:
                    cur.execute('SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily"')
                    raw_last = cur.fetchone()
                    last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
                except Exception:
                    pass

                # Query KPI data at site level, aggregated over the date range
                sql_kpi = """
                    SELECT
                        COALESCE(nsa, 'Unknown') AS nop,
                        COALESCE(city, 'Unknown') AS city,
                        siteid,
                        -- Numerators
                        SUM(dl_prb_util_num) as dl_prb_num,
                        SUM(dl_prb_util_denum) as dl_prb_den,
                        SUM(user_dl_thp_num) as dl_thp_num,
                        SUM(user_dl_thp_denum) as dl_thp_den,
                        SUM(num_average_cqi) as cqi_num,
                        SUM(denum_average_cqi) as cqi_den,
                        SUM(cell_downlink_init_bler * "4g_payload_mb") as dl_bler_num,
                        SUM("4g_payload_mb") as dl_bler_den,
                        SUM(cell_uplink_init_bler * ul_traffic_volume) as ul_bler_num,
                        SUM(ul_traffic_volume) as ul_bler_den,
                        SUM(sdr_num) as sdr_num,
                        SUM(sdr_denum) as sdr_den,
                        SUM(se_v3_num) as se_num,
                        SUM(se_v3_denum) as se_den,
                        SUM(num_rsrp_dbm) as bad_rsrp_num,
                        SUM(denum_rsrp_dbm) as bad_rsrp_den,
                        SUM(rrc_setup_num) as rrc_num,
                        SUM(rrc_setup_denum) as rrc_den,
                        SUM(erab_setup_num) as erab_num,
                        SUM(erab_setup_denum) as erab_den
                    FROM "4g_kpi_zte_daily"
                    WHERE kpi_date >= %s::date AND kpi_date <= %s::date
                    GROUP BY nsa, city, siteid
                """
                cur.execute(sql_kpi, [from_date, to_date])
                kpi_rows = cur.fetchall()

                # Query PL data
                sql_pl = """
                    SELECT
                        COALESCE(nsa, 'Unknown') AS nop,
                        COALESCE(city, 'Unknown') AS city,
                        siteid,
                        SUM(packet_loss_num) as pl_num,
                        SUM(packet_loss_denum) as pl_den
                    FROM "vw_pl_daily"
                    WHERE tech = '4G' AND date >= %s::date AND date <= %s::date
                      AND siteid IS NOT NULL
                    GROUP BY nsa, city, siteid
                """
                cur.execute(sql_pl, [from_date, to_date])
                pl_rows = cur.fetchall()

                # Organize PL by siteid
                pl_by_site = {}
                for r in pl_rows:
                    siteid = r[2]
                    pl_by_site[siteid] = {
                        'pl_num': float(r[3] or 0),
                        'pl_den': float(r[4] or 0)
                    }

                # Process KPI rows into structured python dicts
                regional_data = {'num': defaultdict(float), 'den': defaultdict(float)}
                nop_data = defaultdict(lambda: {'num': defaultdict(float), 'den': defaultdict(float)})
                city_data = defaultdict(lambda: {'num': defaultdict(float), 'den': defaultdict(float), 'nop': ''})
                site_data = defaultdict(lambda: {'num': defaultdict(float), 'den': defaultdict(float), 'city': '', 'nop': ''})

                metrics = ['dl_prb', 'dl_thp', 'cqi', 'dl_bler', 'ul_bler', 'sdr', 'se', 'bad_rsrp', 'rrc', 'erab']

                for r in kpi_rows:
                    nop, city, siteid = r[0], r[1], r[2]
                    
                    nums = {m: float(r[i+3] or 0) for i, m in enumerate(metrics)}
                    dens = {m: float(r[i+4] or 0) for i, m in enumerate(metrics) if m != 'dl_bler' and m != 'ul_bler'}
                    # Bler denominators are the traffic volumes
                    dens['dl_bler'] = float(r[10] or 0)
                    dens['ul_bler'] = float(r[12] or 0)

                    # Update Regional
                    for m in metrics:
                        regional_data['num'][m] += nums[m]
                        regional_data['den'][m] += dens[m]

                    # Update NOP
                    for m in metrics:
                        nop_data[nop]['num'][m] += nums[m]
                        nop_data[nop]['den'][m] += dens[m]

                    # Update City
                    city_data[city]['nop'] = nop
                    for m in metrics:
                        city_data[city]['num'][m] += nums[m]
                        city_data[city]['den'][m] += dens[m]

                    # Update Site
                    site_data[siteid]['nop'] = nop
                    site_data[siteid]['city'] = city
                    for m in metrics:
                        site_data[siteid]['num'][m] += nums[m]
                        site_data[siteid]['den'][m] += dens[m]

                # Merge PL data
                for siteid, pl in pl_by_site.items():
                    if siteid in site_data:
                        nop = site_data[siteid]['nop']
                        city = site_data[siteid]['city']
                        
                        site_data[siteid]['num']['pl'] += pl['pl_num']
                        site_data[siteid]['den']['pl'] += pl['pl_den']
                        
                        city_data[city]['num']['pl'] += pl['pl_num']
                        city_data[city]['den']['pl'] += pl['pl_den']
                        
                        nop_data[nop]['num']['pl'] += pl['pl_num']
                        nop_data[nop]['den']['pl'] += pl['pl_den']
                        
                        regional_data['num']['pl'] += pl['pl_num']
                        regional_data['den']['pl'] += pl['pl_den']

                def compute_kpis(data_node):
                    res = {}
                    res['dl_prb'] = round(data_node['num']['dl_prb'] / data_node['den']['dl_prb'] * 100, 2) if data_node['den'].get('dl_prb') else None
                    res['dl_thp'] = round(data_node['num']['dl_thp'] / data_node['den']['dl_thp'] / 1000.0, 2) if data_node['den'].get('dl_thp') else None
                    res['cqi'] = round(data_node['num']['cqi'] / data_node['den']['cqi'], 2) if data_node['den'].get('cqi') else None
                    res['dl_bler'] = round(data_node['num']['dl_bler'] / data_node['den']['dl_bler'] * 100, 2) if data_node['den'].get('dl_bler') else None
                    res['ul_bler'] = round(data_node['num']['ul_bler'] / data_node['den']['ul_bler'] * 100, 2) if data_node['den'].get('ul_bler') else None
                    res['sdr'] = round(data_node['num']['sdr'] / data_node['den']['sdr'] * 100, 2) if data_node['den'].get('sdr') else None
                    res['se'] = round(data_node['num']['se'] / data_node['den']['se'], 2) if data_node['den'].get('se') else None
                    res['bad_rsrp'] = round(data_node['num']['bad_rsrp'] / data_node['den']['bad_rsrp'] * 100, 2) if data_node['den'].get('bad_rsrp') else None
                    res['rrc'] = round(data_node['num']['rrc'] / data_node['den']['rrc'] * 100, 2) if data_node['den'].get('rrc') else None
                    res['erab'] = round(data_node['num']['erab'] / data_node['den']['erab'] * 100, 2) if data_node['den'].get('erab') else None
                    res['pl'] = round(data_node['num']['pl'] / data_node['den']['pl'] * 100, 4) if data_node['den'].get('pl') else None
                    return res

                def compute_node(node):
                    res = compute_kpis(node)
                    if 'nop' in node and node['nop']: res['nop'] = node['nop']
                    if 'city' in node and node['city']: res['city'] = node['city']
                    return res

                final_regional = compute_node(regional_data)
                
                final_nop = {}
                for k, v in nop_data.items(): final_nop[k] = compute_node(v)
                
                final_city = {}
                for k, v in city_data.items(): final_city[k] = compute_node(v)
                
                final_site = {}
                for k, v in site_data.items(): final_site[k] = compute_node(v)

                data_payload = {
                    "regional": final_regional,
                    "nop": final_nop,
                    "city": final_city,
                    "site": final_site
                }
                data_payload_json = json.dumps(data_payload)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            pass

    return render_template("optim_4g.html",
                           from_date=from_date or default_fr,
                           to_date=to_date or default_to,
                           submitted=submitted,
                           last_update=last_update,
                           data_payload_json=data_payload_json)
