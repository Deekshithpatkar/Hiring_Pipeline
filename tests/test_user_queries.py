import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.search import parse_query

queries = [
    "who's in the offer stage",
    "who's in the screenig round",
    "who's in screening round?",
    "who's in onboarding",
]

for q in queries:
    p = parse_query(q)
    print(f"'{q}' => stage={p.current_stage} | name={p.name_query} | error={p.error_message}")
