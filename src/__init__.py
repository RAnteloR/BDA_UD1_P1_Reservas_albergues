from datetime import date
import sys
import threading

import psycopg2
import os
from dotenv import load_dotenv
import redis
from uuid import uuid4
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

# FIRST PART
def start_count():
    cursor_pg.execute("""
        SELECT
            a.id,
            d.noite::date,
            a.prazas - COUNT(r.id) AS libres
        FROM albergues a
        CROSS JOIN generate_series(
            (SELECT MIN(noite) FROM reservas),
            (SELECT MAX(noite) FROM reservas),
            '1 day') AS d(noite)
        LEFT JOIN reservas r ON r.albergue_id = a.id AND r.noite = d.noite::date
        GROUP BY a.id, a.prazas, d.noite
    """)

    results = cursor_pg.fetchall()
    conn.commit()

    for albergue_id, noite, libres in results:

        key = f"prazas:{albergue_id}:{noite}"

        r.set(key, libres)

    cursor_pg.execute("""
        SELECT a.id, p.id, r.id, r.noite
        FROM albergues a
        JOIN reservas r ON r.albergue_id = a.id
        JOIN peregrinos p ON p.id = r.peregrino_id
        ORDER BY RANDOM()
        LIMIT 1
        """)

    test_data = cursor_pg.fetchone()

    if test_data:
        albergue_id, peregrino_id, reserva_id, nigth = test_data
        r.mset({
            "test:albergue_id": albergue_id,
            "test:peregrino_id": peregrino_id,
            "test:reserva_id": reserva_id,
            "test:nigth": nigth.isoformat()
        })

def get_ids():
    try:
        return (
            int(r.get("test:albergue_id")),
            int(r.get("test:peregrino_id")),
            int(r.get("test:reserva_id")),
            date.fromisoformat(r.get("test:nigth"))
        )
    except TypeError as e:
        return None

# SECOND PART
def start_reservas(albergue_id,peregrino_id, nigth):
    message = reservas(albergue_id, nigth, peregrino_id)
    print(message)

def reservas(albergues, nigth , peregrino):
    key = f"prazas:{albergues}:{nigth}"
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
                """, (albergues, peregrino, nigth))
                print(f"Inserted booking at {albergues} at nigth {nigth} with {peregrino}")
                conn_thread.commit()
                return f"Create successfuly"
        except psycopg2.Error as e:
            conn_thread.rollback()
            print(f"Peregrino {peregrino}: ERROR: {e}")
            r.incr(key)
            return f"Booking already exists"
    r.incr(key)
    return f"No booking left"

# FOURTH PART
def general_consult(nigth, path):
    consult,where =cache_redis(path,nigth)

    for c in consult:
        print(f"  {c}")
    print(f"\nKey time: {r.ttl(f"booking_left:albergue:{path}:{nigth}")} s")
    print(f"Did it in {where}")

def consult_path_nigth(path,nigth):
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT a.nome,a.camino,a.prazas - COUNT(r.id) AS libres from albergues a
                JOIN reservas r ON a.id = r.albergue_id
                WHERE a.camino = %s AND r.noite = %s
                GROUP BY a.id,a.nome,a.prazas
                """,(path,nigth))

            results = cursor.fetchall()
            conn.commit()
            return [f" {n} · {c} · {libres}" for n, c, libres in results]
    except psycopg2.Error as e:
        conn.rollback()
        return False


def cache_redis(path,nigth):
    KEY = f"booking_left:albergue:{path}:{nigth}"
    exists = r.lrange(KEY,0,-1)

    if exists:
        return (exists, "REDIS")
    consult = consult_path_nigth(path,nigth)
    if consult:
        r.rpush(KEY,*consult)
        r.expire(KEY,15)
    return (consult, "SQL")

#THIRD PART
def do_simulate(albergue_id, noite):
    simulate(reservas, albergue_id, noite)

def simulate(funcion, albergue_id, noite):
    key = f"prazas:{albergue_id}:{noite}"
    bookings = int(r.get(key))
    exitos = []

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id
            FROM peregrinos
            WHERE id NOT IN (
                SELECT peregrino_id
                FROM reservas
                WHERE noite = %s
            )
            ORDER BY RANDOM()
            LIMIT 60
        """, (noite,))

        peregrinos = [row[0] for row in cursor.fetchall()]
    fios = [threading.Thread(target=lambda peregrino_id=p : exitos.append(funcion(albergue_id,noite,peregrino_id))) for p in peregrinos]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    vendidas = exitos.count("Create successfuly")
    print(f"{funcion.__name__:<15} albergue {albergue_id} · noite {noite} · entradas: {bookings} · vendidas: {vendidas:>2} · "
          f"contador final: {r.get(key)}"
          + ("   ← SOBREVENTA!" if vendidas > bookings else ""))


from datetime import date

if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else "start"
    if part == "start":
        start_count()
    else:
        NIGTH_TO_BOOKING = date(2028, 5, 12)
        path= "Francés"
        albergue_id,peregrino_id,reserva_id,nigth = get_ids()

        if part == "reserva":
            start_reservas(albergue_id,peregrino_id, NIGTH_TO_BOOKING)
        elif part == "simulate":
            do_simulate(albergue_id, nigth)
        elif part == "consult":
            general_consult(nigth, path)

cursor_pg.close()
conn.close()
