"""
Server Helper — SSH / HTTP Communication for VoiceWidget
=========================================================
Handles all server-side communication: Whisper API, Tmux, and SSH.
"""
import json, subprocess, io, os
from pathlib import Path

try:
    import urllib.request
except ImportError:
    urllib = None


class ServerHelper:
    """Verbindung zum Whisper-Server via HTTP und SSH."""

    def __init__(self, host="100.100.196.29", user="server", port=22, whisper_port=8766):
        self.host = host
        self.user = user
        self.port = port
        self.whisper_url = f"http://{host}:{whisper_port}"

    # ── Connection Test ──
    def check(self):
        """Prüft ob der Whisper-Server erreichbar ist."""
        try:
            req = urllib.request.Request(f"{self.whisper_url}/health")
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)}

    # ── Transcription ──
    def transcribe(self, wav_bytes):
        """Sendet WAV-Audio an Whisper API → JSON mit Text + Timestamps."""
        boundary = "----VoiceWidget"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="voice.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode() + wav_bytes + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self.whisper_url}/transcribe",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)}

    # ── Tmux Sessions ──
    def get_tmux_sessions(self):
        """Listet alle aktiven Tmux-Sessions auf dem Server."""
        try:
            cmd = self._ssh_cmd(
                "tmux list-sessions -F '#{session_name}' 2>/dev/null | head -20"
            )
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            sessions = [s.strip() for s in r.stdout.split("\n") if s.strip()]
            return sessions if sessions else []
        except subprocess.TimeoutExpired:
            return []
        except Exception:
            return []

    def send_to_tmux(self, session_name, text):
        """Fügt Text in eine bestimmte Tmux-Session ein."""
        try:
            safe_text = text.replace("'", "'\\''").replace("\n", "\\n")
            cmd = self._ssh_cmd(
                f"tmux send-keys -t '{session_name}' '{safe_text}' Enter"
            )
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except:
            return False

    def send_to_tmux_pane(self, session_name, pane_index, text):
        """Fügt Text in einen bestimmten Pane einer Tmux-Session ein."""
        try:
            safe_text = text.replace("'", "'\\''").replace("\n", "\\n")
            target = f"'{session_name}:{pane_index}'" if pane_index else f"'{session_name}'"
            cmd = self._ssh_cmd(
                f"tmux send-keys -t {target} '{safe_text}' Enter"
            )
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except:
            return False

    def _ssh_cmd(self, remote_cmd):
        """Baut SSH-Kommando mit korrekten Flags."""
        return [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            "-p", str(self.port),
            f"{self.user}@{self.host}",
            remote_cmd,
        ]
