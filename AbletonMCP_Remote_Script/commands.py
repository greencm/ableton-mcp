# AbletonMCP/commands.py — All command handlers (hot-reloadable)
# Each handler is: handle_<command_type>(surface, params) -> dict
# `surface` is the AbletonMCP ControlSurface instance.
from __future__ import absolute_import, print_function, unicode_literals
import math
import time
import traceback
import Live


# ── Helpers ─────────────────────────────────────────────────────

def _get_song(surface):
    return surface._song


def _get_track(surface, params):
    song = _get_song(surface)
    idx = params.get("track_index", 0)
    if idx < 0 or idx >= len(song.tracks):
        raise IndexError("Track index out of range")
    return song.tracks[idx]


def _get_clip(surface, params):
    track = _get_track(surface, params)
    idx = params.get("clip_index", 0)
    if idx < 0 or idx >= len(track.clip_slots):
        raise IndexError("Clip index out of range")
    slot = track.clip_slots[idx]
    if not slot.has_clip:
        raise Exception("No clip in slot")
    return slot, slot.clip


def _get_device_type(device):
    try:
        if device.can_have_drum_pads:
            return "drum_machine"
        elif device.can_have_chains:
            return "rack"
        elif "instrument" in device.class_display_name.lower():
            return "instrument"
        elif "audio_effect" in device.class_name.lower():
            return "audio_effect"
        elif "midi_effect" in device.class_name.lower():
            return "midi_effect"
    except:
        pass
    return "unknown"


def _meter_reading(track):
    """Read output meter levels from a track, return dict with left/right/peak/db."""
    try:
        left = track.output_meter_left
        right = track.output_meter_right
        peak = max(left, right)
        db = round(20.0 * math.log10(peak), 1) if peak > 0.0 else -100.0
        return {"left": round(left, 4), "right": round(right, 4),
                "peak": round(peak, 4), "db": db}
    except Exception:
        return {"left": 0.0, "right": 0.0, "peak": 0.0, "db": -100.0}


# Color mapping for auto-color clips by track role
_ROLE_COLORS = {
    "drums": 69, "drum": 69, "perc": 69,       # red
    "bass": 50,                                   # blue
    "keys": 14, "piano": 14, "organ": 14,        # yellow
    "pad": 26, "pads": 26,                        # green
    "lead": 60, "synth": 60,                      # purple
    "vocal": 35, "vox": 35, "voice": 35,          # cyan
    "fx": 42, "sfx": 42, "noise": 42,             # orange
    "guitar": 18, "gtr": 18,                      # warm yellow
}


def _detect_role_color(track_name):
    """Return a color_index based on track name keywords, or None."""
    name_lower = track_name.lower()
    for keyword, color in _ROLE_COLORS.items():
        if keyword in name_lower:
            return color
    return None


def _find_browser_item_by_uri(browser_or_item, uri, max_depth=10, depth=0):
    try:
        if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
            return browser_or_item
        if depth >= max_depth:
            return None
        if hasattr(browser_or_item, 'instruments'):
            for cat in [browser_or_item.instruments, browser_or_item.sounds,
                        browser_or_item.drums, browser_or_item.audio_effects,
                        browser_or_item.midi_effects]:
                item = _find_browser_item_by_uri(cat, uri, max_depth, depth + 1)
                if item:
                    return item
            return None
        if hasattr(browser_or_item, 'children') and browser_or_item.children:
            for child in browser_or_item.children:
                item = _find_browser_item_by_uri(child, uri, max_depth, depth + 1)
                if item:
                    return item
    except:
        pass
    return None


# ── Session info ────────────────────────────────────────────────

def handle_get_session_info(surface, params):
    song = _get_song(surface)
    return {
        "tempo": song.tempo,
        "signature_numerator": song.signature_numerator,
        "signature_denominator": song.signature_denominator,
        "track_count": len(song.tracks),
        "return_track_count": len(song.return_tracks),
        "master_track": {
            "name": "Master",
            "volume": song.master_track.mixer_device.volume.value,
            "panning": song.master_track.mixer_device.panning.value
        }
    }


def handle_get_track_info(surface, params):
    track = _get_track(surface, params)
    idx = params.get("track_index", 0)
    clip_slots = []
    for slot_index, slot in enumerate(track.clip_slots):
        clip_info = None
        if slot.has_clip:
            clip = slot.clip
            clip_info = {
                "name": clip.name,
                "length": clip.length,
                "is_playing": clip.is_playing,
                "is_recording": clip.is_recording
            }
        clip_slots.append({
            "index": slot_index,
            "has_clip": slot.has_clip,
            "clip": clip_info
        })
    devices = []
    for di, device in enumerate(track.devices):
        devices.append({
            "index": di,
            "name": device.name,
            "class_name": device.class_name,
            "type": _get_device_type(device)
        })
    return {
        "index": idx,
        "name": track.name,
        "is_audio_track": track.has_audio_input,
        "is_midi_track": track.has_midi_input,
        "mute": track.mute,
        "solo": track.solo,
        "arm": track.arm,
        "volume": track.mixer_device.volume.value,
        "panning": track.mixer_device.panning.value,
        "clip_slots": clip_slots,
        "devices": devices
    }


# ── Track creation ──────────────────────────────────────────────

def handle_create_midi_track(surface, params):
    song = _get_song(surface)
    index = params.get("index", -1)
    song.create_midi_track(index)
    new_index = len(song.tracks) - 1 if index == -1 else index
    return {"index": new_index, "name": song.tracks[new_index].name}


def handle_create_audio_track(surface, params):
    song = _get_song(surface)
    index = params.get("index", -1)
    song.create_audio_track(index)
    new_index = len(song.tracks) - 1 if index == -1 else index
    return {"index": new_index, "name": song.tracks[new_index].name}


def handle_set_track_name(surface, params):
    track = _get_track(surface, params)
    name = params.get("name", "")
    track.name = name
    return {"name": track.name}


def handle_set_track_volume(surface, params):
    track = _get_track(surface, params)
    volume = max(0.0, min(1.0, params.get("volume", 0.85)))
    track.mixer_device.volume.value = volume
    return {
        "track_index": params.get("track_index", 0),
        "volume": track.mixer_device.volume.value,
        "track_name": track.name
    }


def handle_set_track_send(surface, params):
    track = _get_track(surface, params)
    send_index = params.get("send_index", 0)
    value = max(0.0, min(1.0, params.get("value", 0.0)))
    sends = track.mixer_device.sends
    if send_index < 0 or send_index >= len(sends):
        raise IndexError("Send index out of range (track has {0} sends)".format(len(sends)))
    sends[send_index].value = value
    return {
        "track_index": params.get("track_index", 0),
        "send_index": send_index,
        "value": sends[send_index].value,
        "track_name": track.name
    }


# ── Clips ───────────────────────────────────────────────────────

def handle_create_clip(surface, params):
    track = _get_track(surface, params)
    clip_index = params.get("clip_index", 0)
    length = params.get("length", 4.0)
    if clip_index < 0 or clip_index >= len(track.clip_slots):
        raise IndexError("Clip index out of range")
    slot = track.clip_slots[clip_index]
    if slot.has_clip:
        raise Exception("Clip slot already has a clip")
    slot.create_clip(length)
    return {"name": slot.clip.name, "length": slot.clip.length}


def handle_delete_clip(surface, params):
    track = _get_track(surface, params)
    clip_index = params.get("clip_index", 0)
    if clip_index < 0 or clip_index >= len(track.clip_slots):
        raise IndexError("Clip index out of range")
    slot = track.clip_slots[clip_index]
    if not slot.has_clip:
        raise Exception("No clip in slot")
    slot.delete_clip()
    return {"deleted": True}


def _parse_notes(notes):
    """Parse notes into MidiNoteSpecification objects (Live 11+ API).

    Supports abbreviated tuples: [pitch, time, dur, vel, probability]
    or dicts with keys: pitch, start_time, duration, velocity, mute,
    probability (0.0-1.0), velocity_deviation (-127 to 127),
    release_velocity (0-127).
    """
    specs = []
    for n in notes:
        if isinstance(n, (list, tuple)):
            specs.append(Live.Clip.MidiNoteSpecification(
                pitch=int(n[0]),
                start_time=float(n[1]),
                duration=float(n[2]) if len(n) > 2 else 0.25,
                velocity=float(n[3]) if len(n) > 3 else 100.0,
                mute=False,
                probability=float(n[4]) if len(n) > 4 else 1.0,
                velocity_deviation=float(n[5]) if len(n) > 5 else 0.0,
                release_velocity=int(n[6]) if len(n) > 6 else 0,
            ))
        else:
            specs.append(Live.Clip.MidiNoteSpecification(
                pitch=int(n.get("pitch", 60)),
                start_time=float(n.get("start_time", 0.0)),
                duration=float(n.get("duration", 0.25)),
                velocity=float(n.get("velocity", 100)),
                mute=bool(n.get("mute", False)),
                probability=float(n.get("probability", 1.0)),
                velocity_deviation=float(n.get("velocity_deviation", 0.0)),
                release_velocity=int(n.get("release_velocity", 0)),
            ))
    return specs


def handle_add_notes_to_clip(surface, params):
    slot, clip = _get_clip(surface, params)
    notes = params.get("notes", [])
    specs = _parse_notes(notes)
    clip.add_new_notes(tuple(specs))
    return {"note_count": len(notes)}


def handle_get_clip_notes(surface, params):
    slot, clip = _get_clip(surface, params)
    notes = clip.get_notes_extended(from_pitch=0, pitch_span=128,
                                    from_time=0.0, time_span=clip.length)
    result = []
    for note in notes:
        entry = {
            "pitch": note.pitch,
            "start_time": note.start_time,
            "duration": note.duration,
            "velocity": note.velocity,
            "mute": note.mute,
        }
        if note.probability < 1.0:
            entry["probability"] = round(note.probability, 2)
        if note.velocity_deviation != 0.0:
            entry["velocity_deviation"] = round(note.velocity_deviation, 1)
        if note.release_velocity != 0:
            entry["release_velocity"] = note.release_velocity
        result.append(entry)
    return {"notes": result, "clip_name": clip.name, "clip_length": clip.length}


def handle_clear_notes(surface, params):
    slot, clip = _get_clip(surface, params)
    clip.remove_notes_extended(from_pitch=0, pitch_span=128,
                               from_time=0.0, time_span=clip.length)
    return {"cleared": True, "clip_name": clip.name}


def handle_set_clip_name(surface, params):
    slot, clip = _get_clip(surface, params)
    name = params.get("name", "")
    clip.name = name
    return {"name": clip.name}


def handle_get_clip_properties(surface, params):
    """Return all readable properties of a clip."""
    track = _get_track(surface, params)
    slot, clip = _get_clip(surface, params)
    is_audio = track.has_audio_input

    props = {
        "name": clip.name,
        "length": clip.length,
        "looping": clip.looping,
        "loop_start": clip.loop_start,
        "loop_end": clip.loop_end,
        "start_marker": clip.start_marker,
        "end_marker": clip.end_marker,
        "color_index": clip.color_index,
        "signature_numerator": clip.signature_numerator,
        "signature_denominator": clip.signature_denominator,
        "is_playing": clip.is_playing,
        "is_recording": clip.is_recording,
        "is_audio": is_audio,
    }

    try:
        props["velocity_amount"] = clip.velocity_amount
    except Exception:
        pass

    if is_audio:
        try:
            props["warping"] = clip.warping
            props["warp_mode"] = clip.warp_mode
            props["pitch_coarse"] = clip.pitch_coarse
            props["pitch_fine"] = clip.pitch_fine
        except Exception:
            pass

    return props


# Whitelist of settable clip properties with type coercion
_CLIP_SETTABLE = {
    "looping": bool, "loop_start": float, "loop_end": float,
    "start_marker": float, "end_marker": float,
    "color_index": int, "velocity_amount": float, "name": str,
    "signature_numerator": int, "signature_denominator": int,
}
_CLIP_AUDIO_SETTABLE = {
    "warping": bool, "warp_mode": int, "pitch_coarse": int, "pitch_fine": float,
}


def handle_set_clip_properties(surface, params):
    """Set one or more clip properties from a dict."""
    track = _get_track(surface, params)
    slot, clip = _get_clip(surface, params)
    is_audio = track.has_audio_input
    properties = params.get("properties", {})

    if not properties:
        raise ValueError("No properties provided")

    applied = {}
    errors = {}
    all_settable = dict(_CLIP_SETTABLE)
    if is_audio:
        all_settable.update(_CLIP_AUDIO_SETTABLE)

    for key, value in properties.items():
        if key not in all_settable:
            errors[key] = "Unknown or read-only property"
            continue
        try:
            setattr(clip, key, all_settable[key](value))
            applied[key] = getattr(clip, key)
        except Exception as e:
            errors[key] = str(e)

    result = {"applied": applied, "clip_name": clip.name}
    if errors:
        result["errors"] = errors
    return result


# ── Transport ───────────────────────────────────────────────────

def handle_set_tempo(surface, params):
    song = _get_song(surface)
    song.tempo = params.get("tempo", 120.0)
    return {"tempo": song.tempo}


def handle_fire_clip(surface, params):
    track = _get_track(surface, params)
    clip_index = params.get("clip_index", 0)
    slot = track.clip_slots[clip_index]
    if not slot.has_clip:
        raise Exception("No clip in slot")
    slot.fire()
    return {"fired": True}


def handle_stop_clip(surface, params):
    track = _get_track(surface, params)
    clip_index = params.get("clip_index", 0)
    track.clip_slots[clip_index].stop()
    return {"stopped": True}


def handle_start_playback(surface, params):
    song = _get_song(surface)
    song.start_playing()
    return {"playing": song.is_playing}


def handle_stop_playback(surface, params):
    song = _get_song(surface)
    song.stop_playing()
    return {"playing": song.is_playing}


def handle_start_recording(surface, params):
    song = _get_song(surface)
    song.session_record = True
    if not song.is_playing:
        song.start_playing()
    return {"recording": True, "playing": song.is_playing}


def handle_stop_recording(surface, params):
    song = _get_song(surface)
    song.session_record = False
    return {"recording": False, "playing": song.is_playing}


def handle_start_arrangement_recording(surface, params):
    song = _get_song(surface)
    stop_after_beats = params.get("stop_after_beats")

    song.record_mode = True
    if not song.is_playing:
        song.start_playing()

    result = {"recording": True, "playing": True, "tempo": song.tempo}

    if stop_after_beats is not None:
        ticks_per_beat = 600.0 / song.tempo
        delay_ticks = int(stop_after_beats * ticks_per_beat)

        def stop_recording():
            try:
                song.record_mode = False
                song.stop_playing()
                surface.log_message("Arrangement recording stopped after " + str(stop_after_beats) + " beats")
            except Exception as ex:
                surface.log_message("Stop recording error: " + str(ex))

        surface.schedule_message(delay_ticks, stop_recording)
        result["stop_after_beats"] = stop_after_beats

    return result


def handle_fire_scene(surface, params):
    song = _get_song(surface)
    scene_index = params.get("scene_index", 0)
    if scene_index < 0 or scene_index >= len(song.scenes):
        raise IndexError("Scene index out of range")
    scene = song.scenes[scene_index]
    scene.fire()
    return {"fired": True, "scene_index": scene_index, "scene_name": scene.name}


def handle_fire_scene_sequence(surface, params):
    song = _get_song(surface)
    scenes = params.get("scenes", [])
    if not scenes:
        raise ValueError("No scenes provided")
    tempo = song.tempo
    ticks_per_beat = 600.0 / tempo
    sorted_scenes = sorted(scenes, key=lambda s: s.get("delay_beats", 0))

    def schedule_next(index, prev_delay_beats):
        if index >= len(sorted_scenes):
            return
        entry = sorted_scenes[index]
        scene_index = entry.get("scene_index", 0)
        delay_beats = entry.get("delay_beats", 0)
        relative_beats = delay_beats - prev_delay_beats
        delay_ticks = max(0, int(relative_beats * ticks_per_beat))

        def fire_and_continue():
            try:
                if scene_index < len(song.scenes):
                    song.scenes[scene_index].fire()
                    surface.log_message("Scene sequence: fired scene " + str(scene_index))
            except Exception as ex:
                surface.log_message("Scene sequence error: " + str(ex))
            schedule_next(index + 1, delay_beats)

        if delay_ticks > 0:
            surface.schedule_message(delay_ticks, fire_and_continue)
        else:
            fire_and_continue()

    schedule_next(0, 0)
    return {
        "queued": len(sorted_scenes),
        "tempo": tempo,
        "ticks_per_beat": ticks_per_beat,
        "scenes": [s.get("scene_index", 0) for s in sorted_scenes]
    }


# ── Device parameters ───────────────────────────────────────────

def handle_get_device_parameters(surface, params):
    track = _get_track(surface, params)
    device_index = params.get("device_index", 0)
    if device_index < 0 or device_index >= len(track.devices):
        raise IndexError("Device index out of range")
    device = track.devices[device_index]
    parameters = []
    for pi, p in enumerate(device.parameters):
        parameters.append({
            "index": pi,
            "name": p.name,
            "value": p.value,
            "min": p.min,
            "max": p.max,
            "is_quantized": p.is_quantized
        })
    return {
        "device_name": device.name,
        "class_name": device.class_name,
        "parameters": parameters
    }


def handle_set_device_parameter(surface, params):
    track = _get_track(surface, params)
    device_index = params.get("device_index", 0)
    parameter_index = params.get("parameter_index", 0)
    value = params.get("value", 0.0)
    if device_index < 0 or device_index >= len(track.devices):
        raise IndexError("Device index out of range")
    device = track.devices[device_index]
    if parameter_index < 0 or parameter_index >= len(device.parameters):
        raise IndexError("Parameter index out of range")
    p = device.parameters[parameter_index]
    value = max(p.min, min(p.max, value))
    p.value = value
    return {
        "device_name": device.name,
        "parameter_name": p.name,
        "value": p.value
    }


# ── Browser ─────────────────────────────────────────────────────

def handle_get_browser_tree(surface, params):
    app = surface.application()
    if not app or not hasattr(app, 'browser') or app.browser is None:
        raise RuntimeError("Browser not available")
    browser = app.browser
    category_type = params.get("category_type", "all")

    def process_item(item):
        if not item:
            return None
        return {
            "name": item.name if hasattr(item, 'name') else "Unknown",
            "is_folder": hasattr(item, 'children') and bool(item.children),
            "is_device": hasattr(item, 'is_device') and item.is_device,
            "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
            "uri": item.uri if hasattr(item, 'uri') else None,
            "children": []
        }

    result = {"type": category_type, "categories": []}
    cat_map = {
        "instruments": ("Instruments", "instruments"),
        "sounds": ("Sounds", "sounds"),
        "drums": ("Drums", "drums"),
        "audio_effects": ("Audio Effects", "audio_effects"),
        "midi_effects": ("MIDI Effects", "midi_effects"),
    }
    for key, (label, attr) in cat_map.items():
        if (category_type == "all" or category_type == key) and hasattr(browser, attr):
            try:
                cat = process_item(getattr(browser, attr))
                if cat:
                    cat["name"] = label
                    result["categories"].append(cat)
            except Exception as e:
                surface.log_message("Error processing {0}: {1}".format(key, str(e)))
    return result


def handle_get_browser_items_at_path(surface, params):
    app = surface.application()
    if not app or not hasattr(app, 'browser') or app.browser is None:
        raise RuntimeError("Browser not available")
    browser = app.browser
    path = params.get("path", "")
    path_parts = path.split("/")
    if not path_parts:
        raise ValueError("Invalid path")

    root_category = path_parts[0].lower()
    cat_map = {
        "instruments": "instruments", "sounds": "sounds", "drums": "drums",
        "audio_effects": "audio_effects", "midi_effects": "midi_effects"
    }
    if root_category in cat_map and hasattr(browser, cat_map[root_category]):
        current_item = getattr(browser, cat_map[root_category])
    else:
        raise ValueError("Unknown category: {0}".format(root_category))

    for i in range(1, len(path_parts)):
        part = path_parts[i]
        if not part:
            continue
        if not hasattr(current_item, 'children'):
            raise ValueError("Item at '{0}' has no children".format('/'.join(path_parts[:i])))
        found = False
        for child in current_item.children:
            if hasattr(child, 'name') and child.name.lower() == part.lower():
                current_item = child
                found = True
                break
        if not found:
            raise ValueError("Path part '{0}' not found".format(part))

    items = []
    if hasattr(current_item, 'children'):
        for child in current_item.children:
            items.append({
                "name": child.name if hasattr(child, 'name') else "Unknown",
                "is_folder": hasattr(child, 'children') and bool(child.children),
                "is_device": hasattr(child, 'is_device') and child.is_device,
                "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                "uri": child.uri if hasattr(child, 'uri') else None
            })
    return {
        "path": path,
        "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
        "uri": current_item.uri if hasattr(current_item, 'uri') else None,
        "items": items
    }


def handle_get_browser_item(surface, params):
    app = surface.application()
    if not app:
        raise RuntimeError("Could not access Live application")
    uri = params.get("uri", None)
    path = params.get("path", None)
    result = {"uri": uri, "path": path, "found": False}
    if uri:
        item = _find_browser_item_by_uri(app.browser, uri)
        if item:
            result["found"] = True
            result["item"] = {
                "name": item.name, "is_folder": item.is_folder,
                "is_device": item.is_device, "is_loadable": item.is_loadable,
                "uri": item.uri
            }
    return result


def handle_get_browser_categories(surface, params):
    # Kept for backwards compat, delegates to tree
    return handle_get_browser_tree(surface, params)


def handle_get_browser_items(surface, params):
    # Kept for backwards compat, delegates to path
    return handle_get_browser_items_at_path(surface, params)


def handle_search_browser(surface, params):
    """Search browser items by name across all categories."""
    app = surface.application()
    if not app or not hasattr(app, 'browser') or app.browser is None:
        raise RuntimeError("Browser not available")
    browser = app.browser
    query = params.get("query", "").lower()
    max_results = params.get("max_results", 20)
    if not query:
        raise ValueError("Search query is required")

    results = []

    def search_children(item, path, depth=0):
        if depth > 6 or len(results) >= max_results:
            return
        if not hasattr(item, 'children'):
            return
        for child in item.children:
            if len(results) >= max_results:
                return
            name = child.name if hasattr(child, 'name') else ""
            child_path = path + "/" + name if path else name
            if query in name.lower():
                results.append({
                    "name": name,
                    "path": child_path,
                    "is_folder": hasattr(child, 'children') and bool(child.children),
                    "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                    "uri": child.uri if hasattr(child, 'uri') else None
                })
            if hasattr(child, 'children') and child.children:
                search_children(child, child_path, depth + 1)

    for attr in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects']:
        if len(results) >= max_results:
            break
        if hasattr(browser, attr):
            try:
                search_children(getattr(browser, attr), attr)
            except:
                pass

    return {"query": query, "results": results, "count": len(results)}


def handle_crawl_browser(surface, params):
    """Walk the full browser tree and return every loadable item."""
    app = surface.application()
    if not app or not hasattr(app, 'browser') or app.browser is None:
        raise RuntimeError("Browser not available")
    browser = app.browser
    category = params.get("category", "all")
    max_depth = params.get("max_depth", 10)

    cat_map = {
        "instruments": "instruments", "sounds": "sounds",
        "drums": "drums", "audio_effects": "audio_effects",
        "midi_effects": "midi_effects",
    }
    cats = cat_map if category == "all" else {category: cat_map[category]}
    result = {}

    for key, attr in cats.items():
        items = []
        if not hasattr(browser, attr):
            continue

        def crawl(item, path, depth):
            if depth > max_depth:
                return
            if not hasattr(item, 'children'):
                return
            try:
                for child in item.children:
                    name = child.name if hasattr(child, 'name') else ""
                    child_path = path + "/" + name if path else name
                    is_loadable = hasattr(child, 'is_loadable') and child.is_loadable
                    uri = child.uri if hasattr(child, 'uri') else None
                    if is_loadable and uri:
                        items.append({
                            "name": name, "path": child_path,
                            "uri": uri,
                            "is_device": hasattr(child, 'is_device') and child.is_device,
                        })
                    if hasattr(child, 'children') and child.children:
                        crawl(child, child_path, depth + 1)
            except Exception:
                pass

        crawl(getattr(browser, attr), key, 0)
        result[key] = items

    total = sum(len(v) for v in result.values())
    return {"categories": result, "total_items": total}


# ── Instrument/effect loading ───────────────────────────────────

def handle_load_browser_item(surface, params):
    song = _get_song(surface)
    track = _get_track(surface, params)
    app = surface.application()
    item_uri = params.get("item_uri", "")
    item = _find_browser_item_by_uri(app.browser, item_uri)
    if not item:
        raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
    song.view.selected_track = track
    app.browser.load_item(item)
    return {"loaded": True, "item_name": item.name, "track_name": track.name, "uri": item_uri}


# ── Save / Load ─────────────────────────────────────────────────

def handle_save_set(surface, params):
    song = _get_song(surface)
    song.save()
    return {"saved": True}


def handle_save_set_as(surface, params):
    song = _get_song(surface)
    file_path = params.get("file_path", "")
    if not file_path:
        raise ValueError("file_path is required")
    song.save_as(file_path)
    return {"saved": True, "file_path": file_path}


# ── Sidechain ───────────────────────────────────────────────────

def handle_setup_sidechain(surface, params):
    """Configure a compressor's sidechain input to listen to another track.

    params:
        track_index: track containing the compressor
        device_index: index of the Compressor device on that track
        sidechain_source_track: track index to use as sidechain input
    """
    song = _get_song(surface)
    track = _get_track(surface, params)
    device_index = params.get("device_index", 0)
    source_track_index = params.get("sidechain_source_track", 0)

    if device_index < 0 or device_index >= len(track.devices):
        raise IndexError("Device index out of range")
    device = track.devices[device_index]

    if source_track_index < 0 or source_track_index >= len(song.tracks):
        raise IndexError("Sidechain source track index out of range")
    source_track = song.tracks[source_track_index]

    # Find the sidechain parameter - Ableton compressors expose this
    # via the device's routing. We look for the "Sidechain" parameter group.
    # The approach: enumerate parameters to find sidechain-related ones,
    # and set the sidechain input routing via the mixer.

    # For Compressor/Glue Compressor, the sidechain is controlled via
    # the device's own parameters. We need to:
    # 1. Enable sidechain (parameter named "S/C On" or similar)
    # 2. Set the routing to the source track

    # Enable sidechain
    sc_enabled = False
    for p in device.parameters:
        if "sidechain" in p.name.lower() or p.name in ("S/C On", "S/C"):
            if p.is_quantized:
                p.value = p.max  # Enable
            else:
                p.value = 1.0
            sc_enabled = True
            break

    # Set sidechain routing via the device's input routing
    # Ableton's API: device has a "input_routing_type" and "input_routing_channel"
    # for sidechain-capable devices
    routing_set = False
    if hasattr(device, 'input_routing_type'):
        # Find the routing option that matches the source track
        available_types = device.input_routing_type.available_values if hasattr(device.input_routing_type, 'available_values') else []
        for rt in available_types:
            if source_track.name.lower() in str(rt).lower():
                device.input_routing_type.value = rt
                routing_set = True
                break

    return {
        "device_name": device.name,
        "sidechain_enabled": sc_enabled,
        "routing_set": routing_set,
        "source_track": source_track.name,
        "note": "Sidechain routing may need manual verification in Ableton"
    }


# ── Meters & Spectrum ─────────────────────────────────────────

def handle_get_meters(surface, params):
    """Return current output meter levels for tracks, returns, and master."""
    song = _get_song(surface)
    track_index = params.get("track_index")
    ts = int(time.time() * 1000)

    if track_index is not None:
        track = _get_track(surface, params)
        return {
            "track_index": track_index,
            "name": track.name,
            "meters": _meter_reading(track),
            "is_playing": song.is_playing,
            "timestamp": ts,
        }

    tracks = []
    for i, track in enumerate(song.tracks):
        tracks.append({"index": i, "name": track.name, "meters": _meter_reading(track)})

    returns = []
    for i, track in enumerate(song.return_tracks):
        returns.append({"index": i, "name": track.name, "meters": _meter_reading(track)})

    return {
        "tracks": tracks,
        "returns": returns,
        "master": _meter_reading(song.master_track),
        "is_playing": song.is_playing,
        "timestamp": ts,
    }


# Peak meter accumulation state (module-level, reset on hot-reload)
_peak_data = {}
_peak_sampling = False


def handle_start_peak_meter(surface, params):
    """Start accumulating peak meter data over multiple samples."""
    global _peak_data, _peak_sampling
    song = _get_song(surface)
    num_samples = min(params.get("samples", 10), 50)
    interval_ms = max(params.get("interval_ms", 50), 20)
    reset = params.get("reset", True)

    if _peak_sampling and not reset:
        return {"error": "Peak metering already in progress. Use reset=true to restart."}

    _peak_data = {}
    _peak_sampling = True

    # Initialize accumulators
    for i, track in enumerate(song.tracks):
        _peak_data[("track", i)] = {"name": track.name, "peak_left": 0.0, "peak_right": 0.0}
    for i, track in enumerate(song.return_tracks):
        _peak_data[("return", i)] = {"name": track.name, "peak_left": 0.0, "peak_right": 0.0}
    _peak_data[("master", 0)] = {"name": "Master", "peak_left": 0.0, "peak_right": 0.0}

    def sample(remaining):
        global _peak_sampling
        if remaining <= 0 or not _peak_sampling:
            _peak_sampling = False
            return
        for i, track in enumerate(song.tracks):
            d = _peak_data.get(("track", i))
            if d:
                try:
                    d["peak_left"] = max(d["peak_left"], track.output_meter_left)
                    d["peak_right"] = max(d["peak_right"], track.output_meter_right)
                except Exception:
                    pass
        for i, track in enumerate(song.return_tracks):
            d = _peak_data.get(("return", i))
            if d:
                try:
                    d["peak_left"] = max(d["peak_left"], track.output_meter_left)
                    d["peak_right"] = max(d["peak_right"], track.output_meter_right)
                except Exception:
                    pass
        d = _peak_data.get(("master", 0))
        if d:
            try:
                d["peak_left"] = max(d["peak_left"], song.master_track.output_meter_left)
                d["peak_right"] = max(d["peak_right"], song.master_track.output_meter_right)
            except Exception:
                pass
        surface.schedule_message(interval_ms, lambda: sample(remaining - 1))

    sample(num_samples)

    return {
        "started": True,
        "samples": num_samples,
        "interval_ms": interval_ms,
        "estimated_duration_ms": num_samples * interval_ms,
    }


def handle_get_peak_meters(surface, params):
    """Read accumulated peak meter data."""
    global _peak_data, _peak_sampling

    if not _peak_data:
        return {"error": "No peak data collected. Call start_peak_meter first."}

    tracks = []
    returns = []
    master = None

    for key in sorted(_peak_data.keys()):
        data = _peak_data[key]
        kind, idx = key
        peak = max(data["peak_left"], data["peak_right"])
        db = round(20.0 * math.log10(peak), 1) if peak > 0.0 else -100.0
        entry = {
            "index": idx,
            "name": data["name"],
            "peak_left": round(data["peak_left"], 4),
            "peak_right": round(data["peak_right"], 4),
            "peak": round(peak, 4),
            "db": db,
        }
        if kind == "track":
            tracks.append(entry)
        elif kind == "return":
            returns.append(entry)
        elif kind == "master":
            master = entry

    return {
        "tracks": tracks,
        "returns": returns,
        "master": master,
        "still_sampling": _peak_sampling,
        "timestamp": int(time.time() * 1000),
    }


SPECTRUM_BANDS = ["Sub", "Low", "Low-Mid", "Mid", "High-Mid", "High", "Air"]


def handle_get_spectrum(surface, params):
    """Read frequency band levels from M4L SpectrumAnalyzer device."""
    track_index = params.get("track_index")
    song = _get_song(surface)
    track = song.master_track if track_index is None else _get_track(surface, params)

    for device in track.devices:
        try:
            param_names = {p.name for p in device.parameters}
            if all(band in param_names for band in SPECTRUM_BANDS):
                bands = {}
                for p in device.parameters:
                    if p.name in SPECTRUM_BANDS:
                        bands[p.name.lower().replace("-", "_")] = round(p.value, 1)
                return {"track": track.name, "bands": bands, "device": device.name}
        except Exception:
            continue

    return {"error": "No spectrum analyzer found on track. Load SpectrumAnalyzer M4L device."}


# ── Snapshot ───────────────────────────────────────────────────
# Aggregates get_session_info + get_track_info + get_clip_notes + device params
# for ALL tracks in one call.  Runs on main thread.  Caps at 100 populated clips.

def handle_snapshot(surface, params):
    """Return the entire session state in a single call.

    Includes: tempo, signature, all tracks with devices (+ key params),
    all clips with MIDI notes.  Capped at 100 populated clips to keep
    payload size reasonable — response includes "truncated": true if
    the cap was hit.
    """
    song = _get_song(surface)
    max_clips = params.get("max_clips", 100)
    clip_count = 0
    truncated = False

    tracks = []
    for ti, track in enumerate(song.tracks):
        # --- devices with top-level params ---
        devices = []
        for di, device in enumerate(track.devices):
            dev_info = {
                "index": di,
                "name": device.name,
                "class_name": device.class_name,
                "type": _get_device_type(device),
            }
            # Include the first 8 non-trivial parameters per device
            try:
                dev_params = {}
                count = 0
                for p in device.parameters:
                    if count >= 8:
                        break
                    # Skip the "Device On" toggle — it's always param 0
                    if p.name == "Device On":
                        continue
                    dev_params[p.name] = round(p.value, 4)
                    count += 1
                if dev_params:
                    dev_info["params"] = dev_params
            except Exception:
                pass
            devices.append(dev_info)

        # --- clips with notes ---
        clips = []
        for si, slot in enumerate(track.clip_slots):
            if not slot.has_clip:
                clips.append(None)
                continue
            clip = slot.clip
            clip_info = {
                "slot": si,
                "name": clip.name,
                "length": clip.length,
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "color_index": clip.color_index,
            }
            if clip_count < max_clips:
                try:
                    notes = clip.get_notes_extended(from_pitch=0, pitch_span=128,
                                                     from_time=0.0, time_span=clip.length)
                    note_list = []
                    for n in notes:
                        nd = [n.pitch, round(n.start_time, 4), round(n.duration, 4), n.velocity]
                        if n.probability < 1.0:
                            nd.append(round(n.probability, 2))
                        note_list.append(nd)
                    clip_info["notes"] = note_list
                    clip_info["note_count"] = len(note_list)
                except Exception:
                    clip_info["notes"] = []
                    clip_info["note_count"] = 0
                clip_count += 1
            else:
                truncated = True
                clip_info["note_count"] = "?"
            clips.append(clip_info)

        tracks.append({
            "index": ti,
            "name": track.name,
            "type": "audio" if track.has_audio_input else "midi",
            "volume": round(track.mixer_device.volume.value, 4),
            "pan": round(track.mixer_device.panning.value, 4),
            "mute": track.mute,
            "solo": track.solo,
            "arm": track.arm,
            "devices": devices,
            "clips": clips,
        })

    return {
        "tempo": song.tempo,
        "signature": "{0}/{1}".format(song.signature_numerator, song.signature_denominator),
        "track_count": len(song.tracks),
        "return_track_count": len(song.return_tracks),
        "scene_count": len(song.scenes),
        "is_playing": song.is_playing,
        "master_volume": round(song.master_track.mixer_device.volume.value, 4),
        "tracks": tracks,
        "clip_count": clip_count,
        "truncated": truncated,
    }


# ── Composite handlers ────────────────────────────────────────

def handle_create_track(surface, params):
    """Create a track with name, instrument, and volume in one call."""
    song = _get_song(surface)
    track_type = params.get("type", "midi")
    name = params.get("name")
    instrument_uri = params.get("instrument_uri")
    volume = params.get("volume")
    index = params.get("index", -1)

    if track_type == "audio":
        song.create_audio_track(index)
    else:
        song.create_midi_track(index)
    new_index = len(song.tracks) - 1 if index == -1 else index
    track = song.tracks[new_index]

    if name:
        track.name = name

    if instrument_uri:
        app = surface.application()
        item = _find_browser_item_by_uri(app.browser, instrument_uri)
        if item:
            song.view.selected_track = track
            app.browser.load_item(item)

    if volume is not None:
        track.mixer_device.volume.value = max(0.0, min(1.0, volume))

    return {
        "track_index": new_index,
        "name": track.name,
        "type": track_type
    }


def handle_write_clip(surface, params):
    """Create a clip, add notes, and set name in one call."""
    track = _get_track(surface, params)
    clip_index = params.get("clip_index", 0)
    length = params.get("length", 4.0)
    notes = params.get("notes", [])
    name = params.get("name")
    overwrite = params.get("overwrite", False)

    if clip_index < 0 or clip_index >= len(track.clip_slots):
        raise IndexError("Clip index out of range")
    slot = track.clip_slots[clip_index]

    if slot.has_clip:
        if overwrite:
            slot.delete_clip()
        else:
            raise Exception("Clip slot already has a clip (use overwrite=true)")

    slot.create_clip(length)
    clip = slot.clip

    if notes:
        specs = _parse_notes(notes)
        clip.add_new_notes(tuple(specs))

    if name:
        clip.name = name

    return {
        "track_index": params.get("track_index", 0),
        "clip_index": clip_index,
        "name": clip.name,
        "length": clip.length,
        "note_count": len(notes)
    }


def handle_set_mix(surface, params):
    """Set volume and pan for multiple tracks in one call."""
    song = _get_song(surface)
    tracks = params.get("tracks", [])
    results = []
    for t in tracks:
        idx = t.get("track_index", t.get("index", 0))
        if idx < 0 or idx >= len(song.tracks):
            results.append({"track_index": idx, "error": "Track index out of range"})
            continue
        track = song.tracks[idx]
        if "volume" in t:
            track.mixer_device.volume.value = max(0.0, min(1.0, t["volume"]))
        if "pan" in t:
            track.mixer_device.panning.value = max(-1.0, min(1.0, t["pan"]))
        results.append({
            "track_index": idx,
            "name": track.name,
            "volume": track.mixer_device.volume.value,
            "panning": track.mixer_device.panning.value
        })
    return {"tracks": results}


# ── Batch & Compose ────────────────────────────────────────────

def handle_batch(surface, params):
    """Execute a list of commands in a single main-thread callback."""
    commands = params.get("commands", [])
    results = []
    for cmd in commands:
        cmd_type = cmd.get("type", "")
        cmd_params = cmd.get("params", {})
        handler = globals().get("handle_" + cmd_type)
        if handler is None:
            results.append({"status": "error", "error": "Unknown command: " + cmd_type})
        else:
            try:
                result = handler(surface, cmd_params)
                results.append({"status": "success", "result": result})
            except Exception as e:
                results.append({"status": "error", "error": str(e)})
    return {"results": results, "count": len(results)}


def handle_compose(surface, params):
    """Execute a sequence of composition operations in a single call."""
    operations = params.get("operations", [])
    results = []
    created_tracks = {}  # sequential ref -> actual Ableton track index

    for op in operations:
        op_type = op.get("op")
        try:
            if op_type == "tempo":
                handle_set_tempo(surface, {"tempo": op.get("bpm", 120)})
                results.append({"op": "tempo", "bpm": op.get("bpm")})

            elif op_type == "track":
                result = handle_create_track(surface, {
                    "name": op.get("name"),
                    "instrument_uri": op.get("instrument_uri"),
                    "type": op.get("type", "midi"),
                    "volume": op.get("volume"),
                    "index": op.get("index", -1),
                })
                ref = len(created_tracks)
                created_tracks[ref] = result["track_index"]
                results.append({"op": "track", "ref": ref, "track_index": result["track_index"]})

            elif op_type == "clip":
                track_idx = op.get("track")
                # Support "ref:N" to reference Nth track created in this compose call
                if isinstance(track_idx, str) and track_idx.startswith("ref:"):
                    ref = int(track_idx.split(":")[1])
                    track_idx = created_tracks.get(ref, 0)
                handle_write_clip(surface, {
                    "track_index": track_idx,
                    "clip_index": op.get("slot", 0),
                    "notes": op.get("notes", []),
                    "name": op.get("name"),
                    "length": op.get("length", 4),
                    "overwrite": op.get("overwrite", False),
                })
                # Auto-color clip based on track role
                try:
                    track = song.tracks[track_idx]
                    slot = track.clip_slots[op.get("slot", 0)]
                    if slot.has_clip:
                        color = _detect_role_color(track.name)
                        if color is not None:
                            slot.clip.color_index = color
                except Exception:
                    pass  # Auto-color is best-effort
                results.append({"op": "clip", "track_index": track_idx, "slot": op.get("slot", 0)})

            elif op_type == "clip_props":
                track_idx = op.get("track")
                if isinstance(track_idx, str) and track_idx.startswith("ref:"):
                    ref = int(track_idx.split(":")[1])
                    track_idx = created_tracks.get(ref, 0)
                result = handle_set_clip_properties(surface, {
                    "track_index": track_idx,
                    "clip_index": op.get("slot", 0),
                    "properties": op.get("properties", {}),
                })
                results.append({"op": "clip_props", "track_index": track_idx, "result": result})

            elif op_type == "mix":
                handle_set_mix(surface, {"tracks": op.get("tracks", [])})
                results.append({"op": "mix"})

            elif op_type == "play":
                scene = op.get("scene")
                if scene is not None:
                    handle_fire_scene(surface, {"scene_index": scene})
                    results.append({"op": "play", "scene": scene})
                else:
                    handle_start_playback(surface, {})
                    results.append({"op": "play"})

            else:
                results.append({"op": op_type, "error": "Unknown operation"})

        except Exception as e:
            results.append({"op": op_type, "error": str(e)})

    return {"operations_completed": len(results), "results": results}


# ── Duplicate / Copy ────────────────────────────────────────────

def handle_duplicate_clip(surface, params):
    """Copy a clip from one slot to another (same or different track)."""
    src_track = _get_track(surface, {"track_index": params["src_track_index"]})
    dst_track = _get_track(surface, {"track_index": params.get("dst_track_index", params["src_track_index"])})
    src_idx = params["src_clip_index"]
    dst_idx = params["dst_clip_index"]

    if src_idx < 0 or src_idx >= len(src_track.clip_slots):
        raise IndexError("Source clip index out of range")
    if dst_idx < 0 or dst_idx >= len(dst_track.clip_slots):
        raise IndexError("Destination clip index out of range")

    src_slot = src_track.clip_slots[src_idx]
    dst_slot = dst_track.clip_slots[dst_idx]

    if not src_slot.has_clip:
        raise Exception("Source slot has no clip")
    if dst_slot.has_clip:
        if params.get("overwrite", False):
            dst_slot.delete_clip()
        else:
            raise Exception("Destination has clip (use overwrite=true)")

    src_clip = src_slot.clip
    dst_slot.create_clip(src_clip.length)
    notes = src_clip.get_notes_extended(from_pitch=0, pitch_span=128,
                                        from_time=0.0, time_span=src_clip.length)
    specs = []
    for n in notes:
        specs.append(Live.Clip.MidiNoteSpecification(
            pitch=n.pitch, start_time=n.start_time, duration=n.duration,
            velocity=n.velocity, mute=n.mute, probability=n.probability,
            velocity_deviation=n.velocity_deviation,
            release_velocity=n.release_velocity,
        ))
    dst_slot.clip.add_new_notes(tuple(specs))
    dst_slot.clip.name = params.get("name", src_clip.name)

    return {
        "src_track": params["src_track_index"], "src_clip": src_idx,
        "dst_track": params.get("dst_track_index", params["src_track_index"]),
        "dst_clip": dst_idx,
        "name": dst_slot.clip.name, "length": src_clip.length
    }


def handle_duplicate_scene(surface, params):
    """Copy all clips from one scene row to another."""
    song = _get_song(surface)
    src = params["src_scene_index"]
    dst = params["dst_scene_index"]
    overwrite = params.get("overwrite", False)
    name_prefix = params.get("name")
    copied = []

    for i, track in enumerate(song.tracks):
        if src >= len(track.clip_slots) or dst >= len(track.clip_slots):
            continue
        src_slot = track.clip_slots[src]
        dst_slot = track.clip_slots[dst]
        if not src_slot.has_clip:
            continue
        if dst_slot.has_clip:
            if overwrite:
                dst_slot.delete_clip()
            else:
                continue
        src_clip = src_slot.clip
        dst_slot.create_clip(src_clip.length)
        notes = src_clip.get_notes_extended(from_pitch=0, pitch_span=128,
                                            from_time=0.0, time_span=src_clip.length)
        specs = []
        for n in notes:
            specs.append(Live.Clip.MidiNoteSpecification(
                pitch=n.pitch, start_time=n.start_time, duration=n.duration,
                velocity=n.velocity, mute=n.mute, probability=n.probability,
                velocity_deviation=n.velocity_deviation,
                release_velocity=n.release_velocity,
            ))
        dst_slot.clip.add_new_notes(tuple(specs))
        dst_slot.clip.name = name_prefix if name_prefix else src_clip.name
        copied.append({"track_index": i, "track_name": track.name,
                        "clip_name": dst_slot.clip.name})

    return {"src_scene": src, "dst_scene": dst,
            "clips_copied": len(copied), "clips": copied}
