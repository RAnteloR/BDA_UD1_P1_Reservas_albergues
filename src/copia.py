
import os
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
COPY_DIR = BASE_DIR / "copias"
COPY_DIR.mkdir(exist_ok=True)

date = datetime.now().strftime("%Y%m%d_%H%M%S")

PG_USER = os.getenv("POSTGRES_USER")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD")
PG_DB = os.getenv("POSTGRES_DB")

MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")

def segurity_copy_postgresql():

    file = COPY_DIR / f"postgres_{date}.dump"

    env = os.environ.copy()

    # IN POstgreSQL read PGPASSWORD automatically and not POSTGRES_PASSWORD
    env["PGPASSWORD"] = PG_PASSWORD

    subprocess.run([
        "pg_dump",
        "-h", "localhost",
        "-p", "5432",
        "-U", PG_USER,
        "-d", PG_DB,
        "-F", "c",
        "-f", str(file)
    ], check=True, env=env)


def security_copy_mongo():

    file = COPY_DIR / f"mongodb_{date}.archive"

    with open(file, "wb") as f:
        subprocess.run([
            "docker", "compose", "exec", "-T", "mongo",
            "mongodump",
            "--username", MONGO_USER,
            "--password", MONGO_PASSWORD,
            "--authenticationDatabase", "admin",
            "--db", "festival",
            "--archive",
            "--gzip"
        ], stdout=f, check=True)



def do_secutity_copy():
    segurity_copy_postgresql()
    security_copy_mongo()


if __name__ == "__main__":
    do_secutity_copy()
