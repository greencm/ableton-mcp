# AbletonMCP - Ableton Live Model Context Protocol Integration

AbletonMCP connects Ableton Live to Claude AI through the Model Context Protocol (MCP), allowing Claude to directly interact with and control Ableton Live. This integration enables prompt-assisted music production, track creation, and Live session manipulation.

This is a fork of [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) with additional features listed below.

### Join the Community

Give feedback, get inspired, and build on top of the MCP: [Discord](https://discord.gg/3ZrMyGKnaU). Originally made by [Siddharth](https://x.com/sidahuj)

## Features

- **Two-way communication**: Connect Claude AI to Ableton Live through a socket-based server
- **Track manipulation**: Create, modify, and manipulate MIDI and audio tracks
- **Instrument and effect selection**: Claude can access and load the right instruments, effects and sounds from Ableton's library
- **Clip creation**: Create and edit MIDI clips with notes
- **Session control**: Start and stop playback, fire clips, and control transport

### Additional Features (this fork)

- **Composition flow tools**: `create_track`, `write_clip`, `set_mix`, and `compose` — batch operations that replace multi-call sequences, allowing Claude to build an entire song in a single tool call
- **Scene control**: `fire_scene` to trigger all clips in a row, and `fire_scene_sequence` for beat-timed scene arrangements with zero network latency between transitions
- **Session recording**: `start_recording` / `stop_recording` for recording MIDI input into Session View clip slots
- **Arrangement recording**: `start_arrangement_recording` with optional `stop_after_beats` parameter — records scene performances into the Arrangement timeline for export, with automatic timed stop
- **Sidechain routing**: `setup_sidechain` to configure a compressor's sidechain input from another track
- **Save**: `save_set` and `save_set_as` for saving the Live set
- **Clip property control**: `get_clip_properties` and `set_clip_properties` — read and write loop settings, markers, color, warp mode, pitch, and more
- **Track metering**: `get_meters` for instantaneous output levels (dB) across all tracks, and `get_peak_meters` for multi-sample peak detection
- **Spectrum analysis**: `get_spectrum` reads 7 perceptual frequency bands from a Max for Live device (see [Spectrum Analyzer Setup](#spectrum-analyzer-setup-max-for-live))
- **Auto-color clips**: Clips created via `compose()` are automatically colored by track role (drums=red, bass=blue, keys=yellow, etc.)
- **Hot-reload architecture**: The Remote Script is split into a thin bootstrap (`__init__.py`) and a `commands.py` module that can be reloaded without restarting Ableton via the `reload_commands` tool
- **Ableton 12 compatibility**: Adds `get_capabilities()` required by Ableton 12's control surface loader

## Components

The system consists of two main components:

1. **Ableton Remote Script** (`AbletonMCP_Remote_Script/`): A MIDI Remote Script for Ableton Live that creates a socket server to receive and execute commands. Uses a hot-reload architecture with `__init__.py` (bootstrap) and `commands.py` (handlers).
2. **MCP Server** (`MCP_Server/server.py`): A Python server that implements the Model Context Protocol and connects to the Ableton Remote Script

## Installation

### Prerequisites

- **Ableton Live 11 or newer** (requires the Live 11+ MIDI note API for probability, velocity deviation, and release velocity support). Tested on macOS; Windows is untested.
- Python 3.14 or newer
- [uv package manager](https://astral.sh/uv)

If you're on Mac, please install uv as:
```
brew install uv
```

Otherwise, install from [uv's official website][https://docs.astral.sh/uv/getting-started/installation/]

⚠️ Do not proceed before installing UV

### Claude for Desktop Integration

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Go to Claude > Settings > Developer > Edit Config > claude_desktop_config.json to include the following:

```json
{
    "mcpServers": {
        "AbletonMCP": {
            "command": "uvx",
            "args": [
                "ableton-mcp"
            ]
        }
    }
}
```

### Cursor Integration

Run ableton-mcp without installing it permanently through uvx. Go to Cursor Settings > MCP and paste this as a command:

```
uvx ableton-mcp
```

⚠️ Only run one instance of the MCP server (either on Cursor or Claude Desktop), not both

### Installing the Ableton Remote Script

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Download the `AbletonMCP_Remote_Script/__init__.py` file from this repo

2. Copy the folder to Ableton's MIDI Remote Scripts directory. Different OS and versions have different locations. **One of these should work, you might have to look**:

   **For macOS:**
   - Method 1: Go to Applications > Right-click on Ableton Live app → Show Package Contents → Navigate to:
     `Contents/App-Resources/MIDI Remote Scripts/`
   - Method 2: If it's not there in the first method, use the direct path (replace XX with your version number):
     `/Users/[Username]/Library/Preferences/Ableton/Live XX/User Remote Scripts`
   
   **For Windows (untested):**
   - Method 1:
     `C:\Users\[Username]\AppData\Roaming\Ableton\Live x.x.x\Preferences\User Remote Scripts`
   - Method 2:
     `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   - Method 3:
     `C:\Program Files\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   *Note: Replace XX with your Ableton version number (e.g., 11, 12)*

4. Create a folder called 'AbletonMCP' in the Remote Scripts directory and copy both `__init__.py` and `commands.py` from `AbletonMCP_Remote_Script/` into it

3. Launch Ableton Live

4. Go to Settings/Preferences → Link, Tempo & MIDI

5. In the Control Surface dropdown, select "AbletonMCP"

6. Set Input and Output to "None"

## Usage

### Starting the Connection

1. Ensure the Ableton Remote Script is loaded in Ableton Live
2. Make sure the MCP server is configured in Claude Desktop or Cursor
3. The connection should be established automatically when you interact with Claude

### Using with Claude

Once the config file has been set on Claude, and the remote script is running in Ableton, you will see a hammer icon with tools for the Ableton MCP.

## Capabilities

- Get session and track information
- Create and modify MIDI and audio tracks
- Create, edit, and trigger clips
- Control playback (start, stop, fire clips and scenes)
- Load instruments and effects from Ableton's browser
- Add notes to MIDI clips
- Change tempo and other session parameters
- Record session or arrangement performances
- Batch composition with single-call track/clip/mix creation
- Beat-timed scene sequencing for full song arrangements
- Sidechain routing configuration
- Save and export Live sets
- Hot-reload command handlers without restarting Ableton

## Example Commands

Here are some examples of what you can ask Claude to do:

- "Create an 80s synthwave track" [Demo](https://youtu.be/VH9g66e42XA)
- "Create a Metro Boomin style hip-hop beat"
- "Create a new MIDI track with a synth bass instrument"
- "Add reverb to my drums"
- "Create a 4-bar MIDI clip with a simple melody"
- "Get information about the current Ableton session"
- "Load a 808 drum rack into the selected track"
- "Add a jazz chord progression to the clip in track 1"
- "Set the tempo to 120 BPM"
- "Play the clip in track 2"


## Spectrum Analyzer Setup (Max for Live)

The `get_spectrum` tool reads frequency band levels from a custom Max for Live audio effect. This device splits audio into 7 perceptual bands (Sub, Low, Low-Mid, Mid, High-Mid, High, Air) and exposes their dB levels as device parameters that the MCP can read.

**Requirements:** Ableton Live Suite (includes Max for Live) or Max for Live add-on.

### Setup

1. Copy `m4l/Spectrum-MCP.amxd` to your User Library's Max Audio Effect presets folder:
   - **macOS:** `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/`
   - **Windows:** `C:\Users\[Username]\Documents\Ableton\User Library\Presets\Audio Effects\Max Audio Effect\`
2. In Ableton, drag **Spectrum-MCP** from the browser onto the **Master track** (or any track you want to analyze).

That's it — the device is ready to use.

### How It Works

The device passes audio through transparently (no effect on sound) while analyzing 7 frequency bands via bandpass filters (`svf~`), RMS averaging, and dB conversion. Each band's level is exposed as a `live.dial` parameter with **Parameter Visibility** set to "Automated and Stored", which allows the Remote Script to read values through Ableton's device parameter API.

| Band | Frequency Range | Center Freq |
|------|----------------|-------------|
| Sub | 20–60 Hz | 40 Hz |
| Low | 60–250 Hz | 125 Hz |
| Low-Mid | 250–500 Hz | 350 Hz |
| Mid | 500–2000 Hz | 1000 Hz |
| High-Mid | 2000–4000 Hz | 3000 Hz |
| High | 4000–12000 Hz | 7000 Hz |
| Air | 12000–20000 Hz | 16000 Hz |

Each band reports its level in dB (range: -60 to +6 dB).

### Usage

Once the device is loaded on a track:

```
# Read spectrum from master track (default)
get_spectrum()

# Read spectrum from a specific track
get_spectrum(track_index=2)
```

Returns:
```json
{
  "track": "Master",
  "bands": {
    "sub": -18.3,
    "low": -12.1,
    "low_mid": -8.5,
    "mid": -6.2,
    "high_mid": -9.8,
    "high": -14.3,
    "air": -22.7
  },
  "device": "Spectrum-MCP"
}
```

If no spectrum device is found on the track, the tool returns an error message with setup instructions.

## Troubleshooting

- **Connection issues**: Make sure the Ableton Remote Script is loaded, and the MCP server is configured on Claude
- **Timeout errors**: Try simplifying your requests or breaking them into smaller steps
- **Have you tried turning it off and on again?**: If you're still having connection errors, try restarting both Claude and Ableton Live

## Technical Details

### Communication Protocol

The system uses a simple JSON-based protocol over TCP sockets:

- Commands are sent as JSON objects with a `type` and optional `params`
- Responses are JSON objects with a `status` and `result` or `message`

### Limitations & Security Considerations

- Creating complex musical arrangements might need to be broken down into smaller steps
- The tool is designed to work with Ableton's default devices and browser items
- Always save your work before extensive experimentation

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This is a third-party integration and not made by Ableton.
