import sys
import threading

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

    resultados = cursor_pg.fetchall()
    conn.commit()

    for albergue_id, noite, libres in resultados:

        key = f"prazas:{albergue_id}:{noite}"

        r.set(key, libres)

        print(f"{key} = {libres}")


def peregrinos_libres(noite, cantidade):
    """Ids reais de peregrinos (consultados en PostgreSQL) sen reserva a esa noite."""
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id FROM peregrinos
            WHERE id NOT IN (SELECT peregrino_id FROM reservas WHERE noite = %s)
            ORDER BY random() LIMIT %s
        """, (noite, cantidade))
        ids = [f[0] for f in cursor.fetchall()]
    conn.commit()
    return ids

def escolle_albergue_noite(albergue_id=None, noite=None):
    """(albergue_id, noite, camino) reais consultados en PostgreSQL.

    Se non se indica albergue ou noite, escóllense ao azar entre os que teñen reservas.
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT a.id, r.noite, a.camino
            FROM albergues a JOIN reservas r ON r.albergue_id = a.id
            WHERE (%(a)s::int IS NULL OR a.id = %(a)s) AND (%(n)s::date IS NULL OR r.noite = %(n)s)
            GROUP BY a.id, r.noite, a.camino
            ORDER BY random() LIMIT 1
        """, {"a": albergue_id, "n": noite})
        fila = cursor.fetchone()
    conn.commit()
    if fila is None:
        sys.exit("Non hai ningún albergue/noite con eses datos en PostgreSQL")
    return fila[0], str(fila[1]), fila[2]


def start_reservas(albergue_id, noite, camino):
    peregrino_id = peregrinos_libres(noite, 1)[0]
    message = reservas(albergue_id, noite, peregrino_id)
    print(message)

def reservas(albergues, noite , peregrino):
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
                """, (albergues, peregrino, noite))
                print(f"Inserted booking at {albergues} at nigth {noite} with {peregrino}")
                conn_thread.commit()
                return f"Create successfuly"
        except psycopg2.Error as e:
            conn_thread.rollback()
            print(f"Peregrino {peregrino}: ERROR: {e}")
            r.incr(key)
            return f"Booking already exists"
    r.incr(key)
    return f"No booking left"

def general_consult(albergue_id, noite, camino):
    consult,where =cache_redis(camino,noite)

    for c in consult:
        print(f"  {c}")
    print(f"\nCaducidade restante da chave: {r.ttl(f"booking_left:albergue:{camino}:{noite}")} s")
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
        print(e)
        return False


def cache_redis(path,nigth):
    KEY = f"booking_left:albergue:{path}:{nigth}"
    exists = r.lrange(KEY,0,-1)

    if exists:
        return (exists, "REDIS")
    consult = consult_path_nigth(path,nigth)
    if consult:
        print(*consult)
        r.rpush(KEY,*consult)
        r.expire(KEY,15)
    return (consult, "SQL")
    
FANS = 10

def do_simulate(albergue_id, noite, camino):
    simulate(reservas, albergue_id, noite)

def simulate(funcion, albergue_id, noite):
    key = f"prazas:{albergue_id}:{noite}"
    bookings = int(r.get(key))
    exitos = []
    ids = peregrinos_libres(noite, FANS)
    fios = [threading.Thread(target=lambda peregrino_id=pid : exitos.append(funcion(albergue_id,noite,peregrino_id))) for pid in ids]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    vendidas = exitos.count("Create successfuly")
    print(f"{funcion.__name__:<15} albergue {albergue_id} · noite {noite} · entradas: {bookings} · vendidas: {vendidas:>2} · "
          f"contador final: {r.get(key)}"
          + ("   ← SOBREVENTA!" if vendidas > bookings else ""))

if __name__ == "__main__":
    # python src/__init__.py <start|reserva|simulate|consult> [albergue_id] [noite AAAA-MM-DD]
    parte = sys.argv[1] if len(sys.argv) > 1 else "start"
    if parte == "start":
        start_count()
    else:
        albergue_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
        noite_arg = sys.argv[3] if len(sys.argv) > 3 else None
        accion = {"reserva": start_reservas, "simulate": do_simulate, "consult": general_consult}[parte]
        accion(*escolle_albergue_noite(albergue_arg, noite_arg))

cursor_pg.close()
conn.close()
