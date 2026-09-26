import re
import difflib

ORDERED_STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired"]
ALL_STAGES = ORDERED_STAGES + ["Rejected"]
STAGE_MAP = {s.lower(): s for s in ALL_STAGES}

STAGE_SYNONYMS = {
    "selected": "Hired",
    "hired": "Hired",
    "rejected": "Rejected",
    "offered": "Offer",
    "interviewed": "Interview",
    "screened": "Screening",
}

def resolve_stage(word):
    w = word.strip().lower()
    if w in STAGE_MAP:
        return STAGE_MAP[w]
    if w in STAGE_SYNONYMS:
        return STAGE_SYNONYMS[w]
    for s in ALL_STAGES:
        if difflib.SequenceMatcher(None, w, s.lower()).ratio() >= 0.75:
            return s
    return None

test_cases = [
    "how manycandidates left",
    "how many candidates left",
    "in which round is shreyas",
    "who got rejected",
    "who got selected",
    "who's in the offer stage",
    "who's in the screenig round",
    "who's in onboarding",
]

# 1. Active / remaining candidates
active_pattern = r"(?:how\s+many\s+)?(?:candidates\s+|manycandidates\s+)?(?:left|remaining|active|still\s+(?:active|in\s+process))"

# 2. Got / was / were status
status_pattern = r"(?:who\s+)?(?:got|was|were|became|is|are)\s+([a-zA-Z]+)"

# 3. Interrogative words to exclude
INTERROGATIVES = {"the", "a", "an", "this", "that", "which", "what", "where", "how", "when", "why", "whom", "whose", "any"}

for q in test_cases:
    lq = q.lower()
    m_act = re.search(active_pattern, lq)
    if m_act:
        print(f"'{q}' => ACTIVE/REMAINING CANDIDATES FILTER")
        continue

    m_status = re.search(status_pattern, lq)
    if m_status:
        stg_word = m_status.group(1)
        stg = resolve_stage(stg_word)
        if stg:
            print(f"'{q}' => STATUS FILTER: {stg}")
            continue

    # In which round is ...
    # Test stage patterns
    in_pattern = r"(?:who(?:'s|\s+is|\s+are)?\s+)?(?:in|at)\s+(?:the\s+)?([a-zA-Z]+)(?:\s+(?:stage|round|phase|right\s+now|currently))?"
    m_in = re.search(in_pattern, lq)
    if m_in:
        word = m_in.group(1)
        if word in INTERROGATIVES:
            # Not a stage intent, e.g. 'in which round'
            # Remaining tokens will be extracted as name
            tokens = [t for t in re.findall(r'[a-zA-Z0-9]+', q) if t.lower() not in {"in", "which", "round", "is", "stage", "who"}]
            name = " ".join(tokens)
            print(f"'{q}' => INTERROGATIVE QUESTION, NAME: '{name}'")
            continue
        else:
            stg = resolve_stage(word)
            if stg:
                print(f"'{q}' => STAGE FILTER: {stg}")
            else:
                print(f"'{q}' => UNRECOGNIZED STAGE: '{word}'")
            continue

    print(f"'{q}' => FALLTHROUGH")
