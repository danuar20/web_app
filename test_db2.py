
import sys, os
sys.path.insert(0, os.path.abspath('d:/Database/Coding/Belajar Coding Basic/Web-server/web_app'))
from app.db.db_webapp import get_postgres_connection

try:
    conn = get_postgres_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM \"4g_kpi_zte_daily\" LIMIT 1')
    colnames = [desc[0] for desc in cur.description]
    print('4g_kpi_zte_daily columns:', colnames)
    conn.close()
except Exception as e:
    print('ERROR:', e)

