# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union

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

    def receive_full_response(self, sock, buffer_size=8192):
        chunks = []
        sock.settimeout(15.0)
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

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")

        command = {"type": command_type, "params": params or {}}

        is_modifying = command_type not in {
            "get_session_info", "get_track_info",
            "get_browser_item", "get_browser_categories", "get_browser_items",
            "get_browser_tree", "get_browser_items_at_path",
            "get_clip_notes", "get_device_parameters", "search_browser",
        }

        try:
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            if is_modifying:
                import time
                time.sleep(0.1)
            self.sock.settimeout(15.0 if is_modifying else 10.0)
            response_data = self.receive_full_response(self.sock)
            response = json.loads(response_data.decode('utf-8'))
            if response.get("status") == "error":
                raise Exception(response.get("message", "Unknown error"))
            if is_modifying:
                import time
                time.sleep(0.1)
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

def _cmd(command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    return get_ableton_connection().send_command(command_type, params)


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
    """
    return json.dumps(_cmd("get_track_info", {"track_index": track_index}), indent=2)


# ── Track creation & config ─────────────────────────────────────

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    result = _cmd("create_midi_track", {"index": index})
    return f"Created MIDI track: {result.get('name', 'unknown')} at index {result.get('index')}"


@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    result = _cmd("create_audio_track", {"index": index})
    return f"Created audio track: {result.get('name', 'unknown')} at index {result.get('index')}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
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
    """
    return json.dumps(_cmd("set_track_volume", {"track_index": track_index, "volume": volume}))


@mcp.tool()
def set_track_send(ctx: Context, track_index: int, send_index: int, value: float) -> str:
    """
    Set the send level of a track to a return track.

    Parameters:
    - track_index: The index of the track
    - send_index: The index of the send (0 = Send A, 1 = Send B, etc.)
    - value: The send level (0.0 to 1.0)
    """
    return json.dumps(_cmd("set_track_send", {
        "track_index": track_index, "send_index": send_index, "value": value
    }))


# ── Clips ───────────────────────────────────────────────────────

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
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
    """
    _cmd("delete_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Deleted clip at track {track_index}, slot {clip_index}"


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
    """
    _cmd("add_notes_to_clip", {"track_index": track_index, "clip_index": clip_index, "notes": notes})
    return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"


@mcp.tool()
def get_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    return json.dumps(_cmd("get_clip_notes", {"track_index": track_index, "clip_index": clip_index}), indent=2)


@mcp.tool()
def clear_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Remove all MIDI notes from a clip without deleting the clip itself.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    _cmd("clear_notes", {"track_index": track_index, "clip_index": clip_index})
    return f"Cleared all notes from clip at track {track_index}, slot {clip_index}"


@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    _cmd("set_clip_name", {"track_index": track_index, "clip_index": clip_index, "name": name})
    return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"


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
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Fire all clips in a scene (row) simultaneously.

    Parameters:
    - scene_index: The index of the scene to fire
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
    """
    return json.dumps(_cmd("set_device_parameter", {
        "track_index": track_index, "device_index": device_index,
        "parameter_index": parameter_index, "value": value
    }))


# ── Browser ─────────────────────────────────────────────────────

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
def search_browser(ctx: Context, query: str, max_results: int = 20) -> str:
    """
    Search Ableton's browser for instruments, effects, or sounds by name.

    Parameters:
    - query: Search term (case-insensitive, matches partial names)
    - max_results: Maximum number of results to return (default: 20)
    """
    return json.dumps(_cmd("search_browser", {"query": query, "max_results": max_results}), indent=2)


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
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
    """
    # Load rack
    result = _cmd("load_browser_item", {"track_index": track_index, "item_uri": rack_uri})
    if not result.get("loaded", False):
        return f"Failed to load drum rack with URI '{rack_uri}'"
    # Browse for kit
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
    """
    return json.dumps(_cmd("setup_sidechain", {
        "track_index": track_index,
        "device_index": device_index,
        "sidechain_source_track": sidechain_source_track
    }), indent=2)


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
