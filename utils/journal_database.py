# -*- coding: utf-8 -*-
"""Local journal catalog loader and matcher for EdgeRef.

This module matches a target journal name against local CSV catalog files.
It supports international and Chinese journal lists such as SCIE, SSCI,
AHCI, CSSCI, PKU Core, CSCD, AMI, Chinese Science and Technology Core,
and EI Compendex when administrators place CSV catalogs under
``data/journal_catalogs/``.

No internet lookup is performed. A match means the journal was found in the
local catalog files bundled with or supplied to this app; it should still be
verified against the latest official directory before submission.
"""

from __future__ import annotations

import csv
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_CATALOG_DIR = os.path.join(_DATA_DIR, "journal_catalogs")
_SAMPLE_CSV = os.path.join(_DATA_DIR, "chinese_core_journals_sample.csv")

CATALOG_FIELDS = [
    "journal_name",
    "normalized_name",
    "database",
    "database_type",
    "version",
    "subject_area",
    "discipline_code",
    "issn",
    "eissn",
    "cn",
    "publisher",
    "language",
    "journal_code",
    "source_file",
    "source_sheet",
    "source_page",
    "notes",
]

_FULL_TO_HALF = str.maketrans({
    "\uff01": "!", "\uff02": '"', "\uff03": "#", "\uff04": "$",
    "\uff05": "%", "\uff06": "&", "\uff07": "'", "\uff08": "(",
    "\uff09": ")", "\uff0a": "*", "\uff0b": "+", "\uff0c": ",",
    "\uff0d": "-", "\uff0e": ".", "\uff0f": "/", "\uff10": "0",
    "\uff11": "1", "\uff12": "2", "\uff13": "3", "\uff14": "4",
    "\uff15": "5", "\uff16": "6", "\uff17": "7", "\uff18": "8",
    "\uff19": "9", "\uff1a": ":", "\uff1b": ";", "\uff1c": "<",
    "\uff1d": "=", "\uff1e": ">", "\uff1f": "?", "\uff20": "@",
    "\uff21": "A", "\uff22": "B", "\uff23": "C", "\uff24": "D",
    "\uff25": "E", "\uff26": "F", "\uff27": "G", "\uff28": "H",
    "\uff29": "I", "\uff2a": "J", "\uff2b": "K", "\uff2c": "L",
    "\uff2d": "M", "\uff2e": "N", "\uff2f": "O", "\uff30": "P",
    "\uff31": "Q", "\uff32": "R", "\uff33": "S", "\uff34": "T",
    "\uff35": "U", "\uff36": "V", "\uff37": "W", "\uff38": "X",
    "\uff39": "Y", "\uff3a": "Z", "\uff3b": "[", "\uff3c": "\\",
    "\uff3d": "]", "\uff3e": "^", "\uff3f": "_", "\uff40": "`",
    "\uff41": "a", "\uff42": "b", "\uff43": "c", "\uff44": "d",
    "\uff45": "e", "\uff46": "f", "\uff47": "g", "\uff48": "h",
    "\uff49": "i", "\uff4a": "j", "\uff4b": "k", "\uff4c": "l",
    "\uff4d": "m", "\uff4e": "n", "\uff4f": "o", "\uff50": "p",
    "\uff51": "q", "\uff52": "r", "\uff53": "s", "\uff54": "t",
    "\uff55": "u", "\uff56": "v", "\uff57": "w", "\uff58": "x",
    "\uff59": "y", "\uff5a": "z", "\uff5b": "{", "\uff5c": "|",
    "\uff5d": "}", "\uff5e": "~", "\u3000": " ", "\u3002": ".",
})

_BOOK_MARKS_RE = re.compile(r"^[\"'“”‘’《》〈〉「」『』]+|[\"'“”‘’《》〈〉「」『』]+$")


def normalize_journal_name(name: str) -> str:
    """Normalize a journal name for display-level matching."""
    if not name:
        return ""
    n = str(name).strip().lower().translate(_FULL_TO_HALF)
    n = _BOOK_MARKS_RE.sub("", n)
    n = re.sub(r"[\u300a\u300b\u3008\u3009()（）\[\]【】{}<>]", " ", n)
    n = re.sub(r"&", " and ", n)
    n = re.sub(r"[’'`´]", "", n)
    n = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _compact(name: str) -> str:
    return re.sub(r"\s+", "", normalize_journal_name(name or ""))


def _empty_result(journal_name: str = "", warning: str = "") -> Dict[str, Any]:
    return {
        "match_status": "not_checked" if not journal_name else "not_matched",
        "confidence": "" if not journal_name else "Not matched",
        "input_journal_name": (journal_name or "").strip(),
        "matched_journal_name": "",
        "database": "",
        "database_type": "",
        "version": "",
        "subject_area": "",
        "discipline_code": "",
        "issn": "",
        "eissn": "",
        "cn": "",
        "publisher": "",
        "language": "",
        "journal_code": "",
        "source_file": "",
        "source_sheet": "",
        "source_page": "",
        "notes": "Not found in the local journal catalog." if journal_name else "",
        "warning": warning,
        "match_count": 0,
        "match_records": [],
        "database_summary": "",
    }


def _clean_entry(row: Dict[str, Any], source_file: str = "") -> Dict[str, str]:
    entry = {field: str(row.get(field, "") or "").strip() for field in CATALOG_FIELDS}
    # Backward compatibility with older/sample field names.
    if not entry["database_type"]:
        entry["database_type"] = str(row.get("category", "") or "").strip()
    if not entry["source_file"]:
        entry["source_file"] = source_file
    if not entry["normalized_name"]:
        entry["normalized_name"] = normalize_journal_name(entry["journal_name"])
    return entry


def load_catalog_csv(file_path: str) -> List[Dict[str, str]]:
    """Load one catalog CSV file. Invalid rows are skipped safely."""
    if not file_path or not os.path.exists(file_path):
        return []
    entries: List[Dict[str, str]] = []
    try:
        with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "journal_name" not in reader.fieldnames:
                return []
            for row in reader:
                try:
                    entry = _clean_entry(row, os.path.basename(file_path))
                    if entry["journal_name"]:
                        entries.append(entry)
                except Exception:
                    continue
    except Exception:
        return []
    return entries


def load_all_catalogs(catalog_dir: Optional[str] = None) -> List[Dict[str, str]]:
    """Load all CSV catalogs in the configured catalog directory."""
    path = catalog_dir or _CATALOG_DIR
    if not os.path.isdir(path):
        return []
    entries: List[Dict[str, str]] = []
    csv_files = sorted(f for f in os.listdir(path) if f.lower().endswith(".csv"))
    for fname in csv_files:
        # Template files may be header-only; loading them is harmless.
        entries.extend(load_catalog_csv(os.path.join(path, fname)))
    return _dedupe_entries(entries)


@lru_cache(maxsize=1)
def load_journal_database() -> List[Dict[str, str]]:
    """Load catalog entries once per Python process.

    This avoids reparsing a large catalog CSV on every Streamlit rerun. If an
    administrator replaces catalog files while the app is running, restart the
    app to reload the catalog.
    """
    entries = load_all_catalogs()
    if entries:
        return entries
    return _dedupe_entries(load_catalog_csv(_SAMPLE_CSV))


def _entry_key(entry: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
    return (
        _compact(entry.get("journal_name", "")),
        entry.get("database", ""),
        entry.get("database_type", ""),
        entry.get("version", ""),
        entry.get("issn", ""),
        entry.get("cn", ""),
    )


def _dedupe_entries(entries: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for entry in entries:
        key = _entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def fuzzy_match_journal_name(journal_name: str, candidates: List[str], cutoff: float = 0.75) -> List[Tuple[float, str]]:
    """Fuzzy match a normalized journal name against normalized candidates."""
    if not journal_name or not candidates:
        return []
    results: List[Tuple[float, str]] = []
    for candidate in candidates:
        if not candidate:
            continue
        ratio = SequenceMatcher(None, journal_name, candidate).ratio()
        if ratio >= cutoff:
            results.append((ratio, candidate))
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def _entry_norm(entry: Dict[str, str]) -> str:
    # Some generated catalogs store compact normalized names. Normalize again
    # to keep older and newer files comparable.
    return normalize_journal_name(entry.get("normalized_name") or entry.get("journal_name") or "")


def _entry_compact(entry: Dict[str, str]) -> str:
    return _compact(entry.get("normalized_name") or entry.get("journal_name") or "")


def _rank_database(entry: Dict[str, str]) -> int:
    order = {
        "CSSCI": 1,
        "PKU Core": 2,
        "CSCD": 3,
        "Chinese Science and Technology Core": 4,
        "AMI": 5,
        "SCIE": 6,
        "SSCI": 7,
        "AHCI": 8,
        "EI Compendex": 9,
    }
    return order.get(entry.get("database", ""), 99)


def _select_matches(query: str, database: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]], str]:
    q_norm = normalize_journal_name(query)
    q_compact = _compact(query)
    if not q_norm or not q_compact:
        return "", [], ""

    exact = [e for e in database if _entry_norm(e) == q_norm or _entry_compact(e) == q_compact]
    if exact:
        return "Exact", exact, ""

    high = [e for e in database if _entry_compact(e) == q_compact]
    if high:
        return "High", high, ""

    medium = []
    for e in database:
        en = _entry_compact(e)
        if not en:
            continue
        # Avoid very short substring false positives.
        if len(q_compact) >= 4 and (q_compact in en or en in q_compact):
            medium.append(e)
    if medium:
        return "Medium", medium[:20], "Substring match; verify the journal name manually."

    candidate_map = {_entry_compact(e): e for e in database if _entry_compact(e)}
    fuzzy = fuzzy_match_journal_name(q_compact, list(candidate_map.keys()), cutoff=0.82)
    if fuzzy:
        best_ratio = fuzzy[0][0]
        best_candidates = [name for ratio, name in fuzzy if ratio == best_ratio][:10]
        matches = [candidate_map[name] for name in best_candidates]
        return "Low", matches, f"Fuzzy match confidence: {best_ratio:.0%}; verify manually."

    return "Not matched", [], ""


def _record_from_entry(entry: Dict[str, str], confidence: str) -> Dict[str, str]:
    record = {field: entry.get(field, "") for field in CATALOG_FIELDS}
    record["confidence"] = confidence
    return record


def _database_summary(records: List[Dict[str, str]]) -> str:
    parts = []
    for rec in records:
        db = rec.get("database", "")
        db_type = rec.get("database_type", "")
        ver = rec.get("version", "")
        label = db
        if db_type:
            label += f" ({db_type})"
        if ver:
            label += f" {ver}"
        if label and label not in parts:
            parts.append(label)
    return "; ".join(parts)


def match_chinese_core_journal(journal_name: str, database: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Match a target journal against the local journal catalog.

    The function name is kept for backward compatibility with earlier EdgeRef
    versions, but the catalog can now include SCIE, SSCI, AHCI, CSSCI, PKU Core,
    CSCD, AMI, Chinese Science and Technology Core, EI Compendex, and other
    local CSV sources.
    """
    if not journal_name or not str(journal_name).strip():
        return _empty_result("")

    db = database if database is not None else load_journal_database()
    if not db:
        result = _empty_result(journal_name, "Journal catalog is empty or could not be loaded.")
        result["match_status"] = "not_checked"
        return result

    confidence, raw_matches, warning = _select_matches(str(journal_name).strip(), db)
    if not raw_matches:
        result = _empty_result(journal_name)
        result["match_status"] = "not_matched"
        result["confidence"] = "Not matched"
        return result

    raw_matches = sorted(_dedupe_entries(raw_matches), key=lambda e: (_rank_database(e), e.get("database", ""), e.get("journal_name", "")))
    records = [_record_from_entry(e, confidence) for e in raw_matches]
    primary = records[0]

    return {
        "match_status": "matched",
        "confidence": confidence,
        "input_journal_name": str(journal_name).strip(),
        "matched_journal_name": primary.get("journal_name", ""),
        "database": _database_summary(records),
        "database_type": primary.get("database_type", ""),
        "version": primary.get("version", ""),
        "subject_area": primary.get("subject_area", ""),
        "discipline_code": primary.get("discipline_code", ""),
        "issn": primary.get("issn", ""),
        "eissn": primary.get("eissn", ""),
        "cn": primary.get("cn", ""),
        "publisher": primary.get("publisher", ""),
        "language": primary.get("language", ""),
        "journal_code": primary.get("journal_code", ""),
        "source_file": primary.get("source_file", ""),
        "source_sheet": primary.get("source_sheet", ""),
        "source_page": primary.get("source_page", ""),
        "notes": "Matched in the local journal catalog. Please verify with the official/latest directory before submission.",
        "warning": warning,
        "match_count": len(records),
        "match_records": records,
        "database_summary": _database_summary(records),
    }


def get_journal_match_summary(match_result: Optional[Dict[str, Any]]) -> str:
    """Return a Markdown summary for display and prompt context."""
    if not match_result:
        return ""

    status = match_result.get("match_status", "not_checked")
    lines = ["### Journal Catalog Match", ""]

    if status == "matched":
        lines.append("- **Match status**: Matched")
        lines.append(f"- **Confidence**: {match_result.get('confidence', '')}")
        lines.append(f"- **Matched records**: {match_result.get('match_count', 1)}")
        dbs = match_result.get("database_summary") or match_result.get("database", "")
        if dbs:
            lines.append(f"- **Catalog/database**: {dbs}")

        records = match_result.get("match_records") or []
        for idx, rec in enumerate(records[:10], start=1):
            bits = [f"{idx}. {rec.get('journal_name', '')}"]
            db = rec.get("database", "")
            db_type = rec.get("database_type", "")
            ver = rec.get("version", "")
            if db:
                bits.append(f"Database: {db}")
            if db_type:
                bits.append(f"Type: {db_type}")
            if ver:
                bits.append(f"Version: {ver}")
            if rec.get("subject_area"):
                bits.append(f"Subject: {rec.get('subject_area')}")
            if rec.get("issn"):
                bits.append(f"ISSN: {rec.get('issn')}")
            if rec.get("eissn"):
                bits.append(f"eISSN: {rec.get('eissn')}")
            if rec.get("cn"):
                bits.append(f"CN: {rec.get('cn')}")
            if rec.get("journal_code"):
                bits.append(f"Code: {rec.get('journal_code')}")
            lines.append("- " + " | ".join(bits))
        if len(records) > 10:
            lines.append(f"- More matches are available in the local catalog ({len(records)} total).")
        if match_result.get("warning"):
            lines.append(f"- **Warning**: {match_result.get('warning')}")
        lines.append("- **Note**: Please verify with the official/latest directory or institutional research office before submission.")
    elif status == "not_matched":
        lines.append("- **Match status**: Not matched")
        lines.append("- **Note**: Not found in the local journal catalog. This does not prove the journal is not indexed/core; verify with the official/latest directory.")
    else:
        lines.append("- **Match status**: Not checked")
        if match_result.get("warning"):
            lines.append(f"- **Warning**: {match_result.get('warning')}")

    return "\n".join(lines)

def get_catalog_stats():
    """Return cached catalog statistics.

    Uses the cached journal database loader so the displayed record count matches
    the deduplicated records used for matching.
    """
    import os as _os
    stats = {
        "total_records": None,
        "source_file": "",
        "catalog_dir_exists": _os.path.isdir(_CATALOG_DIR),
        "master_file_exists": False,
        "sample_used": True,
        "warning": "",
    }
    master_csv = _os.path.join(_CATALOG_DIR, "journal_catalog_master.csv")
    stats["master_file_exists"] = _os.path.exists(master_csv)
    stats["source_file"] = master_csv if stats["master_file_exists"] else ""
    try:
        records = load_journal_database()
        stats["total_records"] = len(records)
        stats["sample_used"] = not stats["master_file_exists"]
        if not records:
            stats["warning"] = "Journal catalog is empty. Journal matching will use fallback data only."
    except Exception:
        stats["warning"] = "Could not load journal catalog. Journal matching will use fallback data only."

    if not stats["master_file_exists"] and not stats["warning"]:
        csv_count = len([f for f in _os.listdir(_CATALOG_DIR) if f.lower().endswith(".csv")]) if _os.path.isdir(_CATALOG_DIR) else 0
        stats["warning"] = "Master file not found; using other catalog files." if csv_count > 0 else "Journal catalog directory is empty. Using fallback sample data."
    return stats


def clear_catalog_cache():
    """Invalidate the LRU cache for load_journal_database()."""
    load_journal_database.cache_clear()

