### 4.4 Restoration Test

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





