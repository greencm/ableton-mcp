# MCP_Server/analysis.py — MIDI analysis engine (pure Python, no Ableton dependency)
#
# Analysis Pipeline:
#   notes[] → pitch_classes → Krumhansl-Schmuckler → key
#   notes[] → beat_windows  → chord_matching       → chords[]
#   notes[] → per_beat_count → rhythmic_density
#   notes[] → velocity_over_time → energy_arc
#   notes[] → min/max/center → register_analysis
#
# All functions accept raw note data as [[pitch, time, dur, vel], ...].
# No Ableton API objects — fully unit-testable.

import math
from typing import List, Dict, Any, Optional, Tuple

# ── Constants ──────────────────────────────────────────────────

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles (correlation weights for pitch class frequency)
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

# Chord templates: intervals from root (in semitones) → chord quality
CHORD_TEMPLATES = {
    "maj":     frozenset([0, 4, 7]),
    "min":     frozenset([0, 3, 7]),
    "dim":     frozenset([0, 3, 6]),
    "aug":     frozenset([0, 4, 8]),
    "sus2":    frozenset([0, 2, 7]),
    "sus4":    frozenset([0, 5, 7]),
    "maj7":    frozenset([0, 4, 7, 11]),
    "min7":    frozenset([0, 3, 7, 10]),
    "dom7":    frozenset([0, 4, 7, 10]),
    "dim7":    frozenset([0, 3, 6, 9]),
    "m7b5":    frozenset([0, 3, 6, 10]),
    "maj9":    frozenset([0, 4, 7, 11, 14]),
    "min9":    frozenset([0, 3, 7, 10, 14]),
    "add9":    frozenset([0, 4, 7, 14]),
    "6":       frozenset([0, 4, 7, 9]),
    "min6":    frozenset([0, 3, 7, 9]),
}

# GM drum note range (pitches 35-81 are standard drum sounds)
DRUM_RANGE = (35, 81)


# ── Key Detection ──────────────────────────────────────────────

def _pitch_class_histogram(notes: List[List]) -> List[float]:
    """Count weighted occurrences of each pitch class (0-11). Weight by duration."""
    histogram = [0.0] * 12
    for n in notes:
        pitch, _, dur, _ = n[0], n[1], n[2] if len(n) > 2 else 0.25, n[3] if len(n) > 3 else 100
        pc = pitch % 12
        histogram[pc] += dur
    return histogram


def _correlate(histogram: List[float], profile: List[float]) -> float:
    """Pearson correlation between histogram and profile."""
    n = len(histogram)
    mean_h = sum(histogram) / n
    mean_p = sum(profile) / n
    num = sum((histogram[i] - mean_h) * (profile[i] - mean_p) for i in range(n))
    den_h = math.sqrt(sum((histogram[i] - mean_h) ** 2 for i in range(n)))
    den_p = math.sqrt(sum((profile[i] - mean_p) ** 2 for i in range(n)))
    if den_h == 0 or den_p == 0:
        return 0.0
    return num / (den_h * den_p)


def detect_key(notes: List[List]) -> Dict[str, Any]:
    """Detect the key of a set of notes using the Krumhansl-Schmuckler algorithm.

    Returns: {"key": "C minor", "confidence": 0.94, "alternatives": [...]}
    """
    if not notes:
        return {"key": "unknown", "confidence": 0.0, "alternatives": []}

    histogram = _pitch_class_histogram(notes)
    if sum(histogram) == 0:
        return {"key": "unknown", "confidence": 0.0, "alternatives": []}

    scores = []
    for root in range(12):
        # Rotate histogram so root is at index 0
        rotated = histogram[root:] + histogram[:root]
        major_corr = _correlate(rotated, MAJOR_PROFILE)
        minor_corr = _correlate(rotated, MINOR_PROFILE)
        scores.append((NOTE_NAMES[root] + " major", major_corr))
        scores.append((NOTE_NAMES[root] + " minor", minor_corr))

    scores.sort(key=lambda x: x[1], reverse=True)
    best = scores[0]

    return {
        "key": best[0],
        "confidence": round(best[1], 4),
        "alternatives": [
            {"key": s[0], "confidence": round(s[1], 4)}
            for s in scores[1:4]
        ],
    }


# ── Chord Detection ────────────────────────────────────────────

def _identify_chord(pitch_classes: frozenset) -> Optional[str]:
    """Given a set of pitch classes, identify the chord name."""
    if len(pitch_classes) < 2:
        return None

    # Try every pitch class as a potential root
    best_match = None
    best_size = 0

    for root in pitch_classes:
        intervals = frozenset((pc - root) % 12 for pc in pitch_classes)
        for name, template in CHORD_TEMPLATES.items():
            # Check if template is a subset of the actual intervals
            if template.issubset(intervals) and len(template) > best_size:
                root_name = NOTE_NAMES[root]
                if name == "maj":
                    chord_name = root_name
                elif name == "min":
                    chord_name = root_name + "m"
                elif name == "min7":
                    chord_name = root_name + "m7"
                elif name == "dom7":
                    chord_name = root_name + "7"
                elif name == "maj7":
                    chord_name = root_name + "maj7"
                else:
                    chord_name = root_name + name
                best_match = chord_name
                best_size = len(template)

    return best_match


def detect_chords(notes: List[List], length: float, beats_per_chord: float = 4.0) -> List[Dict]:
    """Detect chords by grouping notes into beat windows.

    Returns: [{"beat": 0, "chord": "Cm7", "pitch_classes": [0, 3, 7, 10]}, ...]
    """
    if not notes or length <= 0:
        return []

    chords = []
    beat = 0.0
    while beat < length:
        window_end = beat + beats_per_chord
        # Collect pitch classes of all notes sounding in this window
        pcs = set()
        for n in notes:
            pitch, start, dur = n[0], n[1], n[2] if len(n) > 2 else 0.25
            note_end = start + dur
            # Note overlaps with window if it starts before window end
            # and ends after window start
            if start < window_end and note_end > beat:
                pcs.add(pitch % 12)

        chord_name = _identify_chord(frozenset(pcs)) if pcs else None
        chords.append({
            "beat": round(beat, 2),
            "chord": chord_name or ("rest" if not pcs else "unknown"),
            "pitch_classes": sorted(pcs),
        })
        beat += beats_per_chord

    return chords


# ── Chord Chart Generation ─────────────────────────────────────

def generate_chord_chart(chords: List[Dict], beats_per_bar: float = 4.0,
                         beats_per_chord: float = 4.0) -> str:
    """Generate a lead-sheet style chord chart string.

    Returns something like: |: Cm7    | Eb     | Ab     | Bb    :|
    """
    if not chords:
        return ""

    bars = []
    chords_per_bar = max(1, int(beats_per_bar / beats_per_chord))
    current_bar = []
    for c in chords:
        chord_str = c.get("chord", "?")
        if chord_str == "rest":
            chord_str = "-"
        current_bar.append(chord_str)
        if len(current_bar) >= chords_per_bar:
            bars.append(current_bar)
            current_bar = []
    if current_bar:
        bars.append(current_bar)

    # Format as lead sheet
    lines = []
    for i in range(0, len(bars), 4):
        row = bars[i:i + 4]
        parts = []
        for bar in row:
            parts.append(" ".join(f"{c:<7}" for c in bar))
        line = "| " + " | ".join(parts) + " |"
        lines.append(line)

    return "\n".join(lines)


# ── Rhythmic Analysis ──────────────────────────────────────────

def rhythmic_density(notes: List[List], length: float) -> Dict[str, Any]:
    """Analyze rhythmic density and accent patterns."""
    if not notes or length <= 0:
        return {"avg_notes_per_beat": 0, "busiest_beat": 0, "sparsest_beat": 0,
                "total_notes": 0}

    # Count notes per beat
    num_beats = max(1, int(math.ceil(length)))
    beats = [0] * num_beats
    for n in notes:
        beat_idx = min(int(n[1]), num_beats - 1)
        beats[beat_idx] += 1

    avg = sum(beats) / num_beats
    busiest = max(range(num_beats), key=lambda i: beats[i])
    sparsest = min(range(num_beats), key=lambda i: beats[i])

    return {
        "avg_notes_per_beat": round(avg, 2),
        "busiest_beat": busiest,
        "sparsest_beat": sparsest,
        "total_notes": len(notes),
        "beats_with_notes": sum(1 for b in beats if b > 0),
        "total_beats": num_beats,
    }


# ── Energy Arc ─────────────────────────────────────────────────

def energy_arc(notes: List[List], length: float) -> Dict[str, Any]:
    """Analyze the velocity/energy curve over the clip duration.

    Divides the clip into 4 segments and reports average velocity per segment.
    Returns overall arc direction: "rising", "falling", "flat", "peak", "valley".
    """
    if not notes or length <= 0:
        return {"arc": "empty", "segments": [], "velocity_range": [0, 0]}

    num_segments = 4
    seg_length = length / num_segments
    segments = [[] for _ in range(num_segments)]

    for n in notes:
        vel = n[3] if len(n) > 3 else 100
        seg_idx = min(int(n[1] / seg_length), num_segments - 1)
        segments[seg_idx].append(vel)

    avg_vels = []
    for seg in segments:
        avg_vels.append(round(sum(seg) / len(seg), 1) if seg else 0)

    # Determine arc shape
    if all(v == 0 for v in avg_vels):
        arc = "empty"
    elif len(avg_vels) >= 2:
        first_half = sum(avg_vels[:2]) / 2
        second_half = sum(avg_vels[2:]) / 2
        diff = second_half - first_half
        mid = max(avg_vels[1:3]) if len(avg_vels) >= 3 else avg_vels[0]
        edges = (avg_vels[0] + avg_vels[-1]) / 2

        if abs(diff) < 5:
            if mid > edges + 10:
                arc = "peak"
            elif mid < edges - 10:
                arc = "valley"
            else:
                arc = "flat"
        elif diff > 0:
            arc = "rising"
        else:
            arc = "falling"
    else:
        arc = "flat"

    velocities = [n[3] if len(n) > 3 else 100 for n in notes]
    return {
        "arc": arc,
        "segments": avg_vels,
        "velocity_range": [min(velocities), max(velocities)],
        "avg_velocity": round(sum(velocities) / len(velocities), 1),
    }


# ── Register Analysis ──────────────────────────────────────────

def register_analysis(notes: List[List]) -> Dict[str, Any]:
    """Analyze the pitch range and center of gravity."""
    if not notes:
        return {"lowest": 0, "highest": 0, "center": 0, "range_semitones": 0,
                "lowest_name": "", "highest_name": ""}

    pitches = [n[0] for n in notes]
    lo, hi = min(pitches), max(pitches)
    center = round(sum(pitches) / len(pitches), 1)

    def pitch_name(p):
        return f"{NOTE_NAMES[p % 12]}{p // 12 - 1}"

    return {
        "lowest": lo,
        "highest": hi,
        "center": center,
        "range_semitones": hi - lo,
        "lowest_name": pitch_name(lo),
        "highest_name": pitch_name(hi),
        "center_name": pitch_name(int(center)),
    }


# ── Composite: Analyze Notes ──────────────────────────────────

def analyze_notes(notes: List[List], length: float) -> Dict[str, Any]:
    """Full analysis of a clip's notes. Pure function — no Ableton dependency.

    Args:
        notes: [[pitch, time, dur, vel], ...]
        length: clip length in beats

    Returns: dict with key, chords, chord_chart, rhythm, energy, register
    """
    key_info = detect_key(notes)
    chords = detect_chords(notes, length)
    chart = generate_chord_chart(chords)
    rhythm = rhythmic_density(notes, length)
    energy = energy_arc(notes, length)
    register = register_analysis(notes)

    return {
        "key": key_info,
        "chords": chords,
        "chord_chart": chart,
        "rhythm": rhythm,
        "energy": energy,
        "register": register,
        "note_count": len(notes),
        "length_beats": length,
    }


# ── Session-Level Analysis ─────────────────────────────────────

def _detect_track_role(track: Dict) -> str:
    """Guess the musical role of a track based on its clips and devices."""
    name = track.get("name", "").lower()

    # Name-based heuristics first
    if any(k in name for k in ["drum", "beat", "perc", "kick", "snare", "hat"]):
        return "drums"
    if any(k in name for k in ["bass", "sub"]):
        return "bass"
    if any(k in name for k in ["key", "piano", "rhodes", "wurli", "organ", "clav"]):
        return "keys"
    if any(k in name for k in ["pad", "atmo", "ambient", "texture"]):
        return "pad"
    if any(k in name for k in ["lead", "melody", "synth lead", "solo"]):
        return "lead"
    if any(k in name for k in ["horn", "brass", "string"]):
        return "horns"
    if any(k in name for k in ["guitar", "gtr"]):
        return "guitar"
    if any(k in name for k in ["vocal", "vox"]):
        return "vocal"
    if any(k in name for k in ["fx", "riser", "impact", "sweep"]):
        return "fx"
    if any(k in name for k in ["lick"]):
        return "licks"

    # Device-based heuristics
    for dev in track.get("devices", []):
        dev_type = dev.get("type", "")
        dev_name = dev.get("name", "").lower()
        if dev_type == "drum_machine" or "drum" in dev_name:
            return "drums"

    # Pitch-range heuristics from clip notes
    all_pitches = []
    for clip in track.get("clips", []):
        if clip and "notes" in clip:
            for n in clip["notes"]:
                all_pitches.append(n[0] if isinstance(n, list) else n.get("pitch", 60))

    if all_pitches:
        avg_pitch = sum(all_pitches) / len(all_pitches)
        # Only guess drums by pitch if notes cluster tightly in the GM drum zone
        # AND span a wide range (bass notes are low but melodic, drums are scattered)
        unique_pcs = len(set(p % 12 for p in all_pitches))
        pitch_range = max(all_pitches) - min(all_pitches)
        if (all(DRUM_RANGE[0] <= p <= DRUM_RANGE[1] for p in all_pitches)
                and unique_pcs >= 3 and pitch_range > 10):
            return "drums"
        if avg_pitch < 48:
            return "bass"
        if avg_pitch > 72:
            return "lead"

    return "other"


def _find_fx_issues(tracks: List[Dict]) -> List[str]:
    """Find FX problems: identical chains, reverb on bass, etc."""
    issues = []
    fx_chains = {}

    for t in tracks:
        role = t.get("_role", "other")
        effects = []
        for dev in t.get("devices", []):
            dev_type = dev.get("type", "")
            if dev_type in ("audio_effect", "unknown") and dev.get("class_name") != "InstrumentGroupDevice":
                effects.append(dev.get("name", ""))

                # Bass + Reverb check
                if role == "bass" and "reverb" in dev.get("name", "").lower():
                    issues.append(
                        f"Track '{t.get('name')}' (bass) has Reverb — this muddies bass definition. "
                        f"Consider removing it or using very short decay."
                    )

        fx_key = tuple(sorted(effects))
        if fx_key and len(fx_key) > 0:
            if fx_key not in fx_chains:
                fx_chains[fx_key] = []
            fx_chains[fx_key].append(t.get("name", ""))

    # Find duplicate FX chains
    for chain, track_names in fx_chains.items():
        if len(track_names) > 1:
            issues.append(
                f"Tracks {', '.join(track_names)} have identical FX chains "
                f"({', '.join(chain)}). Consider differentiating — e.g., different "
                f"reverb sizes, different delay times."
            )

    return issues


def analyze_session_data(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a full session snapshot musically.

    Args:
        snap: The result of the snapshot command

    Returns: dict with per-track analysis, mix balance, FX audit, suggestions
    """
    tracks = snap.get("tracks", [])
    if not tracks:
        return {"error": "No tracks in session", "tracks": [],
                "suggestions": ["Start by adding tracks and writing some clips."]}

    track_analyses = []
    all_keys = []

    for t in tracks:
        role = _detect_track_role(t)
        t["_role"] = role  # stash for _find_fx_issues

        # Analyze first populated clip per track for key/chord info
        clip_analysis = None
        for clip in t.get("clips", []):
            if clip and clip.get("notes"):
                notes = clip["notes"]
                length = clip.get("length", 16)
                clip_analysis = analyze_notes(notes, length)
                if clip_analysis["key"]["key"] != "unknown":
                    all_keys.append(clip_analysis["key"]["key"])
                break

        track_analyses.append({
            "index": t.get("index"),
            "name": t.get("name"),
            "role": role,
            "volume": t.get("volume"),
            "pan": t.get("pan"),
            "device_count": len(t.get("devices", [])),
            "clip_count": sum(1 for c in t.get("clips", []) if c),
            "clip_analysis": clip_analysis,
        })

    # Mix balance
    volumes = [t.get("volume", 0.85) for t in tracks]
    pans = [t.get("pan", 0.0) for t in tracks]
    mix_info = {
        "volume_range": [round(min(volumes), 2), round(max(volumes), 2)],
        "avg_volume": round(sum(volumes) / len(volumes), 2),
        "pan_spread": round(max(pans) - min(pans), 2) if pans else 0,
        "all_same_volume": max(volumes) - min(volumes) < 0.05,
    }

    # Key coherence
    unique_keys = list(set(all_keys))
    key_info = {
        "detected_keys": unique_keys,
        "coherent": len(unique_keys) <= 1,
        "primary_key": unique_keys[0] if unique_keys else "unknown",
    }

    # FX audit
    fx_issues = _find_fx_issues(tracks)

    # Suggestions
    suggestions = []
    if mix_info["all_same_volume"]:
        suggestions.append(
            "All tracks are at the same volume. Consider a mix where drums and bass "
            "are louder, pads are quieter, to create depth."
        )
    if mix_info["pan_spread"] < 0.3 and len(tracks) > 2:
        suggestions.append(
            "Very narrow stereo spread. Try panning keys slightly left, "
            "a pad slightly right, to create width."
        )
    if not key_info["coherent"] and len(unique_keys) > 1:
        suggestions.append(
            f"Multiple keys detected: {', '.join(unique_keys)}. "
            f"Check if tracks are harmonically compatible."
        )
    suggestions.extend(fx_issues)

    return {
        "tempo": snap.get("tempo"),
        "signature": snap.get("signature"),
        "track_count": len(tracks),
        "scene_count": snap.get("scene_count", 0),
        "tracks": track_analyses,
        "mix": mix_info,
        "key": key_info,
        "fx_issues": fx_issues,
        "suggestions": suggestions,
    }
