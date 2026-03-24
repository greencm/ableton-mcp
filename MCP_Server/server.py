# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union

from . import style_index
from . import analysis

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")


@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None

    def connect(self) -> bool:
        if self.sock:
            return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192, timeout=15.0):
        chunks = []
        sock.settimeout(timeout)
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving data")
                        break
                    chunks.append(chunk)
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        return data
                    except json.JSONDecodeError:
                        continue
                except socket.timeout:
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    raise
        except Exception as e:
            raise
        if chunks:
            data = b''.join(chunks)
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response")
        raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None,
                     timeout: float = None) -> Dict[str, Any]:
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")

        command = {"type": command_type, "params": params or {}}

        is_modifying = command_type not in {
            "get_session_info", "get_track_info", "snapshot",
            "get_browser_item", "get_browser_categories", "get_browser_items",
            "get_browser_tree", "get_browser_items_at_path",
            "get_clip_notes", "get_device_parameters", "search_browser",
            "crawl_browser", "get_clip_properties", "get_meters",
            "get_peak_meters", "get_spectrum",
        }

        if timeout is None:
            timeout = 15.0 if is_modifying else 10.0

        try:
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            if is_modifying:
                import time
                time.sleep(0.010)
            self.sock.settimeout(timeout)
            response_data = self.receive_full_response(self.sock, timeout=timeout)
            response = json.loads(response_data.decode('utf-8'))
            if response.get("status") == "error":
                raise Exception(response.get("message", "Unknown error"))
            if is_modifying:
                import time
                time.sleep(0.010)
            return response.get("result", {})
        except socket.timeout:
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            if "Timeout" not in str(e) and "Connection" not in str(e):
                self.sock = None
            raise


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    try:
        logger.info("AbletonMCP server starting up")
        try:
            get_ableton_connection()
            logger.info("Connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect on startup: {str(e)}")
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")


mcp = FastMCP("AbletonMCP", lifespan=server_lifespan)
_ableton_connection = None


def get_ableton_connection():
    global _ableton_connection
    if _ableton_connection is not None:
        try:
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except:
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            _ableton_connection = AbletonConnection(host="localhost", port=9877)
            if _ableton_connection.connect():
                _ableton_connection.send_command("get_session_info")
                return _ableton_connection
        except:
            if _ableton_connection:
                _ableton_connection.disconnect()
            _ableton_connection = None
        if attempt < max_attempts:
            import time
            time.sleep(1.0)

    raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")


# ── Helper to reduce boilerplate ────────────────────────────────

def _cmd(command_type: str, params: Dict[str, Any] = None,
         timeout: float = None) -> Dict[str, Any]:
    return get_ableton_connection().send_command(command_type, params, timeout=timeout)


# ── Session ─────────────────────────────────────────────────────

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    return json.dumps(_cmd("get_session_info"), indent=2)


@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.

    Parameters:
    - track_index: The index of the track to get information about

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0).
    """
    return json.dumps(_cmd("get_track_info", {"track_index": track_index}), indent=2)


# ── Snapshot ──────────────────────────────────────────────────

@mcp.tool()
def snapshot(ctx: Context) -> str:
    """
    Return the entire session state in a single call — all tracks, devices
    (with key parameters), and clips (with MIDI notes).

    This is the fastest way to understand what's currently in Ableton.
    Use this instead of calling get_track_info + get_clip_notes for each track.

    Capped at 100 populated clips. If truncated, use get_clip_notes for specific clips.

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0).
    """
    result = _cmd("snapshot", timeout=30.0)
    return json.dumps(result, indent=2)


# ── Composite tools (Tier 1) ──────────────────────────────────

@mcp.tool()
def create_track(ctx: Context, name: str, instrument_uri: str = "",
                 type: str = "midi", volume: float = None, index: int = -1) -> str:
    """
    Create a new track with name, instrument, and volume in one call.
    Replaces the 3-call sequence: create_midi_track + set_track_name + load_instrument.

    Parameters:
    - name: Track name
    - instrument_uri: URI of instrument to load (optional, from search_browser)
    - type: "midi" or "audio" (default: "midi")
    - volume: Volume level 0.0-1.0 (optional, default ~0.85)
    - index: Position to insert at (-1 = end)

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0).
    """
    params = {"name": name, "type": type, "index": index}
    if instrument_uri:
        params["instrument_uri"] = instrument_uri
    if volume is not None:
        params["volume"] = volume
    return json.dumps(_cmd("create_track", params), indent=2)


@mcp.tool()
def write_clip(ctx: Context, track_index: int, clip_index: int,
               notes: List[Union[Dict[str, Union[int, float, bool]], List[Union[int, float]]]],
               name: str = "", length: float = 4.0, overwrite: bool = False) -> str:
    """
    Create a clip, add notes, and set name in one call.
    Replaces the 3-call sequence: create_clip + add_notes_to_clip + set_clip_name.

    Parameters:
    - track_index: Track index
    - clip_index: Clip slot index
    - notes: MIDI notes as dicts {pitch, start_time, duration, velocity}
             OR abbreviated [pitch, time, duration, velocity] tuples
    - name: Clip name (optional)
    - length: Clip length in beats (default: 4.0)
    - overwrite: If true, delete existing clip first (default: false)

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = slot 0).
    """
    params = {
        "track_index": track_index, "clip_index": clip_index,
        "notes": notes, "length": length, "overwrite": overwrite
    }
    if name:
        params["name"] = name
    return json.dumps(_cmd("write_clip", params), indent=2)


@mcp.tool()
def set_mix(ctx: Context, tracks: List[Dict[str, Union[int, float]]]) -> str:
    """
    Set volume and pan for multiple tracks in one call.

    Parameters:
    - tracks: List of dicts, each with:
        - track_index (or index): Track number
        - volume: 0.0-1.0 (optional)
        - pan: -1.0 to 1.0 (optional)

    NOTE: track_index is 0-based (Ableton UI Track 1 = index 0).
    """
    return json.dumps(_cmd("set_mix", {"tracks": tracks}), indent=2)


# ── Compose DSL (Tier 2) ──────────────────────────────────────

@mcp.tool()
def compose(ctx: Context, operations: List[Dict[str, Any]]) -> str:
    """
    Execute a sequence of composition operations in a single call.
    Can build an entire song in one tool call.

    Parameters:
    - operations: List of operation dicts. Each has an "op" key:

      {"op": "tempo", "bpm": 128}

      {"op": "track", "name": "Drums", "instrument_uri": "...", "volume": 0.7}
      Returns ref index for use in clip ops.

      {"op": "clip", "track": 0, "slot": 0, "name": "Beat", "length": 8,
       "notes": [[36,0,0.5,100], [38,1,0.5,80]]}
      track is absolute Ableton index. Use "ref:N" to reference Nth track
      created in this compose call.

      {"op": "mix", "tracks": [{"index": 0, "volume": 0.7}]}

      {"op": "play", "scene": 0}

    Notes support abbreviated [pitch, time, duration, velocity] tuples.

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = slot 0).
    """
    return json.dumps(_cmd("compose", {"operations": operations}), indent=2)


# ── Individual tools ────────────────────────────────────────────

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)

    NOTE: Index is 0-based (Ableton UI Track 1 = index 0).
    """
    result = _cmd("create_midi_track", {"index": index})
    return f"Created MIDI track: {result.get('name', 'unknown')} at index {result.get('index')}"


@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)

    NOTE: Index is 0-based (Ableton UI Track 1 = index 0).
    """
    result = _cmd("create_audio_track", {"index": index})
    return f"Created audio track: {result.get('name', 'unknown')} at index {result.get('index')}"


@mcp.tool()
def set_track_send(ctx: Context, track_index: int, send_index: int, value: float) -> str:
    """
    Set the send level of a track to a return track.

    Parameters:
    - track_index: The index of the track
    - send_index: The index of the send (0 = Send A, 1 = Send B, etc.)
    - value: The send level (0.0 to 1.0)

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Send A = send_index 0).
    """
    return json.dumps(_cmd("set_track_send", {
        "track_index": track_index, "send_index": send_index, "value": value
    }))


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track

    NOTE: track_index is 0-based (Ableton UI Track 1 = index 0).
    """
    result = _cmd("set_track_name", {"track_index": track_index, "name": name})
    return f"Renamed track to: {result.get('name', name)}"


@mcp.tool()
def set_track_volume(ctx: Context, track_index: int, volume: float) -> str:
    """
    Set the volume of a track.

    Parameters:
    - track_index: The index of the track
    - volume: The volume level (0.0 to 1.0, where 0.85 is approximately 0dB)

    NOTE: track_index is 0-based (Ableton UI Track 1 = index 0).
    """
    return json.dumps(_cmd("set_track_volume", {"track_index": track_index, "volume": volume}))


@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    _cmd("create_clip", {"track_index": track_index, "clip_index": clip_index, "length": length})
    return f"Created clip at track {track_index}, slot {clip_index} ({length} beats)"


@mcp.tool()
def delete_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete a clip from a clip slot.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot to delete from

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    _cmd("delete_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Deleted clip at track {track_index}, slot {clip_index}"


@mcp.tool()
def get_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    return json.dumps(_cmd("get_clip_notes", {"track_index": track_index, "clip_index": clip_index}), indent=2)


@mcp.tool()
def clear_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Remove all MIDI notes from a clip without deleting the clip itself.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    _cmd("clear_notes", {"track_index": track_index, "clip_index": clip_index})
    return f"Cleared all notes from clip at track {track_index}, slot {clip_index}"


@mcp.tool()
def add_notes_to_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    _cmd("add_notes_to_clip", {"track_index": track_index, "clip_index": clip_index, "notes": notes})
    return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"


@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    _cmd("set_clip_name", {"track_index": track_index, "clip_index": clip_index, "name": name})
    return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"


@mcp.tool()
def get_clip_properties(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Get all properties of a clip including loop settings, markers, color, time signature,
    and audio-specific properties (warping, pitch) for audio clips.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot

    NOTE: All indices are 0-based.
    """
    return json.dumps(_cmd("get_clip_properties", {
        "track_index": track_index, "clip_index": clip_index
    }), indent=2)


@mcp.tool()
def set_clip_properties(ctx: Context, track_index: int, clip_index: int,
                        properties: Dict[str, Any]) -> str:
    """
    Set one or more clip properties in a single call.

    Parameters:
    - track_index: The track containing the clip
    - clip_index: The clip slot index
    - properties: Dict of property names to values. Settable properties:
        - looping (bool): Loop on/off
        - loop_start (float): Loop start in beats
        - loop_end (float): Loop end in beats
        - start_marker (float): Clip start marker
        - end_marker (float): Clip end marker
        - color_index (int): Clip color 0-69
        - velocity_amount (float): Velocity randomization 0.0-1.0
        - signature_numerator (int): Time signature numerator
        - signature_denominator (int): Time signature denominator
        - name (str): Clip name
        Audio clips only:
        - warping (bool): Warp on/off
        - warp_mode (int): 0=Beats, 1=Tones, 2=Texture, 3=Re-Pitch, 4=Complex, 6=Pro
        - pitch_coarse (int): Pitch shift in semitones
        - pitch_fine (float): Fine pitch in cents

    NOTE: All indices are 0-based.
    """
    return json.dumps(_cmd("set_clip_properties", {
        "track_index": track_index, "clip_index": clip_index,
        "properties": properties
    }), indent=2)


# ── Meters & Spectrum ─────────────────────────────────────────


@mcp.tool()
def get_meters(ctx: Context, track_index: int = None) -> str:
    """
    Get current output meter levels for tracks, return tracks, and master.
    Returns instantaneous left/right levels (0.0-1.0) and dB values.

    Parameters:
    - track_index: Optional specific track (omit for all tracks)

    NOTE: track_index is 0-based. Levels are instantaneous snapshots;
    for peak detection use get_peak_meters.
    """
    params = {}
    if track_index is not None:
        params["track_index"] = track_index
    return json.dumps(_cmd("get_meters", params), indent=2)


@mcp.tool()
def get_peak_meters(ctx: Context, samples: int = 10, interval_ms: int = 50) -> str:
    """
    Sample track output meters multiple times and return peak values.
    Useful for detecting clipping or comparing track loudness.

    Parameters:
    - samples: Number of samples to take (default: 10, max: 50)
    - interval_ms: Milliseconds between samples (default: 50, min: 20)

    Total duration = samples * interval_ms. Keep samples reasonable.
    """
    import time
    start_result = _cmd("start_peak_meter", {
        "samples": samples, "interval_ms": interval_ms, "reset": True
    })
    if "error" in start_result:
        return json.dumps(start_result, indent=2)
    wait_ms = start_result.get("estimated_duration_ms", 500)
    time.sleep((wait_ms + 100) / 1000.0)
    return json.dumps(_cmd("get_peak_meters"), indent=2)


@mcp.tool()
def get_spectrum(ctx: Context, track_index: int = None) -> str:
    """
    Get frequency spectrum data from M4L SpectrumAnalyzer device.
    Returns 7 perceptual bands in dB: sub, low, low_mid, mid, high_mid, high, air.

    Parameters:
    - track_index: Track to read spectrum from (default: master track)

    Requires the SpectrumAnalyzer Max for Live device on the target track.
    """
    params = {}
    if track_index is not None:
        params["track_index"] = track_index
    return json.dumps(_cmd("get_spectrum", params), indent=2)


# ── Transport ───────────────────────────────────────────────────

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    _cmd("set_tempo", {"tempo": tempo})
    return f"Set tempo to {tempo} BPM"


@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    _cmd("fire_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Started playing clip at track {track_index}, slot {clip_index}"


@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    _cmd("stop_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Stopped clip at track {track_index}, slot {clip_index}"


@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    _cmd("start_playback")
    return "Started playback"


@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    _cmd("stop_playback")
    return "Stopped playback"


@mcp.tool()
def start_recording(ctx: Context) -> str:
    """Start session recording in Ableton. Also starts playback if not already playing."""
    return json.dumps(_cmd("start_recording"))


@mcp.tool()
def stop_recording(ctx: Context) -> str:
    """Stop session recording in Ableton."""
    return json.dumps(_cmd("stop_recording"))


@mcp.tool()
def start_arrangement_recording(ctx: Context, stop_after_beats: int = None) -> str:
    """
    Start arrangement recording in Ableton. Records the session performance
    (scene launches, clip playback) into the Arrangement timeline.

    Parameters:
    - stop_after_beats: Optional number of beats after which to automatically
      stop recording and playback. Useful for capturing a fixed-length arrangement.
    """
    params = {}
    if stop_after_beats is not None:
        params["stop_after_beats"] = stop_after_beats
    return json.dumps(_cmd("start_arrangement_recording", params))


@mcp.tool()
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Fire all clips in a scene (row) simultaneously.

    Parameters:
    - scene_index: The index of the scene to fire

    NOTE: scene_index is 0-based (Ableton UI Scene 1 = index 0).
    """
    return json.dumps(_cmd("fire_scene", {"scene_index": scene_index}))


@mcp.tool()
def fire_scene_sequence(ctx: Context, scenes: List[Dict[str, Union[int, float]]]) -> str:
    """
    Fire a sequence of scenes with beat-based timing, all executed inside Ableton
    with no network round-trip latency between scene changes.

    Parameters:
    - scenes: List of scene entries, each with:
        - scene_index: The index of the scene to fire
        - delay_beats: Beats from the START of the sequence before firing this scene
          (use 0 for the first scene)

    Example: Play scene 0 immediately, scene 5 after 16 beats, scene 2 after 32 beats:
    [
        {"scene_index": 0, "delay_beats": 0},
        {"scene_index": 5, "delay_beats": 16},
        {"scene_index": 2, "delay_beats": 32}
    ]

    NOTE: scene_index is 0-based (Ableton UI Scene 1 = index 0).
    """
    return json.dumps(_cmd("fire_scene_sequence", {"scenes": scenes}))


# ── Device parameters ───────────────────────────────────────────

@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Get all parameters of a device on a track.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on the track

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0).
    """
    return json.dumps(_cmd("get_device_parameters", {
        "track_index": track_index, "device_index": device_index
    }), indent=2)


@mcp.tool()
def set_device_parameter(ctx: Context, track_index: int, device_index: int,
                         parameter_index: int, value: float) -> str:
    """
    Set a device parameter value.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on the track
    - parameter_index: The index of the parameter (use get_device_parameters to find indices)
    - value: The new value (will be clamped to parameter's min/max range)

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0).
    """
    return json.dumps(_cmd("set_device_parameter", {
        "track_index": track_index, "device_index": device_index,
        "parameter_index": parameter_index, "value": value
    }))


# ── Browser ─────────────────────────────────────────────────────

@mcp.tool()
def search_browser(ctx: Context, query: str, max_results: int = 20) -> str:
    """
    Search Ableton's browser for instruments, effects, or sounds by name.

    Parameters:
    - query: Search term (case-insensitive, matches partial names)
    - max_results: Maximum number of results to return (default: 20)
    """
    return json.dumps(_cmd("search_browser", {"query": query, "max_results": max_results}), indent=2)


@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.

    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    result = _cmd("get_browser_tree", {"category_type": category_type})
    output = f"Browser tree for '{category_type}':\n\n"
    for cat in result.get("categories", []):
        name = cat.get("name", "Unknown")
        uri = cat.get("uri", "")
        output += f"  {name}"
        if uri:
            output += f" (uri: {uri})"
        output += "\n"
    return output


@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.

    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    return json.dumps(_cmd("get_browser_items_at_path", {"path": path}), indent=2)


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')

    NOTE: track_index is 0-based (Ableton UI Track 1 = index 0).
    """
    result = _cmd("load_browser_item", {"track_index": track_index, "item_uri": uri})
    if result.get("loaded", False):
        return f"Loaded '{result.get('item_name', uri)}' on track {track_index}"
    return f"Failed to load instrument with URI '{uri}'"


@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.

    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')

    NOTE: track_index is 0-based (Ableton UI Track 1 = index 0).
    """
    result = _cmd("load_browser_item", {"track_index": track_index, "item_uri": rack_uri})
    if not result.get("loaded", False):
        return f"Failed to load drum rack with URI '{rack_uri}'"
    kit_result = _cmd("get_browser_items_at_path", {"path": kit_path})
    if "error" in kit_result:
        return f"Loaded drum rack but failed to find kit: {kit_result.get('error')}"
    loadable = [i for i in kit_result.get("items", []) if i.get("is_loadable")]
    if not loadable:
        return f"Loaded drum rack but no loadable kits at '{kit_path}'"
    _cmd("load_browser_item", {"track_index": track_index, "item_uri": loadable[0]["uri"]})
    return f"Loaded drum rack and kit '{loadable[0].get('name')}' on track {track_index}"


# ── Save / Load ─────────────────────────────────────────────────

@mcp.tool()
def save_set(ctx: Context) -> str:
    """Save the current Ableton Live set."""
    _cmd("save_set")
    return "Set saved"


@mcp.tool()
def save_set_as(ctx: Context, file_path: str) -> str:
    """
    Save the current Ableton Live set to a new file.

    Parameters:
    - file_path: The full file path to save to (e.g., '/Users/me/Music/my_track.als')
    """
    _cmd("save_set_as", {"file_path": file_path})
    return f"Set saved to {file_path}"


# ── Sidechain ───────────────────────────────────────────────────

@mcp.tool()
def setup_sidechain(ctx: Context, track_index: int, device_index: int,
                    sidechain_source_track: int) -> str:
    """
    Configure a compressor's sidechain input to listen to another track.

    Parameters:
    - track_index: The track containing the compressor
    - device_index: The index of the Compressor device on that track
    - sidechain_source_track: The track index to use as sidechain input

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0).
    """
    return json.dumps(_cmd("setup_sidechain", {
        "track_index": track_index,
        "device_index": device_index,
        "sidechain_source_track": sidechain_source_track
    }), indent=2)


# ── Style Index ──────────────────────────────────────────────────

@mcp.tool()
def build_index(ctx: Context, force: bool = False) -> str:
    """
    Crawl Ableton's browser and cache all instruments, effects, and sounds to disk.
    Skips if the index is less than 24 hours old, unless force=True.

    Parameters:
    - force: Rebuild even if the index is fresh (default: False)
    """
    age = style_index.index_age_hours()
    if not force and age is not None and age < 24:
        idx = style_index.load_index()
        return json.dumps({
            "skipped": True,
            "reason": f"Index is {age:.1f}h old (< 24h). Use force=True to rebuild.",
            "stats": idx.get("stats", {}),
        }, indent=2)

    crawl_result = _cmd("crawl_browser", {"category": "all", "max_depth": 10}, timeout=120.0)
    save_result = style_index.save_index(crawl_result)
    return json.dumps(save_result, indent=2)


@mcp.tool()
def search_index(ctx: Context, query: str, category: str = "all", limit: int = 50) -> str:
    """
    Search the cached browser index — instant, no Ableton round-trip.
    Run build_index() first if the index doesn't exist.

    Parameters:
    - query: Search term (case-insensitive, matches name and path)
    - category: Filter by category ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    - limit: Maximum results (default: 50)
    """
    result = style_index.search_index(query, category, limit)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_palette(ctx: Context, style: str) -> str:
    """
    Return the instrument/effect palette for a music style.
    Resolves URIs against the cached browser index. Run build_index() first.

    Parameters:
    - style: Style name (e.g., 'lofi', 'disco_house')
    """
    result = style_index.get_palette(style)
    return json.dumps(result, indent=2)


@mcp.tool()
def analyze_session(ctx: Context) -> str:
    """
    Analyze the current session musically. Reads all tracks via snapshot,
    then returns: per-track role detection, key/chord analysis, mix balance,
    FX audit, energy arc, and style match against palettes.

    Use this to understand what's in the session before giving feedback.
    """
    snap = _cmd("snapshot", timeout=30.0)
    result = analysis.analyze_session_data(snap)

    # Also score against palettes
    tracks_for_palette = []
    for t in snap.get("tracks", []):
        tracks_for_palette.append({
            "name": t.get("name", ""),
            "devices": t.get("devices", []),
        })
    palette_scores = style_index.analyze_session_against_palettes(tracks_for_palette)
    result["palette_match"] = palette_scores

    return json.dumps(result, indent=2)


@mcp.tool()
def analyze_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Analyze a specific clip musically — detect key, chords, rhythmic density,
    energy arc, and register. Returns structured music theory analysis.

    Parameters:
    - track_index: The track containing the clip
    - clip_index: The clip slot index

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    clip_data = _cmd("get_clip_notes", {
        "track_index": track_index, "clip_index": clip_index
    })
    notes = clip_data.get("notes", [])
    length = clip_data.get("clip_length", 16.0)
    clip_name = clip_data.get("clip_name", "")

    # Normalize notes to [pitch, time, dur, vel] format
    normalized = []
    for n in notes:
        if isinstance(n, dict):
            normalized.append([n["pitch"], n["start_time"], n["duration"], n["velocity"]])
        else:
            normalized.append(n)

    result = analysis.analyze_notes(normalized, length)
    result["clip_name"] = clip_name
    result["track_index"] = track_index
    result["clip_index"] = clip_index
    return json.dumps(result, indent=2)


@mcp.tool()
def swap_instrument(ctx: Context, track_index: int, instrument_uri: str) -> str:
    """
    Swap the instrument on a track while preserving effects and clips.
    Loads a new instrument by URI — the previous instrument is replaced
    but all effects in the chain and all clip data remain intact.

    Use with palette alternatives to try different sounds on the same part.

    Parameters:
    - track_index: The track to swap the instrument on
    - instrument_uri: URI of the new instrument to load

    NOTE: track_index is 0-based (Ableton UI Track 1 = index 0).
    """
    result = _cmd("load_browser_item", {
        "track_index": track_index, "item_uri": instrument_uri
    })
    if result.get("loaded", False):
        return f"Swapped instrument to '{result.get('item_name', instrument_uri)}' on track {track_index}. Effects and clips preserved."
    return f"Failed to load instrument with URI '{instrument_uri}'"


# ── Duplicate / Copy ────────────────────────────────────────────

@mcp.tool()
def duplicate_clip(ctx: Context, src_track_index: int, src_clip_index: int,
                   dst_track_index: int, dst_clip_index: int,
                   name: str = "", overwrite: bool = False) -> str:
    """
    Copy a clip from one slot to another (same or different track).
    All note data is copied inside Ableton — no network transfer.

    Parameters:
    - src_track_index: Source track index
    - src_clip_index: Source clip slot index
    - dst_track_index: Destination track index
    - dst_clip_index: Destination clip slot index
    - name: Name for the new clip (default: same as source)
    - overwrite: If true, overwrite existing clip at destination

    NOTE: All indices are 0-based (Ableton UI Track 1 = index 0, Scene 1 = clip_index 0).
    """
    params = {
        "src_track_index": src_track_index, "src_clip_index": src_clip_index,
        "dst_track_index": dst_track_index, "dst_clip_index": dst_clip_index,
        "overwrite": overwrite
    }
    if name:
        params["name"] = name
    return json.dumps(_cmd("duplicate_clip", params), indent=2)


@mcp.tool()
def duplicate_scene(ctx: Context, src_scene_index: int, dst_scene_index: int,
                    name: str = "", overwrite: bool = False) -> str:
    """
    Copy all clips from one scene (row) to another.
    Copies every clip across all tracks in a single call.

    Parameters:
    - src_scene_index: Source scene (row) index
    - dst_scene_index: Destination scene (row) index
    - name: Name for all copied clips (default: keep original names)
    - overwrite: If true, overwrite existing clips at destination

    NOTE: scene indices are 0-based (Ableton UI Scene 1 = index 0).
    """
    params = {
        "src_scene_index": src_scene_index, "dst_scene_index": dst_scene_index,
        "overwrite": overwrite
    }
    if name:
        params["name"] = name
    return json.dumps(_cmd("duplicate_scene", params), indent=2)


# ── Hot-reload ──────────────────────────────────────────────────

@mcp.tool()
def reload_commands(ctx: Context) -> str:
    """Hot-reload the Remote Script's command handlers without restarting Ableton."""
    return json.dumps(_cmd("reload"))


# ── Main ────────────────────────────────────────────────────────

def main():
    mcp.run()


if __name__ == "__main__":
    main()
