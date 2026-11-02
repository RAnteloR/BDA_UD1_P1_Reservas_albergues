import sys

import psycopg2
import os
from dotenv import load_dotenv
import redis

load_dotenv()


conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD")
)
r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", 6379)),
                decode_responses=True)
cursor_pg = conn.cursor()


def start_count():
    cursor_pg.execute("""
        SELECT
            a.id,
            a.prazas,
            r.noite,
            COUNT(r.id) AS reservas,
            a.prazas - COUNT(r.id) AS libres
        FROM albergues a
        JOIN reservas r ON a.id = r.albergue_id
        GROUP BY a.id, a.prazas, r.noite
    """)

    resultados = cursor_pg.fetchall()

    for albergue_id, prazas, noite, reservas, libres in resultados:

        key = f"prazas:{albergue_id}:{noite}"

        r.set(key, libres)

        print(f"{key} = {libres}")
        
def start_reservas():
    print(reservas(ALBERGUE_ID,NOITE,PEREGRINO_ID))
    
def reservas(albergues, noite , pregrino):
    key = f"prazas:{albergues}:{noite}"
    free = r.decr(key)
    print(free)
    if free >= 0:
        cursor_pg.execute("""
            INSERT INTO reservas (albergue_id, peregrino_id, noite)
            VALUES (%s, %s, %s)
        """, (albergues, pregrino, noite))
        return f"Create successfuly"
    r.incr(key)
    return f"No booking left"


ALBERGUE_ID = 35
NOITE = "2027-05-02"
PEREGRINO_ID = 1


if __name__ == "__main__":
    parte = sys.argv[1] if len(sys.argv) > 1 else "start"
    {"start": start_count, "reserva": start_reservas,}[parte]()
cursor_pg.close()
conn.close()