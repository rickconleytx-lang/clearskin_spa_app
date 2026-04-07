import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host="localhost",
        database="clearskin_spa",
        user=os.environ.get("LOCAL_DB_USER", "postgres"),
        password=os.environ.get("LOCAL_DB_PASSWORD")
    )
