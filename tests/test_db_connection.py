import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

database_url = os.getenv("DATABASE_URL")
print(f"Connecting to database (URL defined: {bool(database_url)})...")

try:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1;")).scalar()
        print(f"Connection test successful! SELECT 1 returned: {result}")
except Exception as e:
    print(f"Connection failed: {e}")
