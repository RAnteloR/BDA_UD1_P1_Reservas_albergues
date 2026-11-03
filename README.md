# Camiño Aberto · rede de albergues

Proxecto con tres bases de datos coordinadas (PostgreSQL, Redis e MongoDB) para xestionar as reservas dunha rede ficticia de albergues do Camiño de Santiago.

## 1. Arquitectura

| Sistema | Que garda | Por que alí |
|---|---|---|
| **PostgreSQL 17** | `albergues`, `peregrinos`, `reservas` (verdade do negocio) | Datos relacionais con integridade: claves foráneas, `UNIQUE (peregrino_id, noite)` (un peregrino non reserva dous albergues a mesma noite) e `CHECK` nas prazas. As reservas deben ser duradeiras e transaccionais. |
| **Redis 7.4** | Contador de prazas libres por (albergue, noite) e caché das consultas de dispoñibilidade por camiño e noite | `DECR` é atómico: serializa as reservas concorrentes sen bloqueos e evita a sobreventa. Ler da memoria é máis rápido que agregar en SQL. Arranca con AOF (`appendonly yes`) para non perder os contadores ao reiniciar. |
| **MongoDB 8** | `fichas`: unha ficha descritiva por albergue | A información varía moito entre albergues (públicos sinxelos, privados con servizos, opinións, bicicletas...). Un documento flexible evita táboas con moitas columnas nulas. |

Redis **non é a fonte de verdade**: os contadores recalcúlanse desde PostgreSQL (`python src/__init__.py start`), creando un por cada albergue e cada noite da tempada, tamén as que aínda non teñen reservas. Adminer (opcional) dá unha interface web a PostgreSQL en http://localhost:8080.

## 2. Como arrancar e xerar os datos

```bash
cp .env.example .env            # cambia os contrasinais
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d            # postgres, redis, mongo e adminer
python -m src.xera_datos        # xera e carga PostgreSQL + MongoDB
python src/__init__.py start    # calcula os contadores de prazas en Redis
```

O xerador acepta `--albergues` (40), `--peregrinos` (1500), `--reservas` (5000), `--semente` (42), `--desde` (2027-05-01), `--dias` (30) e `--sen-carga` (só xera e mostra). A mesma semente produce sempre os mesmos datos. Con valores por defecto cárganse 40 albergues, 1500 peregrinos, 4714 reservas (5000 intentos; descártanse os que incumpren as regras) e 40 fichas.

Outros comandos de `src/__init__.py`: `reserva` (unha reserva), `simulate` (proba de sobreventa) e `consult` (consulta con caché). Todos aceptan `[albergue_id] [noite AAAA-MM-DD]`; se se omiten, escóllese ao azar un albergue e unha noite existentes en PostgreSQL. Nada vai fixo no código: o camiño sácase do albergue elixido e os peregrinos son ids reais consultados en PostgreSQL que non teñen reserva esa noite.

```bash
python src/__init__.py simulate 13 2027-05-02   # albergue 13, noite 2027-05-02
```

## 3. Decisións tomadas

**Claves de Redis**

| Clave | Tipo | TTL | Uso |
|---|---|---|---|
| `prazas:<albergue_id>:<noite>` | enteiro | sen TTL | Prazas libres. Réstase con `DECR` ao reservar e devólvese con `INCR` se non hai praza ou falla o INSERT. |
| `booking_left:albergue:<camino>:<noite>` | lista | **15 s** | Caché da consulta "albergues e prazas libres dun camiño nunha noite". Se existe responde Redis; se non, SQL e énchese a caché. |
| `disp:<albergue_id>:<noite>` | enteiro | sen TTL | Só para as medicións (`src/medicions.py`), co mesmo significado que `prazas:`. |

- O contador non caduca porque é estado vivo que non se pode perder; a caché de consultas si, e con TTL curto (15 s) porque as prazas cambian con cada reserva: unha lista vella só pode estar desfasada ata 15 s.
- O nome inclúe albergue e noite para consultar unha única praza en O(1).

**Estrutura das fichas (MongoDB, colección `fichas`)**: un documento por albergue, con índice único en `albergue_id`.
- Campos comúns: `albergue_id`, `nome`, `camino`, `servizos`, `horario {apertura, peche}`.
- Públicos (~40 %): só os comúns máis `titularidade` (Xunta, Concello, Deputación).
- Privados (~60 %): máis servizos, `contacto {telefono, web?}` e, opcionalmente, `admite_cans`, `bicicletas {garaxe, prazas}`, `idiomas` e `opinions [{autor, nota, texto}]`. As opinións van incrustadas porque sempre se len coa ficha.

**Reservas e concorrencia**: primeiro réstase o contador en Redis (atómico); só se o resultado é >= 0 se insire en PostgreSQL. Se o INSERT falla (p. ex. peregrino duplicado) devólvese a praza con `INCR`.

## 4. Proba de sobreventa

10 fíos intentan reservar á vez o albergue 13 na noite 2027-05-02, cada un cun peregrino real distinto consultado en PostgreSQL. Para forzar a escaseza déixase o contador en 3 prazas:

```bash
docker compose exec redis redis-cli set prazas:13:2027-05-02 3
python src/__init__.py simulate 13 2027-05-02
```

Resultado obtido:

```
reservas        albergue 13 · noite 2027-05-02 · entradas: 3 · vendidas:  3 · contador final: 0
```

De 10 intentos concorrentes vendéronse exactamente 3 (as prazas dispoñibles); o contador quedou en 0 e en PostgreSQL só se inseriron 3 reservas novas. Non hai sobreventa. Se se executa `simulate` sen argumentos, o albergue e a noite saen ao azar e normalmente quedan moitas prazas, polo que non se ve a escaseza: para a proba hai que baixar o contador como arriba. Para repetila hai que volver executar `python src/__init__.py start`.

## 5. Proba de restauración

**1. Copy creation**


```bash
python src/copia.py
```

This command must create security files in `copias/`.

**2. Restoration Test on PostgreSQL**

Delete some data to comprobate that copy works

```bash
docker compose exec %POSTGRES_SERVICE_NAME psql -U %USER -d %DB -c "DROP TABLE peregrinos CASCADE"
```


```bash
docker compose exec %POSTGRES_SERVICE_NAME psql -U %USER -d %DB -c "SELECT * FROM peregrinos"
```
This must return no data or an error, and now you must
restore the copy to the database with
 `pg_restore`.

```bash
docker compose exec -T %POSTGRES_SERVICE_NAME pg_restore \
  --clean \
  --if-exists \
  -U %USER \
  -d %DB $ \
  < copias/%FILE.dump
```

Comprobate again that the restore was successfuly

```bash
docker compose exec %POSTGRES_SERVICE_NAME psql -U %USER -d %DB -c "SELECT * FROM peregrinos"
```

And this will return all the restored data to you

**3. Restoration Test on MongoDB**

Delete some data to comprobate that copy works

```bash
docker compose exec %MONGO_SERVICE_NAME mongosh -u %USER -p --authenticationDatabase admin %DB --eval "db.fichas.deleteMany({})" 
```


```bash
docker compose exec %MONGO_SERVICE_NAME mongosh -u %USER -p --authenticationDatabase admin %DB --eval "db.fichas.find().toArray()"
```

This must return no data or an error, and now you must
restore the copy to the database with `mongorestore`:

```bash
docker compose exec -T mongo mongorestore \
  --username %USER \
  --password %PASSWORD \
  --authenticationDatabase admin \
  --archive \
  --gzip \
  --drop \
  < copias/%FILE
```

Comprobate again that the restore was successfuly

```bash
docker compose exec %MONGO_SERVICE_NAME mongosh -u %USER -p --authenticationDatabase admin %DB --eval "db.fichas.find().toArray()"
```
And this will return all the restored data to you

## 6. Medicións

`python -m src.medicions` (2000 consultas aleatorias de prazas libres dun albergue nunha noite, con quentamento e comprobación de que ambos sistemas devolven o mesmo). Datos: 40 albergues x 30 noites = 1200 contadores.

| Sistema    | Consultas | Media (ms) | Mediana (ms) | P95 (ms) |
|------------|-----------|-----------|--------------|----------|
| PostgreSQL |      2000 |     0.271 |        0.254 |    0.348 |
| Redis      |      2000 |     0.203 |        0.185 |    0.299 |

`docker stats` tras as medicións:

| Contedor | CPU | Memoria | Net I/O | Block I/O |
|---|---|---|---|---|
| albergues_postgres | 0.00 % | 59.9 MiB | 2.22 MB / 1.16 MB | 77.8 MB / 33.5 MB |
| albergues_redis | 0.20 % | 14.2 MiB | 1.37 MB / 862 kB | 37 MB / 766 kB |
| albergues_mongo | 0.38 % | 291.5 MiB | 60.8 kB / 9.84 kB | 327 MB / 9.33 MB |

Redis é ~25 % máis rápido de media (0,203 ms fronte a 0,271 ms), pero a diferenza é pequena: con 4714 reservas e o índice `idx_reservas_albergue_noite` PostgreSQL xa responde de media en menos de 0,3 ms (P95 0,348 ms), e ambos miden tamén a latencia local do cliente Python. A vantaxe real de Redis é a atomicidade do contador baixo concorrencia e que descarga a PostgreSQL; crecería co volume de datos.

## 7. Uso da IA

Utilizouse Claude Code (Anthropic) como axuda. Neste apartado empregouse para: redactar este README a partir do código, executar as medicións e a proba de sobreventa, e corrixir erros que impedían a proba: (1) en `src/__init__.py`, `simulate` facía `sum()` de cadeas (agora conta as reservas "Create successfuly"), os ids de peregrino, albergue, noite e camiño estaban fixos ou inventados con `random` (agora saen de PostgreSQL) e `start` non creaba contador para albergues/noites sen reservas (agora usa `LEFT JOIN`); (2) en `src/xera_datos.py`, a secuencia `SERIAL` de `reservas` non avanzaba tras cargar ids explícitos e os novos INSERT chocaban coa PK (agora faise `setval`). Todo o código e resultados foron revisados e executados polo equipo. <!-- Completar co uso da IA no resto do proxecto -->
