from flask import Blueprint, render_template, request, session, make_response
from app.db.db_pumaz import get_pumaz_connection
from ._utils import login_required, _no_cache
import psycopg2

ta4g = Blueprint("ta4g", __name__)

TA_LABELS = [
    "0-0.156", "0.156-0.312", "0.312-0.468", "0.468-0.624", "0.624-0.780",
    "0.780-0.936", "0.936-1.092", "1.092-1.638", "1.638-2.184", "2.184-2.730",
    "2.730-3.198", "3.198-3.978", "3.978-6.396", "6.396-10.140", ">10.140"
]

def extract_site_id(me_name):
    """Extract site ID using MID(3,6) formula from ME Name column.
    MID(text, 3, 6) = extract 6 characters starting from position 3
    
    Examples:
    C-COK303M41... -> COK303
    MXX022MM1... -> X022MM
    """
    # MID(name, 3, 6) in Python = name[2:8] (0-based indexing)
    if len(me_name) >= 8:
        return me_name[2:8].strip()
    return me_name.strip()

def calc_ta90(ta_vals):
    """Calculate TA 90% (range where 90th percentile falls) and sample count at that range."""
    total = sum(ta_vals)
    if total == 0:
        return "-", 0
    # Find range where 90th percentile falls
    threshold = total * 0.9
    cumsum = 0
    ta90_range = "-"
    ta90_samples = 0
    for i, v in enumerate(ta_vals):
        cumsum += v
        if cumsum >= threshold:
            ta90_range = TA_LABELS[i]
            ta90_samples = int(v)
            break
    return ta90_range, ta90_samples

def calc_ta90_total(ta_vals):
    """Calculate total samples from 0% up to 90% threshold."""
    total = sum(ta_vals)
    if total == 0:
        return 0
    threshold = total * 0.9
    cumsum = 0
    ta90_total = 0
    for v in ta_vals:
        cumsum += v
        if cumsum >= threshold:
            break
        ta90_total += int(v)
    return ta90_total

@ta4g.route("/ta_4g")
@login_required
def ta_4g():
    sel_date = request.args.get("date", "")
    sel_sites = request.args.getlist("site")

    sites_list = []
    chart_data = {}
    last_update = None

    conn = None
    cur = None
    try:
        conn = get_pumaz_connection()
        cur = conn.cursor()

        # Get distinct site names
        cur.execute("""
            SELECT DISTINCT "ME Name" FROM "measTA4G"
            WHERE "ME Name" IS NOT NULL
            ORDER BY "ME Name"
        """)
        raw_sites = [r[0] for r in cur.fetchall()]

        for me in raw_sites:
            site_id = extract_site_id(me)
            if site_id and site_id not in sites_list:
                sites_list.append(site_id)
        sites_list.sort()

        try:
            cur.execute('SELECT MAX("Date"::date) FROM "measTA4G"')
            raw = cur.fetchone()
            last_update = raw[0].strftime('%Y-%m-%d') if raw and raw[0] else None
        except Exception:
            last_update = None

        if sel_date and sel_sites:
            site_filter = " OR ".join([f'"ME Name" LIKE %s' for _ in sel_sites])
            site_params = [f"%{site}%" for site in sel_sites]

            cur.execute(f"""
                SELECT
                    "ME Name",
                    "Cell ID",
                    "Cell Name",
                    "Product",
                    COALESCE("0-0,156_km", 0),
                    COALESCE("0,156-0,312_km", 0),
                    COALESCE("0,312-0,468_km", 0),
                    COALESCE("0,468-0,624_km", 0),
                    COALESCE("0,624-0,780_km", 0),
                    COALESCE("0,780-0,936_km", 0),
                    COALESCE("0,936-1,092_km", 0),
                    COALESCE("1,092-1,638_km", 0),
                    COALESCE("1,638-2,184_km", 0),
                    COALESCE("2,184-2,730_km", 0),
                    COALESCE("2,730-3,198_km", 0),
                    COALESCE("3,198-3,978_km", 0),
                    COALESCE("3,978-6,396_km", 0),
                    COALESCE("6,396-10,140_km", 0),
                    COALESCE("TA > 10,140_km", 0)
                FROM "measTA4G"
                WHERE "Date"::date = %s AND ({site_filter})
                ORDER BY "ME Name", "Cell ID", "Product"
            """, [sel_date] + site_params)

            rows = cur.fetchall()
            if not rows:
                session["flash"] = ("No data found for the selected date and sites.", "info")

            # Group by unique cell (site-sector-product)
            for r in rows:
                me_name   = r[0]   # ME Name
                cell_id   = r[1]   # Cell ID
                cell_name = r[2]  # Cell Name
                product   = r[3]   # Product
                ta_vals   = r[4:]  # TA distribution columns (15 bins)

                site_id = extract_site_id(me_name)
                # Cell ID: clean up any .0 float suffix (DB returns numeric as float)
                cell_id_str = str(int(float(cell_id))) if cell_id else ""
                # Sector: first 1 digit of 2-digit ID (11→S1), first 2 digits of 3-digit ID (171→S17)
                try:
                    num_str = str(int(float(cell_id)))
                    sector = num_str[:2] if len(num_str) >= 3 else num_str[:1]
                except (ValueError, TypeError):
                    sector = ""
                product_str = str(product) if product else ""

                key = f"{site_id}|{sector}|{cell_id_str}|{product_str}"

                if key not in chart_data:
                    chart_data[key] = {
                        "site_id": site_id,
                        "sector": sector,
                        "cell_id": cell_id_str,
                        "cell_name": cell_name,
                        "product": product_str,
                        "ta_vals": [0] * 15
                    }

                # Accumulate TA bins across rows with same cell
                existing = chart_data[key]["ta_vals"]
                for i in range(15):
                    existing[i] += float(ta_vals[i]) if ta_vals[i] else 0

        cur.close(); conn.close()
        cur = None; conn = None

    except psycopg2.OperationalError:
        if conn:
            try: conn.rollback()
            except: pass
        if cur: cur.close()
        if conn: conn.close()
        conn = None; cur = None
        session["flash"] = ("Database connection failed.", "warning")
    except Exception as e:
        import traceback; traceback.print_exc()
        if conn:
            try: conn.rollback()
            except: pass
        if cur: cur.close()
        if conn: conn.close()
        conn = None; cur = None
        session["flash"] = (f"Error: {str(e)}", "danger")

    # Pre-calculate TA 90% for each entry
    for key, data in chart_data.items():
        data["total"] = sum(data["ta_vals"])
        ta90_range, ta90_samples = calc_ta90(data["ta_vals"])
        data["ta90_range"] = ta90_range
        data["ta90_samples"] = ta90_samples
        data["ta90_total"] = calc_ta90_total(data["ta_vals"])

    # Sort chart_data: by site_id, then sector number, then cell_id
    def sector_sort_key(item):
        s = item[1]["sector"]
        try:
            num = int(s)
        except (ValueError, TypeError):
            num = 999
        return (item[1]["site_id"], num, item[1]["cell_id"])

    chart_data = dict(sorted(chart_data.items(), key=sector_sort_key))

    # Group chart_data by sector for separate charts (already sorted by site+sector+cell)
    sector_groups = {}
    for key, data in chart_data.items():
        sector_key = f"{data['site_id']}_S{data['sector']}"
        if sector_key not in sector_groups:
            sector_groups[sector_key] = {}
        sector_groups[sector_key][key] = data

    # Sort sector_groups by numeric sector value so charts appear in correct order
    def sector_group_sort(item):
        parts = item[0].rsplit("_S", 1)
        site_part = parts[0]
        try:
            sec_num = int(parts[1])
        except (ValueError, TypeError, IndexError):
            sec_num = 999
        return (site_part, sec_num)

    sector_groups = dict(sorted(sector_groups.items(), key=sector_group_sort))

    return _no_cache(make_response(render_template(
        "ta_4g.html",
        username=session["username"],
        sites_list=sites_list,
        sel_sites=sel_sites,
        sel_date=sel_date,
        last_update=last_update,
        chart_data=chart_data,
        sector_groups=sector_groups,
        active_sites=len(sites_list),
    )))
