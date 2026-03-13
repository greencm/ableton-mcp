# MCP_Server/style_index.py — Browser index persistence, search, palette loading, session scoring
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("AbletonMCPServer")

DATA_DIR = Path(__file__).parent / "data"
INDEX_PATH = DATA_DIR / "browser_index.json"
PALETTES_PATH = Path(__file__).parent.parent / "palettes.json"


# ── Index persistence ──────────────────────────────────────────

def save_index(crawl_result: Dict[str, Any]) -> Dict[str, Any]:
    """Save crawl results to browser_index.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    categories = crawl_result.get("categories", {})
    stats = {k: len(v) for k, v in categories.items()}
    stats["total"] = sum(stats.values())

    index = {
        "version": 1,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "stats": stats,
    }

    INDEX_PATH.write_text(json.dumps(index, indent=2))
    logger.info(f"Browser index saved: {stats['total']} items")
    return {"saved": True, "path": str(INDEX_PATH), "stats": stats}


def load_index() -> Optional[Dict[str, Any]]:
    """Load cached browser index, or None if not found."""
    if not INDEX_PATH.exists():
        return None
    try:
        return json.loads(INDEX_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load index: {e}")
        return None


def index_age_hours() -> Optional[float]:
    """Return hours since last crawl, or None if no index."""
    index = load_index()
    if not index or "crawled_at" not in index:
        return None
    crawled = datetime.fromisoformat(index["crawled_at"])
    if crawled.tzinfo is None:
        crawled = crawled.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - crawled
    return delta.total_seconds() / 3600


# ── Search ──────────────────────────────────────────────────────

def search_index(query: str, category: str = "all", limit: int = 50) -> Dict[str, Any]:
    """Search the cached index by substring match. No Ableton round-trip."""
    index = load_index()
    if not index:
        return {"error": "No index found. Run build_index() first.", "results": [], "count": 0}

    query_lower = query.lower()
    results = []
    categories = index.get("categories", {})

    for cat_name, items in categories.items():
        if category != "all" and cat_name != category:
            continue
        for item in items:
            if len(results) >= limit:
                break
            if query_lower in item.get("name", "").lower() or query_lower in item.get("path", "").lower():
                results.append({**item, "category": cat_name})
        if len(results) >= limit:
            break

    return {"query": query, "category": category, "results": results, "count": len(results)}


# ── Palettes ────────────────────────────────────────────────────

def load_palettes() -> Dict[str, Any]:
    """Load palette definitions from palettes.json."""
    if not PALETTES_PATH.exists():
        return {}
    try:
        return json.loads(PALETTES_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load palettes: {e}")
        return {}


def _resolve_uri(name: str, index: Dict[str, Any]) -> Optional[str]:
    """Try to find a URI in the index matching the given name."""
    name_lower = name.lower()
    categories = index.get("categories", {})
    for items in categories.values():
        for item in items:
            if item.get("name", "").lower() == name_lower:
                return item.get("uri")
    # Partial match fallback
    for items in categories.values():
        for item in items:
            if name_lower in item.get("name", "").lower():
                return item.get("uri")
    return None


def get_palette(style: str) -> Dict[str, Any]:
    """Return a palette with URIs resolved against the index."""
    palettes = load_palettes()
    if style not in palettes:
        available = list(palettes.keys())
        return {"error": f"Unknown style '{style}'", "available_styles": available}

    palette = palettes[style]
    index = load_index()

    resolved = {
        "style": style,
        "description": palette.get("description", ""),
        "tempo_range": palette.get("tempo_range"),
        "tracks": {},
        "mix_template": palette.get("mix_template", {}),
        "missing": [],
    }

    for role, track_def in palette.get("tracks", {}).items():
        resolved_track = {"instruments": [], "effects": [], "effect_chains": track_def.get("effect_chains", [])}

        for inst in track_def.get("instruments", []):
            entry = {**inst}
            if index and not entry.get("uri"):
                found_uri = _resolve_uri(entry["name"], index)
                if found_uri:
                    entry["uri"] = found_uri
                    entry["resolved"] = True
                else:
                    resolved["missing"].append({"role": role, "type": "instrument", "name": entry["name"]})
            resolved_track["instruments"].append(entry)

        for fx in track_def.get("effects", []):
            entry = {**fx}
            if index and not entry.get("uri"):
                found_uri = _resolve_uri(entry["name"], index)
                if found_uri:
                    entry["uri"] = found_uri
                    entry["resolved"] = True
                else:
                    resolved["missing"].append({"role": role, "type": "effect", "name": entry["name"]})
            resolved_track["effects"].append(entry)

        resolved["tracks"][role] = resolved_track

    return resolved


# ── Session analysis ────────────────────────────────────────────

def score_session(tracks: List[Dict[str, Any]], palette: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score how well a session's devices match a palette.
    10pts exact instrument name, 5pts exact effect name, 3pts partial match.
    """
    palette_tracks = palette.get("tracks", {})

    # Collect all instrument and effect names from the palette
    palette_instruments = set()
    palette_effects = set()
    for track_def in palette_tracks.values():
        for inst in track_def.get("instruments", []):
            palette_instruments.add(inst["name"].lower())
        for fx in track_def.get("effects", []):
            palette_effects.add(fx["name"].lower())

    score = 0
    matches = []

    for track in tracks:
        for device in track.get("devices", []):
            dev_name = device.get("name", "").lower()
            dev_class = device.get("class_name", "").lower()

            # Exact instrument match
            if dev_name in palette_instruments:
                score += 10
                matches.append({"track": track.get("name"), "device": device.get("name"), "match": "instrument", "points": 10})
            # Exact effect match
            elif dev_name in palette_effects:
                score += 5
                matches.append({"track": track.get("name"), "device": device.get("name"), "match": "effect", "points": 5})
            else:
                # Partial matches
                for p_inst in palette_instruments:
                    if p_inst in dev_name or dev_name in p_inst:
                        score += 3
                        matches.append({"track": track.get("name"), "device": device.get("name"), "match": "partial_instrument", "points": 3})
                        break
                else:
                    for p_fx in palette_effects:
                        if p_fx in dev_name or dev_name in p_fx:
                            score += 3
                            matches.append({"track": track.get("name"), "device": device.get("name"), "match": "partial_effect", "points": 3})
                            break

    return {"score": score, "matches": matches}


def analyze_session_against_palettes(tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score a session's tracks against all palettes and return ranked results."""
    palettes = load_palettes()
    if not palettes:
        return {"error": "No palettes found"}

    results = []
    for style, palette_def in palettes.items():
        palette_data = {"tracks": palette_def.get("tracks", {})}
        scoring = score_session(tracks, palette_data)
        results.append({
            "style": style,
            "description": palette_def.get("description", ""),
            "score": scoring["score"],
            "matches": scoring["matches"],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    best = results[0] if results else None

    return {
        "best_match": best["style"] if best else None,
        "scores": results,
    }
