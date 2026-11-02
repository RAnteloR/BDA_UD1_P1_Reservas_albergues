import sys
import threading

import psycopg2
import os
from dotenv import load_dotenv
import redis
import random
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
    booking = reservas(ALBERGUE_ID,NOITE,PEREGRINO_ID)
    if booking:
        print(f"Create successfuly")
    else:
        print(f"No booking left")

def reservas(albergues, noite , pregrino):
    key = f"prazas:{albergues}:{noite}"
    free = r.decr(key)
    if free >= 0:
        conn_thread = psycopg2.connect(
        host="localhost",
        port=5432,
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
        )
        try:
            with conn_thread.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO reservas (albergue_id, peregrino_id, noite)
                    VALUES (%s, %s, %s)
                """, (albergues, pregrino, noite))
                return True
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Peregrino {pregrino}: ERROR: {e}")
            r.incr(key)
            return False
    r.incr(key)
    return False


ALBERGUE_ID = 35
NOITE = "2027-05-02"
PEREGRINO_ID = 1500


KEY = f"prazas:{ALBERGUE_ID}:{NOITE}"
FANS = 10

def do_simulate():
    simulate(reservas)

def simulate(funcion):
    bookings = int(r.get(KEY))
    exitos = []
    fios = [threading.Thread(target=lambda peregrino_id=random.randint(0,1500) : exitos.append(funcion(ALBERGUE_ID,NOITE,peregrino_id))) for r in range(FANS)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    print(exitos)
    vendidas = sum(exitos)
    print(f"{funcion.__name__:<15} entradas: {bookings} · vendidas: {vendidas:>2} · "
          f"contador final: {r.get(KEY)}"
          + ("   ← SOBREVENTA!" if vendidas > bookings else ""))

if __name__ == "__main__":
    parte = sys.argv[1] if len(sys.argv) > 1 else "start"
    {"start": start_count, "reserva": start_reservas,"simulate":do_simulate}[parte]()

cursor_pg.close()
conn.close()