# AbletonMCP/__init__.py — Thin bootstrap with hot-reload support
# Command handlers live in commands.py and can be reloaded without restarting Ableton.
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback
import importlib
import sys
import os

try:
    import Queue as queue
except ImportError:
    import queue

DEFAULT_PORT = 9877
HOST = "localhost"


def get_capabilities():
    from _Framework.Capabilities import CONTROLLER_ID_KEY, PORTS_KEY
    return {CONTROLLER_ID_KEY: CONTROLLER_ID_KEY, PORTS_KEY: []}


def create_instance(c_instance):
    return AbletonMCP(c_instance)


class AbletonMCP(ControlSurface):

    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP initializing...")
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        self._song = self.song()
        self._commands = None
        self._load_commands()
        self.start_server()
        self.log_message("AbletonMCP initialized")
        self.show_message("AbletonMCP: Listening on port " + str(DEFAULT_PORT))

    # ── Hot-reload ──────────────────────────────────────────────

    def _commands_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "commands.py")

    def _load_commands(self):
        """Load (or reload) the commands module."""
        try:
            mod_name = "AbletonMCP.commands"
            if mod_name in sys.modules:
                self._commands = importlib.reload(sys.modules[mod_name])
            else:
                from . import commands
                self._commands = commands
            self.log_message("Commands module loaded: " + str(dir(self._commands)))
        except Exception as e:
            self.log_message("Error loading commands module: " + str(e))
            self.log_message(traceback.format_exc())

    def _reload_commands(self):
        """Hot-reload the commands module."""
        try:
            mod_name = "AbletonMCP.commands"
            if mod_name in sys.modules:
                self._commands = importlib.reload(sys.modules[mod_name])
            else:
                self._load_commands()
            self.log_message("Commands module reloaded successfully")
            self.show_message("AbletonMCP: Commands reloaded")
            return {"reloaded": True}
        except Exception as e:
            self.log_message("Error reloading commands: " + str(e))
            self.log_message(traceback.format_exc())
            raise

    # ── Socket server ───────────────────────────────────────────

    def disconnect(self):
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        if self.server:
            try:
                self.server.close()
            except:
                pass
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
        for t in self.client_threads[:]:
            if t.is_alive():
                self.log_message("Client thread still alive during disconnect")
        ControlSurface.disconnect(self)

    def start_server(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error - " + str(e))

    def _server_thread(self):
        try:
            self.server.settimeout(1.0)
            while self.running:
                try:
                    client, address = self.server.accept()
                    self.log_message("Connection from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    t = threading.Thread(target=self._handle_client, args=(client,))
                    t.daemon = True
                    t.start()
                    self.client_threads.append(t)
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
        except Exception as e:
            self.log_message("Server thread error: " + str(e))

    def _handle_client(self, client):
        client.settimeout(None)
        buf = ''
        try:
            while self.running:
                try:
                    data = client.recv(8192)
                    if not data:
                        break
                    try:
                        buf += data.decode('utf-8')
                    except AttributeError:
                        buf += data
                    try:
                        command = json.loads(buf)
                        buf = ''
                        response = self._process_command(command)
                        client.sendall(json.dumps(response).encode('utf-8'))
                    except ValueError:
                        continue
                except Exception as e:
                    self.log_message("Client error: " + str(e))
                    try:
                        client.sendall(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
                    except:
                        break
                    if not isinstance(e, ValueError):
                        break
        finally:
            try:
                client.close()
            except:
                pass

    # ── Command dispatch ────────────────────────────────────────

    # Read-only commands that can run on the socket thread
    READ_COMMANDS = {
        "get_session_info", "get_track_info",
        "get_browser_item", "get_browser_categories", "get_browser_items",
        "get_browser_tree", "get_browser_items_at_path",
        "crawl_browser",
    }

    def _process_command(self, command):
        command_type = command.get("type", "")
        params = command.get("params", {})
        response = {"status": "success", "result": {}}

        try:
            # Built-in: reload
            if command_type == "reload":
                response_queue = queue.Queue()
                def do_reload():
                    try:
                        result = self._reload_commands()
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        response_queue.put({"status": "error", "message": str(e)})
                try:
                    self.schedule_message(0, do_reload)
                except:
                    do_reload()
                try:
                    r = response_queue.get(timeout=10.0)
                    response.update(r)
                except queue.Empty:
                    response = {"status": "error", "message": "Reload timeout"}
                return response

            # Delegate to commands module
            if not self._commands:
                response["status"] = "error"
                response["message"] = "Commands module not loaded"
                return response

            handler = getattr(self._commands, "handle_" + command_type, None)
            if handler is None:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
                return response

            # Read-only commands run directly on socket thread
            if command_type in self.READ_COMMANDS:
                response["result"] = handler(self, params)
                return response

            # State-modifying commands run on the main thread
            response_queue = queue.Queue()
            def main_thread_task():
                try:
                    result = handler(self, params)
                    response_queue.put({"status": "success", "result": result})
                except Exception as e:
                    self.log_message("Main thread error: " + str(e))
                    self.log_message(traceback.format_exc())
                    response_queue.put({"status": "error", "message": str(e)})
            try:
                self.schedule_message(0, main_thread_task)
            except:
                main_thread_task()
            try:
                task_response = response_queue.get(timeout=10.0)
                if task_response.get("status") == "error":
                    response["status"] = "error"
                    response["message"] = task_response.get("message", "Unknown error")
                else:
                    response["result"] = task_response.get("result", {})
            except queue.Empty:
                response["status"] = "error"
                response["message"] = "Timeout waiting for operation to complete"

        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)

        return response
