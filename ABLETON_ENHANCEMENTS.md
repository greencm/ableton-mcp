# Ableton MCP Enhancement Requests

**Fork:** [github.com/cmgbhm/ableton-mcp](https://github.com/cmgbhm/ableton-mcp)
**Upstream:** [github.com/closestfriend/ableton-mcp](https://github.com/closestfriend/ableton-mcp)

Limitations encountered during disco house production session. These are features the MCP API currently lacks that required manual intervention in Ableton.

## Track Controls

### Set Track Volume — IMPLEMENTED
**Priority:** High
We couldn't programmatically adjust faders when the mix was clipping. User had to manually pull down all 4 track volumes.
- `set_track_volume(track_index, volume)` — volume as 0.0-1.0 float

### Delete Track
**Priority:** Medium
Created 4 duplicate "Wind Down" tracks (8-11) that became unnecessary after moving clips to the main tracks. No way to remove them via API.
- `delete_track(track_index)`

### Set Track Panning
**Priority:** Low
Not needed yet but would be expected alongside volume control.
- `set_track_panning(track_index, pan)` — pan as -1.0 to 1.0

## Device / Effect Parameters

### Set Device Parameter
**Priority:** High
Couldn't adjust Saturator drive, Reverb dry/wet, Echo feedback, Drum Buss crunch, Auto Filter cutoff, etc. This was a major limitation for mixing and sound design.
- `get_device_parameters(track_index, device_index)` — list available params and current values
- `set_device_parameter(track_index, device_index, parameter_name, value)`

### Sidechain Routing
**Priority:** Medium
Wanted to set up sidechain compression (e.g., bass ducking to kick) but routing is not exposed.
- `set_sidechain_source(track_index, device_index, source_track_index)`

## Clip Management

### Delete / Overwrite Clip
**Priority:** High
Cannot remove or replace an existing clip. If a clip needs to be redone, there's no recourse via API. Had to work around this multiple times.
- `delete_clip(track_index, clip_index)`
- Or allow `create_clip` to overwrite when a clip already exists

### Clear Notes from Clip
**Priority:** Medium
Can only add notes, never remove them. If a wrong note is added, the clip is permanently altered.
- `remove_notes_from_clip(track_index, clip_index, notes)` — remove specific notes
- `clear_clip_notes(track_index, clip_index)` — remove all notes

## Scene Management

### Create Scene
**Priority:** High
Ran out of clip slots (only 8 scenes existed). User had to manually add scenes through index 13 in Ableton before we could create the 32-beat Wind Down clips at slot 8.
- `create_scene(index)` — add a scene at the given index
- `set_scene_name(scene_index, name)`

### Delete Scene
**Priority:** Low
- `delete_scene(scene_index)`

### Fire Scene — IMPLEMENTED
**Priority:** High
Currently firing clips one track at a time. Scene-level fire would simplify arrangement playback significantly — we had to fire 4 clips independently for each section change.
- `fire_scene(scene_index)` — fire all clips in a scene row simultaneously
- `fire_scene_sequence(scenes)` — fire a sequence of scenes with beat-based timing, all executed inside Ableton with zero network latency between changes. Each entry specifies `scene_index` and `delay_beats` from the start of the sequence.

## Launch Quantization

### Set Global Launch Quantization
**Priority:** Medium
User wanted clips to only switch on 4-bar boundaries. Had to set this manually via the dropdown next to the tempo display.
- `set_launch_quantization(value)` — e.g., "1 Bar", "4 Bars", "None"

### Set Clip Launch Quantization
**Priority:** Low
Per-clip override of the global launch quantization.
- `set_clip_launch_quantization(track_index, clip_index, value)`

## Arrangement / Transport

### Set Song Position
**Priority:** Low
Would be useful for jumping to a specific bar before recording.
- `set_song_position(beats)`

### Trigger Record — IMPLEMENTED
**Priority:** Medium
User had to manually hit record. Being able to trigger record via API would enable fully automated arrangement recording.
- `start_recording()` — enables session recording and starts playback
- `stop_recording()` — disables session recording

## Ableton 12 Compatibility Fix

The Remote Script required a code change to work with Ableton 12. The original script was missing the `get_capabilities()` function that Ableton 12's control surface loader expects.

### Problem
Ableton 12 changed how it loads control surface scripts. Without `get_capabilities()`, the script fails to initialize and doesn't appear in Ableton's Control Surface preferences.

### Fix Applied
Added `get_capabilities()` to `AbletonMCP_Remote_Script/__init__.py`:

```python
def get_capabilities():
    """Return the capabilities of this control surface script"""
    from _Framework.Capabilities import CONTROLLER_ID_KEY, PORTS_KEY, NOTES_CC, SCRIPT
    return {
        CONTROLLER_ID_KEY: CONTROLLER_ID_KEY,
        PORTS_KEY: [],
    }
```

This was inserted before the existing `create_instance()` function. The function returns a minimal capabilities dict with no port requirements, which is correct since AbletonMCP communicates over a TCP socket (port 9877) rather than MIDI ports.

### Diff
```diff
--- a/AbletonMCP_Remote_Script/__init__.py
+++ b/AbletonMCP_Remote_Script/__init__.py
@@ -18,6 +18,14 @@
 DEFAULT_PORT = 9877
 HOST = "localhost"

+def get_capabilities():
+    """Return the capabilities of this control surface script"""
+    from _Framework.Capabilities import CONTROLLER_ID_KEY, PORTS_KEY, NOTES_CC, SCRIPT
+    return {
+        CONTROLLER_ID_KEY: CONTROLLER_ID_KEY,
+        PORTS_KEY: [],
+    }
+
 def create_instance(c_instance):
     """Create and return the AbletonMCP script instance"""
     return AbletonMCP(c_instance)
```

**Note:** This fix has not been committed upstream yet. It should be submitted as a PR to the ableton-mcp repo.

---

## Composition Flow Optimization

Building a 5-track electro swing song required **~69 MCP tool calls across ~26 LLM round trips**. Each round trip costs 2-5 seconds of LLM generation latency, making the total composition time dominated by protocol overhead rather than Ableton execution. The disco house session showed the same pattern — 4 tracks, 9 clip slots, similar call counts. The three tiers below target progressively larger reductions in round trips and context.

### Tier 1 — Composite Tools (quick wins, no protocol changes)

These are new MCP tools that wrap existing `_cmd()` handlers sequentially in `server.py`. No changes to the socket protocol or Remote Script.

**`create_track(name, instrument_uri, type, volume)`**
Replaces the current 3-call sequence (`create_midi_track` → `set_track_name` → `load_instrument_or_effect`) with a single call. Optionally sets volume in the same call.

**`write_clip(track_index, clip_index, notes, name, length, overwrite)`**
Replaces the 3-call sequence (`create_clip` → `add_notes_to_clip` → `set_clip_name`) with one call. If `overwrite=true`, deletes any existing clip first. This is the single biggest win — every clip in a song hits this sequence.

**`set_mix(tracks: [{track_index, volume, pan}])`**
Replaces N individual `set_track_volume` / `set_track_panning` calls with one batch call.

**Reduce socket sleep from 0.1s to 0.025s**
The `schedule_message` + `response_queue.get()` pattern in `server.py:91-101` already blocks until Ableton completes each command. The 0.1s sleeps before and after are conservative padding. Reducing to 0.025s saves ~75% of the ~10s cumulative sleep overhead in a typical session.

### Tier 2 — Batch Protocol + Tool Consolidation (medium effort)

**Native `batch` command in socket protocol**
Add a `handle_batch` handler in `commands.py` that accepts a list of commands and executes them in a single `schedule_message` callback. The composite tools from Tier 1 switch from N socket round trips to 1, cutting per-command sleep overhead to near zero.

**`compose` DSL tool**
A single MCP tool accepting a list of typed operations:
```json
[
  {"op": "tempo", "bpm": 128},
  {"op": "track", "name": "Drums", "instrument_uri": "...", "volume": 0.7},
  {"op": "clip", "track": 0, "slot": 0, "name": "Verse Beat", "length": 8,
   "notes": [[36,0,0.5,100], [38,1,0.5,80], [42,0,0.25,90], ...]},
  {"op": "mix", "tracks": [{"index": 0, "volume": 0.7}, {"index": 1, "volume": 0.6}]},
  {"op": "play", "scene": 0}
]
```
Replaces most individual tool calls for song creation. An entire 5-track song can be described in 1-2 `compose` calls.

**Abbreviated note format**
`[pitch, time, dur, vel]` tuple instead of `{"pitch":, "start_time":, "duration":, "velocity":, "mute":}`. Reduces LLM output tokens per clip by ~75% — a 16-note drum pattern drops from ~800 tokens to ~200.

**Remove redundant MCP tools**
Keep the handlers in `commands.py` but strip `@mcp.tool()` decorators from ~13 tools that are fully subsumed by the composite tools (`create_midi_track`, `set_track_name`, `load_instrument_or_effect`, `create_clip`, `add_notes_to_clip`, `set_clip_name`, `set_track_volume`, `fire_clip`, `stop_clip`, `set_tempo`, `get_browser_tree`, `get_browser_items_at_path`, `load_drum_kit`). Reduces tool schema context sent to the LLM by ~50%.

### Tier 3 — Architectural (longer term)

**Song template system**
Entire song described as one JSON document — tracks, instruments, clips, notes, mix, arrangement — posted in a single MCP call and processed entirely within the Remote Script. The LLM generates one structured output and Ableton builds it.

**Async command pipeline**
Replace the blocking request/response socket with a pipelined protocol. Commands are streamed without waiting for individual responses. Errors are collected and returned at the end.

### Impact Comparison (5-track, 2-scene song)

| Metric | Current | Tier 1 | Tier 1+2 |
|--------|---------|--------|----------|
| MCP tool calls | ~69 | ~31 | ~12 |
| LLM round trips | ~26 | ~18 | ~8 |
| Socket sleep overhead | ~10s | ~2.5s | ~0.5s |
| Tool schemas in context | 33 | 36 (+3 new) | ~20 (-13 removed) |

---

## Summary

| Category | Enhancement | Priority |
|----------|------------|----------|
| Track Controls | Set track volume | ~~High~~ DONE |
| Track Controls | Delete track | Medium |
| Track Controls | Set track panning | Low |
| Devices | Get/set device parameters | High |
| Devices | Sidechain routing | Medium |
| Clips | Delete/overwrite clip | High |
| Clips | Clear/remove notes | Medium |
| Scenes | Create scene | High |
| Scenes | Fire scene + sequence | ~~High~~ DONE |
| Scenes | Delete scene | Low |
| Scenes | Set scene name | Medium |
| Launch | Global launch quantization | Medium |
| Launch | Per-clip launch quantization | Low |
| Transport | Set song position | Low |
| Transport | Start/stop recording | ~~Medium~~ DONE |
| Optimization | Composite tools (`create_track`, `write_clip`, `set_mix`) | High |
| Optimization | Reduce socket sleep (0.1s → 0.025s) | High |
| Optimization | Native `batch` socket command | Medium |
| Optimization | `compose` DSL tool | Medium |
| Optimization | Abbreviated note format | Medium |
| Optimization | Remove redundant MCP tool schemas | Medium |
| Optimization | Song template system | Low |
| Optimization | Async command pipeline | Low |
