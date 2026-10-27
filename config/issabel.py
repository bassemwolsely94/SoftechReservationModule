"""
Issabel CDR connector  (doc 16, Phase 5)
========================================
Read-only connection to the Issabel/Asterisk CDR database (MySQL/MariaDB) so the
call-center call-count can be pulled automatically (like SOFTECH sales).

Configure in .env (never hard-code credentials):
  ISSABEL_CDR_HOST=192.168.1.155
  ISSABEL_CDR_PORT=3306
  ISSABEL_CDR_DB=asteriskcdrdb
  ISSABEL_CDR_TABLE=cdr
  ISSABEL_CDR_USER=<db user>
  ISSABEL_CDR_PASSWORD=<db password>

Returns raw CDR rows; the counting rule lives in apps.forecasting.callcount so the
CSV importer and the live pull produce identical numbers.
"""
from decouple import config


def cdr_configured() -> bool:
    return bool(config('ISSABEL_CDR_USER', default='') and config('ISSABEL_CDR_PASSWORD', default=''))


def get_cdr_connection():
    import pymysql
    return pymysql.connect(
        host=config('ISSABEL_CDR_HOST', default='192.168.1.155'),
        port=config('ISSABEL_CDR_PORT', default=3306, cast=int),
        database=config('ISSABEL_CDR_DB', default='asteriskcdrdb'),
        user=config('ISSABEL_CDR_USER', default=''),
        password=config('ISSABEL_CDR_PASSWORD', default=''),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=60,
    )


def fetch_cdr_rows(start_date, end_date):
    """Rows with [start_date, end_date) on calldate. Dates as 'YYYY-MM-DD' strings/date."""
    table = config('ISSABEL_CDR_TABLE', default='cdr')
    sql = (f"SELECT calldate, clid, src, dst, disposition "
           f"FROM {table} WHERE calldate >= %s AND calldate < %s")
    conn = get_cdr_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (str(start_date), str(end_date)))
            return cur.fetchall()
    finally:
        conn.close()
