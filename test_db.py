
import sys, os
sys.path.insert(0, os.path.abspath('d:/Database/Coding/Belajar Coding Basic/Web-server/web_app'))
from app.db.db_webapp import db_query

from_date = '2026-06-01'
to_date = '2026-07-30'

conn = None
cur = None
with db_query() as (conn, cur):
    try:
        cur.execute('''
            SELECT
                COALESCE(nsa, 'Unknown') AS nop,
                COALESCE(city, 'Unknown') AS city,
                siteid,
                band,
                SUM(dl_prb_util_num) as dl_prb_num
            FROM \"4g_kpi_zte_daily\"
            WHERE kpi_date >= %s::date AND kpi_date <= %s::date
            GROUP BY nsa, city, siteid, band
            LIMIT 5
        ''', [from_date, to_date])
        print('kpi:', cur.fetchall())
    except Exception as e:
        print('ERROR kpi:', e)

    try:
        cur.execute('''
            SELECT
                COALESCE(nsa, 'Unknown') AS nop,
                COALESCE(city, 'Unknown') AS city,
                siteid,
                SUM(packet_loss_num) as pl_num
            FROM \"vw_pl_daily\"
            WHERE tech = '4G' AND date >= %s::date AND date <= %s::date
              AND siteid IS NOT NULL
            GROUP BY nsa, city, siteid
            LIMIT 5
        ''', [from_date, to_date])
        print('pl:', cur.fetchall())
    except Exception as e:
        print('ERROR pl:', e)

