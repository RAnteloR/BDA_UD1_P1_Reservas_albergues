"""Medicións do apartado 4.5: tempo da consulta de dispoñibilidade en PostgreSQL e Redis.

A consulta: prazas libres dun albergue nunha noite.
  - PostgreSQL: prazas - COUNT(reservas) (usa o índice idx_reservas_albergue_noite).
  - Redis: GET disp:<albergue>:<noite>, un contador xa calculado.

Uso (desde a raíz do proxecto, co compose en marcha e os datos cargados):
  python -m src.medicions
  python -m src.medicions --repeticions 5000
"""
import argparse
import os
import random
import statistics
import subprocess
import time
from datetime import date, timedelta

import psycopg2
import redis
from dotenv import load_dotenv

SQL_DISPONIBILIDADE = """
SELECT a.prazas - COUNT(r.id)
FROM albergues a
LEFT JOIN reservas r ON r.albergue_id = a.id AND r.noite = %s
WHERE a.id = %s
GROUP BY a.id
"""


def clave(albergue_id, noite):
    return f"disp:{albergue_id}:{noite.isoformat()}"


def carga_contadores(cur, r, desde, dias):
    """Deixa en Redis as prazas libres de cada (albergue, noite), calculadas desde PostgreSQL."""
    cur.execute("""
        SELECT a.id, d.noite::date, a.prazas - COUNT(r.id)
        FROM albergues a
        CROSS JOIN generate_series(%s::date, %s::date, '1 day') AS d(noite)
        LEFT JOIN reservas r ON r.albergue_id = a.id AND r.noite = d.noite::date
        GROUP BY a.id, d.noite, a.prazas
    """, (desde, desde + timedelta(days=dias - 1)))
    filas = cur.fetchall()
    pipe = r.pipeline()
    for albergue_id, noite, libres in filas:
        pipe.set(clave(albergue_id, noite), libres)
    pipe.execute()
    return len(filas)


def mide(funcion, casos):
    """Executa `funcion` por cada caso e devolve os tempos en milisegundos."""
    tempos = []
    for caso in casos:
        t0 = time.perf_counter()
        funcion(*caso)
        tempos.append((time.perf_counter() - t0) * 1000)
    return tempos


def resumo(nome, tempos):
    tempos = sorted(tempos)
    p95 = tempos[int(len(tempos) * 0.95) - 1]
    print(f"| {nome:<10} | {len(tempos):>9} | {statistics.mean(tempos):>9.3f} "
          f"| {statistics.median(tempos):>10.3f} | {p95:>8.3f} |")


def main():
    ap = argparse.ArgumentParser(description="Medicións de Camiño Aberto (apartado 4.5)")
    ap.add_argument("--repeticions", type=int, default=2000)
    ap.add_argument("--desde", type=date.fromisoformat, default=date(2027, 5, 1))
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--semente", type=int, default=42)
    args = ap.parse_args()

    load_dotenv()
    conn = psycopg2.connect(host=os.getenv("PGHOST", "localhost"), user=os.environ["POSTGRES_USER"],
                            password=os.environ["POSTGRES_PASSWORD"], dbname=os.environ["POSTGRES_DB"])
    r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), decode_responses=True)
    cur = conn.cursor()

    cur.execute("SELECT id FROM albergues")
    ids = [f[0] for f in cur.fetchall()]
    n = carga_contadores(cur, r, args.desde, args.dias)
    print(f"Contadores en Redis: {n} (albergue, noite)\n")

    rng = random.Random(args.semente)
    casos = [(rng.choice(ids), args.desde + timedelta(days=rng.randrange(args.dias)))
             for _ in range(args.repeticions)]

    def consulta_pg(albergue_id, noite):
        cur.execute(SQL_DISPONIBILIDADE, (noite, albergue_id))
        return cur.fetchone()[0]

    def consulta_redis(albergue_id, noite):
        return int(r.get(clave(albergue_id, noite)))

    # Coherencia: ambos devolven o mesmo antes de medir
    assert all(consulta_pg(*c) == consulta_redis(*c) for c in casos[:200]), "PostgreSQL e Redis difiren"

    mide(consulta_pg, casos[:200])      # quentamento
    mide(consulta_redis, casos[:200])

    print("| Sistema    | Consultas | Media (ms) | Mediana (ms) | P95 (ms) |")
    print("|------------|-----------|-----------|--------------|----------|")
    resumo("PostgreSQL", mide(consulta_pg, casos))
    resumo("Redis", mide(consulta_redis, casos))

    print("\ndocker stats (tres contedores):")
    print(subprocess.run(
        ["docker", "stats", "--no-stream", "--format",
         "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}",
         "albergues_postgres", "albergues_redis", "albergues_mongo"],
        capture_output=True, text=True, check=True).stdout)

    conn.close()


if __name__ == "__main__":
    main()
