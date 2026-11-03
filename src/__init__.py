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
            r.noite,
            a.prazas - COUNT(r.id) AS libres
        FROM albergues a
        JOIN reservas r ON a.id = r.albergue_id
        GROUP BY a.id, a.prazas, r.noite
    """)

    resultados = cursor_pg.fetchall()

    for albergue_id, noite, libres in resultados:

        key = f"prazas:{albergue_id}:{noite}"

        r.set(key, libres)

        print(f"{key} = {libres}")
        
def start_reservas():
    message = reservas(ALBERGUE_ID,NOITE,PEREGRINO_ID)
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

CAMINO = "Norte"

def general_consult():
    consult,where =cache_redis(CAMINO,NOITE)

    for c in consult:
        print(f"  {c}")
    print(f"\nCaducidade restante da chave: {r.ttl(f"booking_left:albergue:{CAMINO}:{NOITE}")} s")
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
    
ALBERGUE_ID = 13
NOITE = "2027-05-02"
PEREGRINO_ID = random.randint(0,1500)


KEY = f"prazas:{ALBERGUE_ID}:{NOITE}"
FANS = 10

def do_simulate():
    simulate(reservas)

def simulate(funcion):
    bookings = int(r.get(KEY))
    exitos = []
    fios = [threading.Thread(target=lambda peregrino_id=random.randint(0,1500) : exitos.append(funcion(ALBERGUE_ID,NOITE,peregrino_id))) for _ in range(FANS)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    vendidas = exitos.count("Create successfuly")
    print(f"{funcion.__name__:<15} entradas: {bookings} · vendidas: {vendidas:>2} · "
          f"contador final: {r.get(KEY)}"
          + ("   ← SOBREVENTA!" if vendidas > bookings else ""))

if __name__ == "__main__":
    parte = sys.argv[1] if len(sys.argv) > 1 else "start"
    {"start": start_count, "reserva": start_reservas,"simulate":do_simulate,"consult":general_consult}[parte]()

cursor_pg.close()
conn.close()