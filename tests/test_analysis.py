# tests/test_analysis.py — Unit tests for MIDI analysis engine
# Uses real chord voicings from DISCOSONG.md and vapor1.md as fixtures.
import sys
import os
import pytest

# Add MCP_Server to path so we can import analysis directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'MCP_Server'))
import analysis


# ── Fixtures: real MIDI data from existing songs ───────────────

# DISCOSONG.md: Cm7→Eb→Ab→Bb progression (Scene A, 16 beats)
DISCO_CM7 = [
    [60, 0, 4, 100],   # C3
    [63, 0, 4, 95],    # Eb3
    [67, 0, 4, 90],    # G3
    [70, 0, 4, 85],    # Bb3
]
DISCO_EB = [
    [63, 4, 4, 100],   # Eb3
    [67, 4, 4, 95],    # G3
    [70, 4, 4, 90],    # Bb3
]
DISCO_AB = [
    [56, 8, 4, 100],   # Ab3
    [60, 8, 4, 95],    # C4
    [63, 8, 4, 90],    # Eb4
]
DISCO_BB = [
    [58, 12, 4, 100],  # Bb3
    [62, 12, 4, 95],   # D4
    [65, 12, 4, 90],   # F4
]
DISCO_SCENE_A = DISCO_CM7 + DISCO_EB + DISCO_AB + DISCO_BB

# vapor1.md: Ebmaj7→Abmaj7→Fm7→Bbmaj7 (32 beats)
VAPOR_EBMAJ7 = [
    [51, 0, 8, 80],    # Eb3
    [55, 0, 8, 75],    # G3
    [58, 0, 8, 70],    # Bb3
    [62, 0, 8, 65],    # D4
]
VAPOR_ABMAJ7 = [
    [56, 8, 8, 80],    # Ab3
    [60, 8, 8, 75],    # C4
    [63, 8, 8, 70],    # Eb4
    [67, 8, 8, 65],    # G4
]
VAPOR_FM7 = [
    [53, 16, 8, 80],   # F3
    [56, 16, 8, 75],   # Ab3
    [60, 16, 8, 70],   # C4
    [63, 16, 8, 65],   # Eb4
]
VAPOR_BBMAJ7 = [
    [58, 24, 8, 80],   # Bb3
    [62, 24, 8, 75],   # D4
    [65, 24, 8, 70],   # F4
    [69, 24, 8, 65],   # A4
]
VAPOR_PROGRESSION = VAPOR_EBMAJ7 + VAPOR_ABMAJ7 + VAPOR_FM7 + VAPOR_BBMAJ7

# Simple C minor scale for key detection
C_MINOR_SCALE = [
    [60, 0, 1, 100],   # C
    [62, 1, 1, 100],   # D
    [63, 2, 1, 100],   # Eb
    [65, 3, 1, 100],   # F
    [67, 4, 1, 100],   # G
    [68, 5, 1, 100],   # Ab
    [70, 6, 1, 100],   # Bb
    [72, 7, 1, 100],   # C (octave)
]

# Drum pattern (GM standard: kick=36, snare=38, hihat=42)
DRUM_PATTERN = [
    [36, 0, 0.5, 100],   # Kick
    [42, 0, 0.25, 80],   # HH
    [42, 0.5, 0.25, 70], # HH
    [38, 1, 0.5, 90],    # Snare
    [42, 1, 0.25, 80],   # HH
    [42, 1.5, 0.25, 70], # HH
    [36, 2, 0.5, 100],   # Kick
    [42, 2, 0.25, 80],   # HH
    [42, 2.5, 0.25, 70], # HH
    [38, 3, 0.5, 90],    # Snare
    [42, 3, 0.25, 80],   # HH
    [42, 3.5, 0.25, 70], # HH
]


# ── Key Detection Tests ───────────────────────────────────────

class TestDetectKey:
    def test_c_minor_scale(self):
        result = analysis.detect_key(C_MINOR_SCALE)
        assert result["key"] == "C minor"
        assert result["confidence"] > 0.7

    def test_disco_progression_c_minor(self):
        result = analysis.detect_key(DISCO_SCENE_A)
        # Should detect C minor or Eb major (relative major)
        assert result["key"] in ("C minor", "Eb major", "G# major", "D# major")
        assert result["confidence"] > 0.5

    def test_vapor_progression_eb(self):
        result = analysis.detect_key(VAPOR_PROGRESSION)
        # Should detect Eb major or C minor (relative minor)
        key = result["key"]
        assert "Eb" in key or "C" in key or "D#" in key
        assert result["confidence"] > 0.5

    def test_empty_notes(self):
        result = analysis.detect_key([])
        assert result["key"] == "unknown"
        assert result["confidence"] == 0.0

    def test_single_note(self):
        result = analysis.detect_key([[60, 0, 1, 100]])
        assert result["key"] != "unknown"
        # Single C note — should suggest C something
        assert "C" in result["key"]

    def test_unison(self):
        """All same pitch — degenerate case."""
        notes = [[60, i, 1, 100] for i in range(8)]
        result = analysis.detect_key(notes)
        assert result["key"] != "unknown"

    def test_returns_alternatives(self):
        result = analysis.detect_key(C_MINOR_SCALE)
        assert len(result["alternatives"]) >= 1
        # Relative major should be in alternatives
        alt_keys = [a["key"] for a in result["alternatives"]]
        assert any("Eb" in k or "D#" in k for k in alt_keys) or result["key"] == "Eb major"


# ── Chord Detection Tests ─────────────────────────────────────

class TestDetectChords:
    def test_cm7_voicing(self):
        """DISCOSONG Cm7: C3, Eb3, G3, Bb3"""
        chords = analysis.detect_chords(DISCO_CM7, 4.0, beats_per_chord=4.0)
        assert len(chords) == 1
        assert chords[0]["chord"] == "Cm7"

    def test_ebmaj7_voicing(self):
        """vapor1 Ebmaj7: Eb3, G3, Bb3, D4"""
        chords = analysis.detect_chords(VAPOR_EBMAJ7, 8.0, beats_per_chord=8.0)
        assert len(chords) == 1
        chord = chords[0]["chord"]
        assert chord in ("D#maj7", "Ebmaj7"), f"Expected Ebmaj7, got {chord}"

    def test_disco_progression_4_chords(self):
        """Full disco progression should detect 4 chords."""
        chords = analysis.detect_chords(DISCO_SCENE_A, 16.0, beats_per_chord=4.0)
        assert len(chords) == 4
        assert chords[0]["chord"] == "Cm7"

    def test_vapor_progression_4_chords(self):
        """Full vaporwave progression should detect 4 chords."""
        chords = analysis.detect_chords(VAPOR_PROGRESSION, 32.0, beats_per_chord=8.0)
        assert len(chords) == 4

    def test_empty_returns_empty(self):
        assert analysis.detect_chords([], 16.0) == []

    def test_rest_when_no_notes_in_window(self):
        """Notes only in first 4 beats, window at beat 8 should be 'rest'."""
        chords = analysis.detect_chords(DISCO_CM7, 16.0, beats_per_chord=4.0)
        assert chords[2]["chord"] == "rest"

    def test_simple_major_triad(self):
        """C major triad: C, E, G."""
        notes = [[60, 0, 4, 100], [64, 0, 4, 95], [67, 0, 4, 90]]
        chords = analysis.detect_chords(notes, 4.0, beats_per_chord=4.0)
        assert chords[0]["chord"] == "C"


# ── Chord Chart Tests ─────────────────────────────────────────

class TestChordChart:
    def test_basic_chart(self):
        chords = analysis.detect_chords(DISCO_SCENE_A, 16.0, beats_per_chord=4.0)
        chart = analysis.generate_chord_chart(chords)
        assert "Cm7" in chart
        assert "|" in chart

    def test_empty_returns_empty(self):
        assert analysis.generate_chord_chart([]) == ""


# ── Rhythmic Density Tests ────────────────────────────────────

class TestRhythmicDensity:
    def test_drum_pattern(self):
        result = analysis.rhythmic_density(DRUM_PATTERN, 4.0)
        assert result["total_notes"] == 12
        assert result["avg_notes_per_beat"] == 3.0

    def test_empty(self):
        result = analysis.rhythmic_density([], 4.0)
        assert result["total_notes"] == 0

    def test_sparse_pattern(self):
        notes = [[60, 0, 1, 100], [62, 3, 1, 100]]
        result = analysis.rhythmic_density(notes, 4.0)
        assert result["total_notes"] == 2
        assert result["beats_with_notes"] == 2


# ── Energy Arc Tests ──────────────────────────────────────────

class TestEnergyArc:
    def test_rising_energy(self):
        """Notes get louder over time."""
        notes = [
            [60, 0, 1, 40], [60, 1, 1, 50],
            [60, 2, 1, 90], [60, 3, 1, 120],
        ]
        result = analysis.energy_arc(notes, 4.0)
        assert result["arc"] == "rising"

    def test_falling_energy(self):
        notes = [
            [60, 0, 1, 120], [60, 1, 1, 100],
            [60, 2, 1, 50], [60, 3, 1, 30],
        ]
        result = analysis.energy_arc(notes, 4.0)
        assert result["arc"] == "falling"

    def test_flat_energy(self):
        notes = [[60, i, 1, 80] for i in range(4)]
        result = analysis.energy_arc(notes, 4.0)
        assert result["arc"] == "flat"

    def test_empty(self):
        result = analysis.energy_arc([], 4.0)
        assert result["arc"] == "empty"

    def test_velocity_range(self):
        notes = [[60, 0, 1, 40], [60, 1, 1, 120]]
        result = analysis.energy_arc(notes, 2.0)
        assert result["velocity_range"] == [40, 120]


# ── Register Analysis Tests ───────────────────────────────────

class TestRegisterAnalysis:
    def test_bass_register(self):
        notes = [[36, 0, 1, 100], [40, 1, 1, 100], [43, 2, 1, 100]]
        result = analysis.register_analysis(notes)
        assert result["lowest"] == 36
        assert result["highest"] == 43
        assert result["center"] < 48  # bass register

    def test_empty(self):
        result = analysis.register_analysis([])
        assert result["range_semitones"] == 0

    def test_pitch_names(self):
        notes = [[60, 0, 1, 100]]  # Middle C
        result = analysis.register_analysis(notes)
        assert result["lowest_name"] == "C4"


# ── Composite analyze_notes Tests ─────────────────────────────

class TestAnalyzeNotes:
    def test_disco_full_analysis(self):
        result = analysis.analyze_notes(DISCO_SCENE_A, 16.0)
        assert "key" in result
        assert "chords" in result
        assert "chord_chart" in result
        assert "rhythm" in result
        assert "energy" in result
        assert "register" in result
        assert result["note_count"] == len(DISCO_SCENE_A)

    def test_empty_clip(self):
        result = analysis.analyze_notes([], 16.0)
        assert result["key"]["key"] == "unknown"
        assert result["note_count"] == 0


# ── Track Role Detection Tests ────────────────────────────────

class TestTrackRoleDetection:
    def test_drums_by_name(self):
        track = {"name": "Disco Drums", "devices": [], "clips": []}
        assert analysis._detect_track_role(track) == "drums"

    def test_bass_by_name(self):
        track = {"name": "Sub Bass", "devices": [], "clips": []}
        assert analysis._detect_track_role(track) == "bass"

    def test_keys_by_name(self):
        track = {"name": "Disco Keys", "devices": [], "clips": []}
        assert analysis._detect_track_role(track) == "keys"

    def test_drums_by_device(self):
        track = {"name": "Track 1", "devices": [{"type": "drum_machine", "name": "909 Kit"}], "clips": []}
        assert analysis._detect_track_role(track) == "drums"

    def test_bass_by_pitch(self):
        track = {
            "name": "Track 2", "devices": [],
            "clips": [{"notes": [[36, 0, 4, 100], [40, 4, 4, 100]], "length": 8}]
        }
        assert analysis._detect_track_role(track) == "bass"
