import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.models import SessionLocal

db = SessionLocal()

print("=" * 115)
print("1. CANDIDATES TABLE (SELECT * FROM candidates LIMIT 5;)")
print("=" * 115)
candidates = db.execute(text("SELECT id, name, email, created_at FROM candidates LIMIT 5;")).fetchall()
header_cand = f"| {'id':<36} | {'name':<16} | {'email':<26} | {'created_at'} |"
print(header_cand)
print("|" + "-" * 38 + "|" + "-" * 18 + "|" + "-" * 28 + "|" + "-" * 32 + "|")
for row in candidates:
    print(f"| {str(row[0]):<36} | {str(row[1]):<16} | {str(row[2]):<26} | {str(row[3])} |")

print("\n" + "=" * 135)
print("2. STAGE_EVENTS TABLE (SELECT * FROM stage_events ORDER BY timestamp ASC LIMIT 5;)")
print("=" * 135)
events = db.execute(text("SELECT id, candidate_id, from_stage, to_stage, timestamp FROM stage_events ORDER BY timestamp ASC LIMIT 5;")).fetchall()
header_evt = f"| {'id':<36} | {'candidate_id':<36} | {'from_stage':<12} | {'to_stage':<12} | {'timestamp'} |"
print(header_evt)
print("|" + "-" * 38 + "|" + "-" * 38 + "|" + "-" * 14 + "|" + "-" * 14 + "|" + "-" * 32 + "|")
for row in events:
    from_s = str(row[2]) if row[2] is not None else "NULL"
    print(f"| {str(row[0]):<36} | {str(row[1]):<36} | {from_s:<12} | {str(row[3]):<12} | {str(row[4])} |")

print("=" * 135)
db.close()
