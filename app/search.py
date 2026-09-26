import re
import difflib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.models import Candidate, StageEvent
from app.pipeline import (
    ORDERED_STAGES,
    ALL_STAGES,
    get_history,
    get_candidate_details,
    _ensure_utc,
)

STAGE_NAME_MAP = {s.lower(): s for s in ALL_STAGES}

STAGE_SYNONYMS = {
    "selected": "Hired",
    "hired": "Hired",
    "hiring": "Hired",
    "rejected": "Rejected",
    "rejecting": "Rejected",
    "offered": "Offer",
    "offer": "Offer",
    "interviewed": "Interview",
    "interview": "Interview",
    "interviewing": "Interview",
    "screened": "Screening",
    "screening": "Screening",
    "applied": "Applied",
    "applying": "Applied",
}

DAYS_OF_WEEK = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

INTERROGATIVE_WORDS = {
    "the", "a", "an", "this", "that", "each", "every", "our", "all", "more",
    "which", "what", "where", "how", "when", "why", "whom", "whose", "any",
    "last", "past", "next", "first", "recent", "total",
}

STOP_WORDS = {
    "find", "who", "who's", "is", "are", "were", "was", "the", "a", "an",
    "in", "for", "since", "right", "now", "currently", "stage", "stages",
    "round", "rounds", "phase", "phases", "level", "levels", "status", "pipeline",
    "process", "candidate", "candidates", "manycandidates", "everyone", "all", "people", "person",
    "except", "excluding", "but", "not", "didn't", "did", "got", "get",
    "reached", "reach", "stuck", "been", "waiting", "moved", "more", "than",
    "over", "to", "at", "show", "me", "list", "has", "have", "had",
    "week", "weeks", "day", "days", "month", "months", "year", "years",
    "hour", "hours", "minute", "minutes", "min", "mins", "second", "seconds", "sec", "secs",
    "ago", "past", "last",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "which", "what", "where", "how", "many", "left", "remaining", "active", "still",
    "s", "re", "m", "d", "t", "ll", "ve",
}


@dataclass
class ParsedFilters:
    current_stage: Optional[str] = None
    exclude_stage: Optional[str] = None
    exclude_terminal: bool = False
    stuck_stage: Optional[str] = None
    stuck_min_seconds: Optional[float] = None
    moved_to_stage: Optional[str] = None
    moved_since: Optional[datetime] = None
    reached_stage: Optional[str] = None
    must_not_be_stage: Optional[str] = None
    name_query: Optional[str] = None
    raw_query: str = ""
    error_message: Optional[str] = None
    detected_descriptions: List[str] = field(default_factory=list)


def resolve_stage_name(word: str) -> Optional[str]:
    """
    Resolves a stage word to its canonical name.
    Supports exact matching, recruitment synonyms (e.g. 'selected' -> 'Hired'),
    and typo tolerance (e.g. 'screenig' -> 'Screening').
    """
    w = word.strip().lower()
    if w in STAGE_NAME_MAP:
        return STAGE_NAME_MAP[w]
    if w in STAGE_SYNONYMS:
        return STAGE_SYNONYMS[w]
    
    # Fuzzy match with threshold 0.75 for stage typos
    best_stage = None
    best_ratio = 0.0
    for s in ALL_STAGES:
        ratio = difflib.SequenceMatcher(None, w, s.lower()).ratio()
        if ratio > best_ratio and ratio >= 0.75:
            best_ratio = ratio
            best_stage = s
    return best_stage


def parse_time_duration(phrase: str) -> Optional[float]:
    """Converts a duration phrase like 'a week', '2 days', '3 hours', '5 minutes' into seconds."""
    phrase = re.sub(r"[^\w\s]", "", phrase.strip().lower())
    
    # Weeks
    m = re.search(r"(\d+)\s+weeks?\b", phrase)
    if m:
        return float(m.group(1)) * 7 * 86400
    if re.search(r"\b(?:a\s+week|one\s+week|week)\b", phrase):
        return 7 * 86400

    # Days
    m = re.search(r"(\d+)\s+days?\b", phrase)
    if m:
        return float(m.group(1)) * 86400
    if re.search(r"\b(?:a\s+day|one\s+day|day)\b", phrase):
        return 86400

    # Months
    m = re.search(r"(\d+)\s+months?\b", phrase)
    if m:
        return float(m.group(1)) * 30 * 86400
    if re.search(r"\b(?:a\s+month|one\s+month|month)\b", phrase):
        return 30 * 86400

    # Hours
    m = re.search(r"(\d+)\s+hours?\b", phrase)
    if m:
        return float(m.group(1)) * 3600
    if re.search(r"\b(?:an\s+hour|one\s+hour|hour)\b", phrase):
        return 3600

    # Minutes
    m = re.search(r"(\d+)\s*(?:min(?:ute)?s?|m)\b", phrase)
    if m:
        return float(m.group(1)) * 60
    if re.search(r"\b(?:a\s+minute|one\s+minute|minute|a\s+min)\b", phrase):
        return 60

    # Seconds
    m = re.search(r"(\d+)\s*(?:sec(?:ond)?s?|s)\b", phrase)
    if m:
        return float(m.group(1))
    if re.search(r"\b(?:a\s+second|one\s+second)\b", phrase):
        return 1

    return None


def resolve_since_date(date_str: str, as_of: datetime) -> Optional[datetime]:
    """Resolves relative date words like 'monday', 'yesterday' or relative durations like '5 minutes' into a timezone-aware UTC datetime."""
    cleaned = date_str.strip().lower()
    cleaned = re.sub(r"\bago\b", "", cleaned).strip()
    as_of = _ensure_utc(as_of)

    word = re.sub(r"[^\w]", "", cleaned)

    if word == "yesterday":
        target = as_of - timedelta(days=1)
        return datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=timezone.utc)
    if word in ("today", "now"):
        return datetime(as_of.year, as_of.month, as_of.day, 0, 0, 0, tzinfo=timezone.utc)

    if word in DAYS_OF_WEEK:
        target_weekday = DAYS_OF_WEEK[word]
        current_weekday = as_of.weekday()
        days_back = (current_weekday - target_weekday) % 7
        if days_back == 0:
            days_back = 0
        target = as_of - timedelta(days=days_back)
        return datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=timezone.utc)

    # Relative duration (e.g. "5 minutes", "2 hours", "1 day")
    dur_sec = parse_time_duration(cleaned)
    if dur_sec is not None:
        return as_of - timedelta(seconds=dur_sec)

    return None


def parse_query(raw_query: str, as_of: Optional[datetime] = None) -> ParsedFilters:
    """Parses a free-text search query into structured criteria using rule-based parsing."""
    text_clean = raw_query.strip()
    filters = ParsedFilters(raw_query=text_clean)
    now = _ensure_utc(as_of or datetime.now(timezone.utc))

    if not text_clean:
        filters.error_message = "Please enter a search term, candidate name, or filter question."
        return filters

    lower_query = text_clean.lower()
    consumed_spans = []

    # 0. Direct stage match for queries like "interview", "interviewing", "screening", "screening candidates", "offer stage"
    clean_stage_probe = re.sub(
        r"\b(candidates?|candidate|stage|round|phase|status|pipeline|show|list|all|who|is|are|in|at|the)\b",
        " ",
        lower_query,
    )
    stage_words = re.findall(r"[a-zA-Z]+", clean_stage_probe)
    if len(stage_words) == 1:
        direct_stage = resolve_stage_name(stage_words[0])
        if direct_stage:
            filters.current_stage = direct_stage
            filters.detected_descriptions.append(f"Current stage: {direct_stage}")
            return filters

    # 1. "How many candidates left" / "active candidates" / "remaining in pipeline"
    active_pattern = (
        r"(?:how\s+many\s+)?(?:candidates\s+|manycandidates\s+)?"
        r"(?:left|remaining|active|still\s+(?:active|in\s+process|here))"
    )
    m_active = re.search(active_pattern, lower_query)
    if m_active:
        filters.exclude_terminal = True
        filters.detected_descriptions.append("Active candidates remaining in pipeline")
        consumed_spans.append(m_active.span())

    # 2. Check for invalid stage mentions like "who's in Onboarding", "in X stage", "stuck in X", "moved to X"
    # Note: question words in INTERROGATIVE_WORDS (e.g. "which", "what") are not stages!
    stage_intent_patterns = [
        r"(?:who(?:'s|\s+is|\s+are)?\s+)?(?:in|at)\s+(?:the\s+)?([a-zA-Z]+)(?:\s+(?:stage|round|phase|right\s+now|currently))?",
        r"(?:(?:has\s+been|been)?\s*stuck|been|waiting)\s+(?:in|at)\s+(?:the\s+)?([a-zA-Z]+)",
        r"(?:moved|advanced|transitioned)\s+to\s+(?:the\s+)?([a-zA-Z]+)",
        r"reached\s+(?:the\s+)?([a-zA-Z]+)",
        r"(?:except|excluding)\s+([a-zA-Z]+)",
    ]
    for pattern in stage_intent_patterns:
        for match in re.finditer(pattern, lower_query):
            potential_stage = match.group(1).lower()
            if potential_stage in INTERROGATIVE_WORDS:
                continue
            resolved = resolve_stage_name(potential_stage)
            if not resolved:
                valid_list = ", ".join(ORDERED_STAGES + ["Rejected"])
                stg_display = match.group(1).capitalize()
                filters.error_message = (
                    f"'{stg_display}' is not a recognized pipeline stage. "
                    f"Valid pipeline stages are: {valid_list}."
                )
                return filters

    # 3. Status queries: "who got rejected", "who got selected", "who was hired"
    status_pattern = r"(?:who(?:'s|\s+is|\s+are|\s+got|\s+was|\s+were|\s+became)?\s+)?(?:got\s+|was\s+|were\s+|became\s+)([a-zA-Z]+)"
    for m_st in re.finditer(status_pattern, lower_query):
        word = m_st.group(1)
        canonical = resolve_stage_name(word)
        if canonical:
            filters.current_stage = canonical
            filters.detected_descriptions.append(f"Status: {canonical}")
            consumed_spans.append(m_st.span())

    # 4. Reached-but-not-current ("reached Offer stage but didn't get hired")
    reached_pattern = (
        r"reached\s+(?:the\s+)?([a-zA-Z]+)(?:\s+(?:stage|round|phase))?\s*(?:but|and)?\s*"
        r"(?:didn't|did\s+not|never|without)\s+(?:get\s+)?([a-zA-Z]+)"
    )
    m_reached = re.search(reached_pattern, lower_query)
    if m_reached:
        stg1 = m_reached.group(1)
        stg2 = m_reached.group(2)
        canonical1 = resolve_stage_name(stg1)
        canonical2 = resolve_stage_name(stg2)
        if canonical1 and canonical2:
            filters.reached_stage = canonical1
            filters.must_not_be_stage = canonical2
            filters.detected_descriptions.append(
                f"Reached {canonical1} but current stage != {canonical2}"
            )
            consumed_spans.append(m_reached.span())

    # 5. Negation filter ("everyone except rejected candidates", "except rejected")
    except_pattern = r"(?:everyone\s+|all\s+candidates\s+)?(?:except|excluding|not\s+in)\s+([a-zA-Z]+)(?:\s+candidates)?"
    m_except = re.search(except_pattern, lower_query)
    if m_except:
        stg = m_except.group(1)
        canonical = resolve_stage_name(stg)
        if canonical:
            filters.exclude_stage = canonical
            filters.detected_descriptions.append(f"Excluding stage: {canonical}")
            consumed_spans.append(m_except.span())

    # 6. Stuck in stage for duration ("Who has been stuck in Screening for more than a week?")
    stuck_pattern = (
        r"(?:(?:has\s+been|been)?\s*stuck|been|waiting)\s+(?:in|at)\s+(?:the\s+)?([a-zA-Z]+)(?:\s+(?:stage|round|phase))?\s+(?:for\s+)?(?:more\s+than|over|longer\s+than)\s+([a-zA-Z0-9\s]+?)"
        r"(?:[?.!]|and\s+|who\s+|$)"
    )
    m_stuck = re.search(stuck_pattern, lower_query)
    if m_stuck:
        stg = m_stuck.group(1)
        dur_str = m_stuck.group(2)
        canonical = resolve_stage_name(stg)
        sec = parse_time_duration(dur_str)
        if canonical and sec is not None:
            filters.stuck_stage = canonical
            filters.stuck_min_seconds = sec
            filters.detected_descriptions.append(
                f"In {canonical} for > {dur_str.strip()}"
            )
            consumed_spans.append(m_stuck.span())

    # 7. Moved to stage since date or relative duration ("moved to Interview since Monday", "moved to Interview since 5 minutes")
    moved_pattern = (
        r"(?:moved|advanced|transitioned)\s+to\s+(?:the\s+)?([a-zA-Z]+)(?:\s+(?:stage|round|phase))?\s+(?:since|in\s+the\s+last|in\s+the\s+past|past)\s+([a-zA-Z0-9\s]+?)"
        r"(?:[?.!]|and\s+|who\s+|$)"
    )
    m_moved = re.search(moved_pattern, lower_query)
    if m_moved:
        stg = m_moved.group(1)
        since_str = m_moved.group(2).strip()
        canonical = resolve_stage_name(stg)
        since_dt = resolve_since_date(since_str, now)
        if canonical and since_dt:
            filters.moved_to_stage = canonical
            filters.moved_since = since_dt
            filters.detected_descriptions.append(
                f"Moved to {canonical} since {since_str}"
            )
            consumed_spans.append(m_moved.span())

    # 8. Current stage filter ("who's in Interview right now", "who's in the offer stage", "in screening round")
    in_stage_pattern = r"(?:who(?:'s|\s+is|\s+are)?\s+)?(?:in|at)\s+(?:the\s+)?([a-zA-Z]+)(?:\s+(?:stage|round|phase|right\s+now|currently))?"
    for m_in in re.finditer(in_stage_pattern, lower_query):
        span = m_in.span()
        overlaps = any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in consumed_spans)
        if not overlaps:
            stg = m_in.group(1)
            if stg in INTERROGATIVE_WORDS:
                continue
            canonical = resolve_stage_name(stg)
            if canonical and not filters.stuck_stage and not filters.moved_to_stage and not filters.current_stage:
                filters.current_stage = canonical
                filters.detected_descriptions.append(f"Current stage: {canonical}")
                consumed_spans.append(span)

    # 9. Remaining name query extraction
    char_list = list(text_clean)
    for start, end in consumed_spans:
        for i in range(start, min(end, len(char_list))):
            char_list[i] = " "
    remaining_text = "".join(char_list)

    # Clean out apostrophes like "who's" or "'s"
    remaining_text = re.sub(r"['’]s\b", " ", remaining_text, flags=re.IGNORECASE)

    tokens = re.findall(r"[a-zA-Z0-9]+", remaining_text)
    name_tokens = [t for t in tokens if len(t) > 1 and t.lower() not in STOP_WORDS]
    if name_tokens:
        filters.name_query = " ".join(name_tokens)
        filters.detected_descriptions.append(f"Name query: '{filters.name_query}'")

    # If nothing was detected at all
    if not filters.detected_descriptions and not filters.error_message:
        filters.error_message = (
            f"Could not understand '{text_clean}'. "
            "Try searching by candidate name (e.g. 'Priya Sharma'), "
            "current stage (e.g. 'Who\\'s in Interview right now?'), "
            "status (e.g. 'who got rejected', 'who got selected'), "
            "pipeline progress (e.g. 'how many candidates left'), "
            "duration (e.g. 'stuck in Screening for more than a week'), "
            "transition date (e.g. 'moved to Interview since Monday'), "
            "or exclusion (e.g. 'Everyone except rejected candidates')."
        )

    return filters


def compute_name_score(query_name: str, candidate_name: str) -> float:
    """
    Computes a match score between query_name and candidate_name.
    Returns a score between 0.0 and 1.0 (with 1.0 for exact matches).
    """
    q = query_name.strip().lower()
    c = candidate_name.strip().lower()

    if not q or not c:
        return 0.0

    # 1. Exact full match
    if q == c:
        return 1.0

    # 2. Substring full match
    if q in c:
        return 0.95

    # 3. Token-level comparisons (handles first name, last name, typos)
    q_tokens = q.split()
    c_tokens = c.split()

    # Exact match on any token (e.g. searching "Priya" matches "Priya Sharma")
    for qt in q_tokens:
        for ct in c_tokens:
            if qt == ct:
                return 0.90
            if qt in ct or ct in qt:
                return 0.85

    # 4. Fuzzy typo matching with SequenceMatcher (e.g. "sharam" -> "sharma")
    overall_ratio = difflib.SequenceMatcher(None, q, c).ratio()

    best_token_ratio = 0.0
    for qt in q_tokens:
        for ct in c_tokens:
            ratio = difflib.SequenceMatcher(None, qt, ct).ratio()
            if ratio > best_token_ratio:
                best_token_ratio = ratio

    best_score = max(overall_ratio, best_token_ratio)
    if best_score >= 0.75:
        return round(best_score, 3)

    return 0.0


def search_candidates(
    db: Session, query_text: str, as_of: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Executes a search query against candidates and stage history.
    Combines parsed filters with fuzzy ranking.
    Returns structured results and explanations.
    """
    now = _ensure_utc(as_of or datetime.now(timezone.utc))
    parsed = parse_query(query_text, as_of=now)

    if parsed.error_message:
        return {
            "query": query_text,
            "success": False,
            "explanation": parsed.error_message,
            "filters_applied": [],
            "count": 0,
            "results": [],
        }

    # Fetch all candidates with their details and history
    candidates = db.query(Candidate).all()
    matched_results = []

    for candidate in candidates:
        details = get_candidate_details(db, candidate.id, as_of=now)
        current_stage = details["current_stage"]
        history = details["history"]
        time_in_stage = details["time_in_current_stage_seconds"]

        # Filter: Exclude terminal states (for "how many candidates left")
        if parsed.exclude_terminal and current_stage in ("Hired", "Rejected"):
            continue

        # Filter 1: current_stage
        if parsed.current_stage and current_stage != parsed.current_stage:
            continue

        # Filter 2: exclude_stage
        if parsed.exclude_stage and current_stage == parsed.exclude_stage:
            continue

        # Filter 3: stuck in stage for min duration
        if parsed.stuck_stage:
            if current_stage != parsed.stuck_stage:
                continue
            if parsed.stuck_min_seconds and time_in_stage < parsed.stuck_min_seconds:
                continue

        # Filter 4: moved to stage since datetime
        if parsed.moved_to_stage:
            matching_moves = [
                e for e in history
                if e["to_stage"] == parsed.moved_to_stage
                and (parsed.moved_since is None or _ensure_utc(e["timestamp"]) >= parsed.moved_since)
            ]
            if not matching_moves:
                continue

        # Filter 5: reached_stage and must_not_be_stage
        if parsed.reached_stage:
            reached_events = [e for e in history if e["to_stage"] == parsed.reached_stage]
            if not reached_events:
                continue
            if parsed.must_not_be_stage and current_stage == parsed.must_not_be_stage:
                continue

        # Filter 6: Name query (exact or fuzzy)
        name_score = 0.0
        if parsed.name_query:
            name_score = compute_name_score(parsed.name_query, candidate.name)
            if name_score < 0.75:
                continue

        # Base ranking score: 100 for satisfying structured criteria + up to 100 based on name match
        total_score = 100.0
        if parsed.name_query:
            total_score += (name_score * 100.0)

        matched_results.append({
            "candidate": details,
            "score": total_score,
            "name_match_score": name_score,
        })

    # Sort results: highest score first, then candidate name ascending
    matched_results.sort(key=lambda r: (-r["score"], r["candidate"]["name"]))

    explanation = None
    if not matched_results:
        applied_desc = ", ".join(parsed.detected_descriptions)
        explanation = f"No candidates found matching criteria: {applied_desc}."

    return {
        "query": query_text,
        "success": True,
        "explanation": explanation,
        "filters_applied": parsed.detected_descriptions,
        "count": len(matched_results),
        "results": [r["candidate"] for r in matched_results],
    }
