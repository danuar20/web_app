"""4G KPI Daily Routes — /kpi_4g_daily"""
from flask import Blueprint, render_template, request, session, make_response, flash
from app.db.db_webapp import get_postgres_connection
from ._utils import login_required, _no_cache, csv_response, validate_date_params
import psycopg2
import psycopg2.errors

kpi4g_daily = Blueprint("kpi4g_daily", __name__)

def _fv(v): return round(float(v), 2) if v is not None else 0
def _pv(v): return round(float(v), 2) if v is not None else None

BASE_KPIS = [
    {"id": "Payload_GB", "label": "Total Payload (GB)", "unit": "GB", "sql": 'SUM("Total_Payload_4G_(MByte)")/1024.0'},
    {"id": "DL_Payload_GB", "label": "DL Payload (GB)", "unit": "GB", "sql": 'SUM("DL_Payload_(MByte)")/1024.0'},
    {"id": "UL_Payload_GB", "label": "UL Payload (GB)", "unit": "GB", "sql": 'SUM("UL_Payload_(MByte)")/1024.0'},
    {"id": "Traffic_VoLTE", "label": "Traffic VoLTE (Erl)", "unit": "Erl", "sql": 'SUM("Traffic_VoLTE_(erl)")'},
    {"id": "Max_RRC_User", "label": "Max RRC User", "unit": "", "sql": 'SUM("Max RRC Connection User")'},
    {"id": "Active_User", "label": "Active User", "unit": "", "sql": 'SUM("New Active Users rnp")'},
]

RATIO_KPIS = [
    ("Cell_Availability_4G", "Cell Availability (%)", "%", "Cell_Availability_Num_4G", "Cell_Availability_Denum_4G"),
    ("RRC_Establishment_SR", "RRC Setup SR (%)", "%", "RRC_Establishment_Num", "RRC_Establishment_Denum"),
    ("ERAB_SR", "E-RAB Setup SR (%)", "%", "E-RAB_Num", "E-RAB_Denum"),
    ("Call_Setup_SR", "Call Setup SR (%)", "%", "Call_Setup_Num", "Call_Setup_Denum"),
    ("ERAB_Drop", "E-RAB Drop (%)", "%", "E-RAB_Drop_Num", "E-RAB_Drop_Denum"),
    ("CSFB_Preparation_SR", "CSFB Prep SR (%)", "%", "CSFB_Preparation_Num", "CSFB_Preparation_Denum"),
    ("Intra_Freq_LTE_HO_SR", "Intra Freq LTE HO SR (%)", "%", "Intra Freq LTE HO_Num", "Intra Freq LTE HO_Denum"),
    ("Intra_Freq_X2_HO_SR", "Intra Freq X2 HO SR (%)", "%", "Intra Freq X2 HO_Num", "Intra Freq X2 HO_Denum"),
    ("Intra_Freq_S1_HO_SR", "Intra Freq S1 HO SR (%)", "%", "Intra Freq S1 HO_Num", "Intra Freq S1 HO_Denum"),
    ("Inter_Freq_LTE_HO_SR", "Inter Freq LTE HO SR (%)", "%", "Inter Freq LTE HO_Num", "Inter Freq LTE HO_Denum"),
    ("Inter_Freq_X2_HO_SR", "Inter Freq X2 HO SR (%)", "%", "Inter Freq X2 HO_Num", "Inter Freq X2 HO_Denum"),
    ("Inter_Freq_S1_HO_SR", "Inter Freq S1 HO SR (%)", "%", "Inter Freq S1 HO_Num", "Inter Freq S1 HO_Denum"),

    ("LTE_GSM_HO_SR", "LTE-GSM HO SR (%)", "%", "LTE-GSM HO_Num", "LTE-GSM HO_Denum"),
    ("User_DL_Throughput", "User DL Throughput (kbps)", "kbps", "User DL Throughput Num", "User DL Throughput Denum"),
    ("User_UL_Throughput", "User UL Throughput (kbps)", "kbps", "User UL Throughput Num", "User UL Throughput Denum"),
    ("Cell_DL_Throughput", "Cell DL Throughput (kbps)", "kbps", "Cell DL Throughput Num", "Cell DL Throughput Denum"),
    ("Cell_UL_Throughput", "Cell UL Throughput (kbps)", "kbps", "Cell UL Throughput Num", "Cell UL Throughput Denum"),
    ("CQI_7", "CQI>=7 (%)", "%", "CQI>=7_Num", "CQI>=7_Denum"),
    ("UL_PRB_Utilization", "UL PRB Utilization (%)", "%", "UL PRB Utilization Num", "UL PRB Utilization Denum"),
    ("DL_PRB_Utilization", "DL PRB Utilization (%)", "%", "DL PRB Utilization Num", "DL PRB Utilization Denum"),
    ("DL_Throughput_CA", "DL Throughput CA (kbps)", "kbps", "DL Throughput CA Num", "DL Throughput CA Denum"),
    ("UL_Throughput_CA", "UL Throughput CA (kbps)", "kbps", "UL Throughput CA Num", "UL Throughput CA Denum"),
    ("Service_Drop_Rate", "Service Drop Rate (%)", "%", "Service_Drop_Num", "Service_Drop_Denum"),
    ("RRC_Establishment_VoLTE_SR", "RRC Est VoLTE SR (%)", "%", "RRC_Establishment_VoLTE_Num", "RRC_Establishment_VoLTE_Denum"),
    ("ERAB_Setup_VoLTE_QCI1_SR", "E-RAB VoLTE QCI1 SR (%)", "%", "E-RAB_Setup_VoLTE_QCI1_Num", "E-RAB_Setup_VoLTE_QCI1_Denum"),
    ("ERAB_Setup_VoLTE_QCI5_SR", "E-RAB VoLTE QCI5 SR (%)", "%", "E-RAB_Setup_VoLTE_QCI5_Num", "E-RAB_Setup_VoLTE_QCI5_Denum"),
    ("Call_Setup_VoLTE_SR", "Call Setup VoLTE SR (%)", "%", "Call_Setup_VoLTE_Num", "Call_Setup_VoLTE_Denum"),
    ("Call_Drop_VoLTE_Rate", "Call Drop VoLTE Rate (%)", "%", "Call_Drop_VoLTE_Num", "Call_Drop_VoLTE_Denum"),
    ("Intra_Freq_HOSR_VoLTE_SR", "Intra Freq HOSR VoLTE SR (%)", "%", "Intra_Freq_HOSR_VoLTE_Num", "Intra_Freq_HOSR_VoLTE_Denum"),
    ("Inter_Freq_HOSR_VoLTE_SR", "Inter Freq HOSR VoLTE SR (%)", "%", "Inter_Freq_HOSR_VoLTE_Num", "Inter_Freq_HOSR_VoLTE_Denum"),

    ("SRVCC_LTE_GSM_HOSR_VoLTE_SR", "SRVCC LTE-GSM VoLTE SR (%)", "%", "SRVCC_LTE-GSM_HOSR_VoLTE_Num", "SRVCC_LTE-GSM_HOSR_VoLTE_Denum"),
    ("DL_PDCP_SDU_Loss_QCI1", "DL PDCP SDU Loss QCI1 (%)", "%", "DL_PDCP_SDU_Loss_QCI1_Num", "DL_PDCP_SDU_Loss_QCI1_Denum"),
    ("UL_PDCP_SDU_Loss_QCI1", "UL PDCP SDU Loss QCI1 (%)", "%", "UL_PDCP_SDU_Loss_QCI1_Num", "UL_PDCP_SDU_Loss_QCI1_Denum"),
    ("SE_New_v1_TI", "SE_New v1_TI", "", "SE_New v1_TI_Num", "SE_New v1_TI_Denum"),
    ("CQI_average", "CQI Average", "", "Num Average CQI", "Denum Average CQI"),
    ("S1_Signaling_SR_NF", "S1 Signaling SR (NF) (%)", "%", "S1 Signaling SR (NF)_num", "S1 Signaling SR (NF)_denum"),
    ("VoLTE_Call_Setup_SR", "VoLTE Call Setup SR (%)", "%", "[VoLTE]_Call Setup SR (QCI=1&QCI=5)_V2 Num", "[VoLTE]_Call Setup SR (QCI=1&QCI=5)_V2 Denum"),

    ("VoLTE_SRVCC_HO_SR_LTE_GSM", "VoLTE SRVCC LTE-GSM (%)", "%", "[VoLTE]_SRVCC_Handover SR (LTE->GSM)_num", "[VoLTE]_SRVCC_Handover SR (LTE->GSM)_denum"),
    ("VoLTE_Call_Drop_Rate_MME", "VoLTE Call Drop MME (%)", "%", "[VoLTE]_Call Drop Rate_MME (%)_num", "[VoLTE]_Call Drop Rate_MME (%)_denum"),
    ("AGG8", "AGG8 (%)", "%", "Num AGG8", "Denum AGG8"),
    ("Packet_Processing_Delay", "Packet Proc Delay (FDD)", "", "Packet_Processing_Delay_Num (FDD)", "Packet_Processing_Delay_Denum (FDD)")
]

# Generate ALL_KPIS list for template rendering and parsing
ALL_KPIS = BASE_KPIS + [
    {"id": r[0], "label": r[1], "unit": r[2], 
     "sql": f'CASE WHEN SUM("{r[4]}")::numeric>0 THEN SUM("{r[3]}")::numeric/SUM("{r[4]}")::numeric*100 ELSE NULL END'}
    if r[2] == "%" else
    {"id": r[0], "label": r[1], "unit": r[2], 
     "sql": f'CASE WHEN SUM("{r[4]}")::numeric>0 THEN SUM("{r[3]}")::numeric/SUM("{r[4]}")::numeric ELSE NULL END'}
    for r in RATIO_KPIS
]

@kpi4g_daily.route("/kpi_4g_daily")
@login_required
def kpi_4g_daily():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")
    
    # Get selected KPIs or default to core ones
    sel_kpis = request.args.getlist("kpi")
    if not sel_kpis and not from_date: # Default on initial load
        sel_kpis = [
            "Payload_GB", "DL_Payload_GB", "UL_Payload_GB", "Traffic_VoLTE",
            "Max_RRC_User", "Active_User", "Cell_Availability_4G", "RRC_Establishment_SR",
            "ERAB_SR", "Call_Setup_SR", "ERAB_Drop", "CSFB_Preparation_SR",
            "Intra_Freq_LTE_HO_SR", "Inter_Freq_LTE_HO_SR", "DL_PRB_Utilization",
            "UL_PRB_Utilization", "User_DL_Throughput", "User_UL_Throughput",
            "SE_New_v1_TI", "CQI_average", "S1_Signaling_SR_NF"
        ]
        
    site_list   = []
    table_rows  = []
    last_update = None
    chart_labels  = []
    chart_data = {kpi["id"]: {} for kpi in ALL_KPIS}
    
    conn = cur = None
    try:
        conn = get_postgres_connection(); cur = conn.cursor()
        
        try:
            cur.execute('SELECT MAX("Date") FROM "measKpiDy4G"')
            raw_last = cur.fetchone()
            last_update = raw_last[0].strftime('%Y-%m-%d') if raw_last and raw_last[0] else None
        except: pass
        
        # Load Site list
        site_expr = 'CASE WHEN LENGTH("ME Name") >= 8 THEN TRIM(SUBSTRING("ME Name", 3, 6)) ELSE TRIM("ME Name") END'
        try:
            cur.execute(f'''
                SELECT DISTINCT {site_expr} 
                FROM "measKpiDy4G" 
                WHERE "ME Name" IS NOT NULL AND "Date" >= CURRENT_DATE - INTERVAL '60 days' 
                ORDER BY 1
            ''')
            site_list = [r[0] for r in cur.fetchall() if r[0]]
            
            # move selected to top
            if sel_sites:
                site_list = [x for x in site_list if x in sel_sites] + [x for x in site_list if x not in sel_sites]
                
        except Exception:
            pass

        if from_date and to_date and sel_sites:
            kpi_sql_parts = [kpi["sql"].replace("%", "%%") for kpi in ALL_KPIS]
            kpi_sql_str = ",\n                        ".join(kpi_sql_parts)
            
            site_filter = f"AND ({site_expr}) = ANY(%s)"
            
            sql = f"""
                SELECT
                    "Date"::date AS date,
                    {site_expr} AS site_id,
                    {kpi_sql_str}
                FROM "measKpiDy4G"
                WHERE "Date" BETWEEN %s AND %s {site_filter}
                GROUP BY "Date"::date, {site_expr}
                ORDER BY "Date"::date, site_id
            """
            cur.execute(sql, [from_date, to_date, sel_sites])
            rows_data = cur.fetchall()
            
            timestamps_set = set()
            date_dict = {}
            for r in rows_data:
                date_str = r[0].strftime("%Y-%m-%d") if r[0] else ""
                site = (r[1] or "").strip()
                timestamps_set.add(date_str)
                if date_str not in date_dict:
                    date_dict[date_str] = {}
                date_dict[date_str][site] = r
            
            chart_labels = sorted(timestamps_set)
            
            # Format Data for Charts
            for site in sel_sites:
                for kpi_idx, kpi in enumerate(ALL_KPIS):
                    chart_data[kpi["id"]][site] = []
                    for ts in chart_labels:
                        day_data = date_dict.get(ts, {}).get(site)
                        val = day_data[2 + kpi_idx] if day_data else None
                        chart_data[kpi["id"]][site].append(_pv(val))
            
            # Format Data for Tables
            for r in rows_data:
                row_dict = {
                    "date": r[0].strftime("%Y-%m-%d") if r[0] else "",
                    "site": (r[1] or "").strip()
                }
                for kpi_idx, kpi in enumerate(ALL_KPIS):
                    row_dict[kpi["id"]] = _pv(r[2 + kpi_idx])
                table_rows.append(row_dict)

        cur.close(); conn.close()
    except Exception as e:
        import traceback
        with open('traceback.txt', 'w') as f:
            f.write(traceback.format_exc())
        if conn:
            try: conn.rollback()
            except: pass
            conn.close()
        flash(f"Error: {str(e)}", "danger")

    return _no_cache(make_response(render_template(
        "kpi_4g_daily.html",
        username=session.get("username", "User"),
        site_list=site_list,
        sel_sites=sel_sites,
        sel_kpis=sel_kpis,
        all_kpis=ALL_KPIS,
        from_date=from_date, to_date=to_date,
        last_update=last_update,
        table_rows=table_rows,
        chart_labels=chart_labels,
        chart_data=chart_data
    )))

@kpi4g_daily.route("/export/kpi_4g_daily")
@login_required
def export_kpi_4g_daily():
    from_date = request.args.get("from_date", "")
    to_date   = request.args.get("to_date",   "")
    sel_sites = request.args.getlist("site")
    
    valid, err = validate_date_params(from_date, to_date)
    if from_date and to_date and not valid:
        return "Invalid dates", 400
    if not all([from_date, to_date, sel_sites]):
        return "Missing parameters", 400

    try:
        conn = get_postgres_connection(); cur = conn.cursor()
        site_expr = 'CASE WHEN LENGTH("ME Name") >= 8 THEN TRIM(SUBSTRING("ME Name", 3, 6)) ELSE TRIM("ME Name") END'
        kpi_sql_parts = [kpi["sql"].replace("%", "%%") for kpi in ALL_KPIS]
        kpi_sql_str = ",\n                        ".join(kpi_sql_parts)
        site_filter = f"AND ({site_expr}) = ANY(%s)"
        
        sql = f"""
            SELECT
                "Date"::date AS date,
                {site_expr} AS site_id,
                {kpi_sql_str}
            FROM "measKpiDy4G"
            WHERE "Date" BETWEEN %s AND %s {site_filter}
            GROUP BY "Date"::date, {site_expr}
            ORDER BY "Date"::date, site_id
        """
        cur.execute(sql, [from_date, to_date, sel_sites])
        
        headers = ["Date", "Site ID"] + [kpi["label"] for kpi in ALL_KPIS]
        rows = []
        for r in cur.fetchall():
            date_str = r[0].strftime("%Y-%m-%d") if r[0] else ""
            site_id = (r[1] or "").strip()
            row = [date_str, site_id]
            for val in r[2:]:
                row.append(_pv(val) if val is not None else "")
            rows.append(row)
            
        cur.close(); conn.close()
        return csv_response(rows, headers, f"kpi_4g_daily_{from_date}_{to_date}.csv")
    except Exception as e:
        return str(e), 500
