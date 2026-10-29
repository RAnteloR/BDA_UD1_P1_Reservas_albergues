"""Xerador de datos de proba para a rede de albergues Camiño Aberto (ficticia).

Xera albergues, peregrinos, reservas e fichas, e cárgaos en PostgreSQL e MongoDB.
A mesma semente produce sempre os mesmos datos.

Exemplos (desde a raíz do proxecto):
  python -m src.xera_datos --sen-carga                    # só xerar e mostrar
  python -m src.xera_datos --albergues 60 --semente 7 --sen-carga
  python -m src.xera_datos                                 # xerar e cargar 
"""
import argparse
from collections import Counter
import os
import random
from datetime import date, timedelta

import psycopg2
from dotenv import load_dotenv
from faker import Faker
from pymongo import MongoClient
from psycopg2.extras import execute_values

# ------------------------------------------------------------------ catálogos
# Concellos galegos de cada camiño, en orde de etapas. Podes engadir máis.
CAMIÑOS = {
    "Francés":   ["Pedrafita do Cebreiro", "Triacastela", "Samos", "Sarria", "Portomarín",
                  "Palas de Rei", "Melide", "Arzúa", "O Pino"],
    "Portugués": ["Tui", "O Porriño", "Redondela", "Pontevedra", "Caldas de Reis", "Padrón", "Teo"],
    "Norte":     ["Ribadeo", "Lourenzá", "Mondoñedo", "Abadín", "Vilalba", "Guitiriz", "Sobrado"],
    "Primitivo": ["A Fonsagrada", "Castroverde", "Lugo", "Friol", "Melide"],
    "Inglés":    ["Ferrol", "Neda", "Pontedeume", "Betanzos", "Abegondo", "Ordes"],
}
NOMES_ALBERGUE = ["Vieiras", "Pedra Miúda", "O Cruceiro", "A Ponte Vella", "Bordón", "A Cabaciña",
                  "Fonte Vella", "Os Carballos", "A Estrela", "Camiño Real", "Casa do Peregrino",
                  "A Xesta", "O Muíño", "Santa Mariña", "O Hórreo", "A Lareira", "Sete Fontes"]


# Un Faker por país: así o nome e o apelido son coherentes co país.
LOCALES = {"España": "es_ES", "Portugal": "pt_PT", "Alemaña": "de_DE", "Francia": "fr_FR",
           "Italia": "it_IT", "Irlanda": "en_IE"}
PESOS_PAIS = [50, 15, 12, 10, 8, 5]
DATA_REF = date(2027, 1, 1)   # data fixa para calcular idades (reproducible)

SERVIZOS_BASICOS = ["cociña", "lavadora", "secadora", "mantas"]
SERVIZOS_EXTRA = ["wifi", "almorzo", "cea", "piscina", "farmacia", "transporte de mochilas"]
IDIOMAS = ["inglés", "francés", "alemán", "portugués", "italiano"]
TITULARES_PUBLICOS = ["Xunta de Galicia", "Concello", "Deputación"]
OPINIONS = [(2, "Pouca auga quente"), (3, "Correcto"), (4, "Moi limpo"),
            (4, "Boa relación calidade-prezo"), (5, "Almorzo estupendo"), (5, "Trato inmellorable")]


# ------------------------------------------------------------------ xeración
def xera_albergues(n, rng):
    """EXEMPLO RESOLTO: úsao como modelo para o resto de funcións.

    Devolve unha lista de dicionarios, un por albergue. Todo o azar sae de `rng`
    (un random.Random), non do módulo `random` directamente: así a semente controla
    o resultado.
    """
    albergues = []
    for i in range(1, n + 1):
        camino = rng.choice(list(CAMIÑOS))
        concello = rng.choice(CAMIÑOS[camino])
        albergues.append({
            "id": i,
            "nome": f"Albergue {rng.choice(NOMES_ALBERGUE)} ({concello})",
            "camino": camino,
            "concello": concello,
            "prazas": rng.randint(8, 60),
            "prezo": float(rng.randint(10, 22)),
        })
    return albergues


def xera_peregrinos(n, rng, fake):
    """Devolve `n` peregrinos con documento e email únicos, reproducibles coa semente."""
    fakers = {}
    for pais, locale in LOCALES.items():
        fakers[pais] = Faker(locale)
        fakers[pais].seed_instance(rng.randint(0, 2**32 - 1))

    peregrinos = []
    for i in range(1, n + 1):
        pais = rng.choices(list(LOCALES), weights=PESOS_PAIS)[0]
        peregrinos.append({
            "id": i,
            "nome": fakers[pais].first_name(),
            "apelidos": fakers[pais].last_name(),
            "documento": f"{10_000_000 + i}{rng.choice('ABCDEFGHJKLMNPQRSTVWXYZ')}",  # único polo id
            "email": f"peregrino{i}@example.com",
            "pais": pais,
            "data_nacemento": DATA_REF - timedelta(days=rng.randint(18 * 365, 80 * 365)),
        })
    return peregrinos


def xera_reservas(n, albergues, peregrinos, desde, dias, rng):
    """Devolve ata `n` reservas entre `desde` e `desde + dias - 1`.

    Regras do negocio:
      - Nun albergue, as reservas dunha noite non poden superar as súas prazas.
      - Un peregrino non pode ter dúas reservas a mesma noite.
    Os intentos que as incumpren descártanse, así que pode haber menos de `n`.
    """
    ocupadas = Counter()   # (albergue_id, noite) -> reservas feitas
    xa_reservou = set()    # (peregrino_id, noite)
    reservas = []
    for _ in range(n):
        albergue = rng.choice(albergues)
        peregrino = rng.choice(peregrinos)
        noite = desde + timedelta(days=rng.randrange(dias))

        if (peregrino["id"], noite) in xa_reservou:
            continue
        if ocupadas[albergue["id"], noite] >= albergue["prazas"]:
            continue

        xa_reservou.add((peregrino["id"], noite))
        ocupadas[albergue["id"], noite] += 1
        reservas.append({"id": len(reservas) + 1, "albergue_id": albergue["id"],
                         "peregrino_id": peregrino["id"], "noite": noite})
    return reservas


def xera_fichas(albergues, rng, fake):
    """Devolve unha ficha por albergue para MongoDB; os campos varían entre albergues.

    Os públicos son sinxelos (con titularidade). Os privados teñen máis servizos,
    contacto e, ao azar, cans, bicicletas, idiomas e opinións.
    """
    fichas = []
    for a in albergues:
        ficha = {
            "albergue_id": a["id"],
            "nome": a["nome"],
            "camino": a["camino"],
            "servizos": rng.sample(SERVIZOS_BASICOS, rng.randint(1, 3)),
            "horario": {"apertura": f"{rng.randint(12, 14)}:00",
                        "peche": f"{rng.randint(21, 22)}:{rng.choice(['00', '30'])}"},
        }
        if rng.random() < 0.4:
            ficha["titularidade"] = rng.choice(TITULARES_PUBLICOS)
        else:
            engade_datos_privados(ficha, rng)
        fichas.append(ficha)
    return fichas


def engade_datos_privados(ficha, rng):
    """Engade á ficha os campos propios dun albergue privado (cada un, ao azar)."""
    ficha["servizos"] += rng.sample(SERVIZOS_EXTRA, rng.randint(1, 4))
    ficha["contacto"] = {"telefono": f"+34 98{rng.randint(1, 8)} {rng.randint(100, 999)} {rng.randint(100, 999)}"}
    if rng.random() < 0.7:
        ficha["contacto"]["web"] = f"https://albergue{ficha['albergue_id']}.gal"
    if rng.random() < 0.5:
        ficha["admite_cans"] = rng.random() < 0.6
    if rng.random() < 0.6:
        garaxe = rng.random() < 0.7
        ficha["bicicletas"] = {"garaxe": garaxe, "prazas": rng.randint(4, 20) if garaxe else 0}
    if rng.random() < 0.6:
        ficha["idiomas"] = ["galego", "castelán"] + rng.sample(IDIOMAS, rng.randint(0, 3))
    if rng.random() < 0.7:
        ficha["opinions"] = [
            {"autor": rng.choice("ABCDEFGHIJLMNPRSTV") + ".", "nota": nota, "texto": texto}
            for nota, texto in rng.choices(OPINIONS, k=rng.randint(1, 5))
        ]


# ------------------------------------------------------------------ carga
ESQUEMA_POSTGRES = """
DROP TABLE IF EXISTS reservas, peregrinos, albergues CASCADE;

CREATE TABLE albergues (
    id       INTEGER PRIMARY KEY,
    nome     TEXT NOT NULL,
    camino   TEXT NOT NULL,
    concello TEXT NOT NULL,
    prazas   INTEGER NOT NULL CHECK (prazas > 0),
    prezo    NUMERIC(6,2) NOT NULL CHECK (prezo >= 0)
);

CREATE TABLE peregrinos (
    id             INTEGER PRIMARY KEY,
    nome           TEXT NOT NULL,
    apelidos       TEXT NOT NULL,
    documento      TEXT NOT NULL UNIQUE,
    email          TEXT NOT NULL UNIQUE,
    pais           TEXT NOT NULL,
    data_nacemento DATE NOT NULL
);

CREATE TABLE reservas (
    id           INTEGER PRIMARY KEY,
    albergue_id  INTEGER NOT NULL REFERENCES albergues(id),
    peregrino_id INTEGER NOT NULL REFERENCES peregrinos(id),
    noite        DATE NOT NULL,
    UNIQUE (peregrino_id, noite)
);
CREATE INDEX idx_reservas_albergue_noite ON reservas (albergue_id, noite);
"""


def insire(cur, taboa, filas):
    """Insire `filas` (lista de dicionarios coas mesmas claves) en `taboa`."""
    columnas = list(filas[0])
    execute_values(cur, f"INSERT INTO {taboa} ({', '.join(columnas)}) VALUES %s",
                   [[f[c] for c in columnas] for f in filas])


def carga_postgres(albergues, peregrinos, reservas):
    """Recrea as táboas e insire os datos nunha única transacción."""
    load_dotenv()
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )
    try:
        with conn, conn.cursor() as cur:   # `with conn`: commit ao final, rollback se hai erro
            cur.execute(ESQUEMA_POSTGRES)
            insire(cur, "albergues", albergues)
            insire(cur, "peregrinos", peregrinos)
            insire(cur, "reservas", reservas)
        print(f"  Postgres: {len(albergues)} albergues, {len(peregrinos)} peregrinos, "
              f"{len(reservas)} reservas cargados")
    finally:
        conn.close()


def carga_mongo(fichas):
    """Garda as fichas na colección `fichas` (substitúe o contido anterior)."""
    load_dotenv()
    user, pwd = os.environ["MONGO_USER"], os.environ["MONGO_PASSWORD"]
    client = MongoClient(f"mongodb://{user}:{pwd}@{os.getenv('MONGO_HOST', 'localhost')}:27017/?authSource=admin")
    try:
        col = client[os.environ["MONGO_DB"]]["fichas"]
        col.drop()
        if fichas:
            col.insert_many(fichas)
        col.create_index("albergue_id", unique=True)
        print(f"  Mongo: {len(fichas)} fichas cargadas")
    finally:
        client.close()


# ------------------------------------------------------------------ main
def mostra(titulo, filas, cantas=2):
    print(f"\n{titulo}: {len(filas)}")
    for f in filas[:cantas]:
        print(f"  {f}")


def main():
    ap = argparse.ArgumentParser(description="Xera e carga datos de proba de Camiño Aberto")
    ap.add_argument("--albergues", type=int, default=40)
    ap.add_argument("--peregrinos", type=int, default=1500)
    ap.add_argument("--reservas", type=int, default=5000)
    ap.add_argument("--semente", type=int, default=42, help="mesma semente → mesmos datos")
    ap.add_argument("--desde", type=date.fromisoformat, default=date(2027, 5, 1),
                    help="primeira noite da tempada (AAAA-MM-DD)")
    ap.add_argument("--dias", type=int, default=30, help="número de noites da tempada")
    ap.add_argument("--sen-carga", action="store_true", help="xera e mostra, pero non carga nada")
    args = ap.parse_args()

    rng = random.Random(args.semente)
    fake = Faker("es_ES")
    fake.seed_instance(args.semente)

    print(f"Semente {args.semente} · tempada {args.desde} + {args.dias} noites")
    albergues = xera_albergues(args.albergues, rng)
    peregrinos = xera_peregrinos(args.peregrinos, rng, fake)
    reservas = xera_reservas(args.reservas, albergues, peregrinos, args.desde, args.dias, rng)
    fichas = xera_fichas(albergues, rng, fake)

    mostra("Albergues", albergues)
    mostra("Peregrinos", peregrinos)
    mostra("Reservas", reservas)
    mostra("Fichas", fichas, 1)

    if not args.sen_carga:
        carga_postgres(albergues, peregrinos, reservas)
        carga_mongo(fichas)


if __name__ == "__main__":
    main()
