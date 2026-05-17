#!/usr/bin/env python3
"""
VoiceWidget — Liquid Glass Transcription Widget
================================================
Windows Desktop Widget: Sprachaufnahme → Server-Transkription → Tmux-Einfügung

Usage:
    python widget.py              # Normal start
    python widget.py --debug      # Debug mode (console output)
"""
import sys, os, json, configparser, threading, queue, time, subprocess, tempfile, shutil
from pathlib import Path
from datetime import datetime

# ── Config ─────────────────────────────────────────────
CONFIG_FILE = Path(__file__).parent / "config.ini"
DEFAULT_CONFIG = {
    "Server": {
        "host": "100.100.196.29",
        "user": "server",
        "port": "22",
        "whisper_port": "8766",
    },
    "Widget": {
        "theme": "liquid_glass",
        "opacity": "0.92",
        "autostart": "false",
    }
}

def load_config():
    config = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
    for section, keys in DEFAULT_CONFIG.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, val in keys.items():
            if not config.has_option(section, key):
                config.set(section, key, val)
    with open(CONFIG_FILE, "w") as f:
        config.write(f)
    return config

CONFIG = load_config()
SERVER_HOST = CONFIG.get("Server", "host")
SERVER_USER = CONFIG.get("Server", "user")
SERVER_PORT = CONFIG.get("Server", "port")
WHISPER_PORT = CONFIG.get("Server", "whisper_port")
WIDGET_OPACITY = float(CONFIG.get("Widget", "opacity"))


# ── CustomTkinter + Imports ───────────────────────────
try:
    import customtkinter as ctk
    from PIL import Image, ImageDraw, ImageTk
except ImportError as e:
    print(f"Fehlende Abhaengigkeit: {e}")
    print("Bitte installieren: pip install customtkinter Pillow")
    sys.exit(1)

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
except ImportError:
    print("sounddevice nicht installiert. Audio-Aufnahme deaktiviert.")
    print("   pip install sounddevice soundfile numpy")
    sd = None
    sf = None
    np = None

# ── Server Connection ─────────────────────────────────
class ServerHelper:
    """SSH + HTTP Kommunikation mit dem Server."""

    def __init__(self):
        self.host = SERVER_HOST
        self.user = SERVER_USER
        self.port = int(SERVER_PORT)
        self.whisper_url = f"http://{self.host}:{WHISPER_PORT}"

    def check_connection(self):
        """Prueft ob Server erreichbar ist."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.whisper_url}/health")
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)}

    def transcribe(self, wav_data):
        """Sendet Audio an Whisper API und gibt Text zurueck."""
        import urllib.request
        boundary = "----VoiceWidgetBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="voice.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode() + wav_data + f"\r\n--{boundary}--\r\n".encode()

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

    def get_tmux_sessions(self):
        """Holt Liste der aktiven Tmux Sessions via SSH."""
        try:
            cmd = [
                "ssh", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=5",
                f"{self.user}@{self.host}",
                "-p", str(self.port),
                "tmux list-sessions -F '#{session_name}' 2>/dev/null || echo 'NO_TMUX'"
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            sessions = [s.strip() for s in r.stdout.split("\n") if s.strip() and s.strip() != "NO_TMUX"]
            return sessions if sessions else []
        except:
            return []

    def send_to_tmux(self, session_name, text):
        """Fuegt Text in eine Tmux Session ein."""
        try:
            safe = text.replace("'", "'\"'\"'").replace("\n", "\\n")
            cmd = [
                "ssh", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=5",
                f"{self.user}@{self.host}",
                "-p", str(self.port),
                f"tmux send-keys -t '{session_name}' '{safe}' Enter"
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except:
            return False


# ── Liquid Glass Theme (nur hex, tkinter-kompatibel) ──
# Die Transparenz/Glass-Effekt kommt ueber window.attributes("-alpha", ...)
# und die dunkle Farbpalette.
COLOR_BG = "#0d0d1a"          # Tiefschwarz Hintergrund
COLOR_GLASS = "#1a1a2e"       # Glasscheibe (dunkel)
COLOR_GLASS_HOVER = "#2a2a3e" # Glasscheibe hover
COLOR_GLASS_LIGHT = "#353550" # Hellere Scheibe (Button-Bg)
COLOR_FG = "#ffffff"          # Primaertext
COLOR_FG2 = "#8888aa"         # Sekundaertext
COLOR_ACCENT = "#ff7eb3"      # Pink-Akzent (Aufnehmen)
COLOR_ACCENT_HOVER = "#ff5588"
COLOR_PURPLE = "#7c3aed"      # Lila (Tmux/Senden)
COLOR_PURPLE_HOVER = "#6d28d9"
COLOR_RED = "#ef4444"         # Rot (Stop)
COLOR_RED_HOVER = "#dc2626"
COLOR_GREEN = "#22c55e"       # Gruen (Verbunden)
COLOR_BORDER = "#2a2a3e"     # Rahmen
RADIUS = 24
RADIUS_SM = 14
FONT = ("Segoe UI",)
FONT_BOLD = ("Segoe UI", "bold")
FONT_MONO = ("Cascadia Code", "Consolas", "monospace")


# ── Main Widget ────────────────────────────────────────
class VoiceWidget(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.server = ServerHelper()
        self.recording = False
        self.audio_data = []
        self.samplerate = 16000
        self.transcribed_text = ""
        self.audio_stream = None

        # ── Window ──
        self.title("VoiceWidget")
        self.configure(fg_color=COLOR_BG)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", WIDGET_OPACITY)
        self.geometry("380x540")

        # Center top-right
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        x = sw - 420
        y = 80
        self.geometry(f"380x540+{x}+{y}")

        # ── Drag ──
        self.bind("<Button-1>", self.start_drag)
        self.bind("<B1-Motion>", self.do_drag)
        self.drag_x = 0
        self.drag_y = 0

        # ── Build ──
        self.build_ui()
        self.refresh_tmux()
        self.after(10000, self.auto_refresh_tmux)

    def start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def do_drag(self, event):
        x = self.winfo_x() + event.x - self.drag_x
        y = self.winfo_y() + event.y - self.drag_y
        self.geometry(f"+{x}+{y}")

    def build_ui(self):
        # Glass-Frame
        self.main = ctk.CTkFrame(
            self, corner_radius=RADIUS,
            fg_color=COLOR_GLASS, border_color=COLOR_BORDER, border_width=1
        )
        self.main.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Titlebar ──
        title_frame = ctk.CTkFrame(self.main, fg_color="transparent", height=40)
        title_frame.pack(fill="x", padx=20, pady=(16, 0))

        ctk.CTkLabel(
            title_frame, text="🎤  VoiceWidget",
            font=(FONT[0], 16, "bold"), text_color=COLOR_FG
        ).pack(side="left")

        ctk.CTkButton(
            title_frame, text="✕", width=32, height=32,
            corner_radius=16, fg_color="transparent",
            hover_color=COLOR_GLASS_HOVER, text_color=COLOR_FG2,
            font=(FONT[0], 14), command=self.quit_app
        ).pack(side="right")

        # ── Status ──
        self.status_lbl = ctk.CTkLabel(
            self.main, text="🔌 Verbinde...",
            font=(FONT[0], 11), text_color=COLOR_FG2
        )
        self.status_lbl.pack(pady=(4, 0))
        self.check_connection()

        # ── Record Button ──
        btn_frame = ctk.CTkFrame(self.main, fg_color="transparent")
        btn_frame.pack(pady=(20, 10))

        self.record_btn = ctk.CTkButton(
            btn_frame, text="⏺  AUFNEHMEN",
            width=200, height=100, corner_radius=50,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#ffffff", font=(FONT[0], 18, "bold"),
            command=self.toggle_recording
        )
        self.record_btn.pack()

        self.rec_lbl = ctk.CTkLabel(
            self.main, text="",
            font=(FONT[0], 11), text_color=COLOR_ACCENT
        )
        self.rec_lbl.pack()

        # ── Tmux Section ──
        tmux_frame = ctk.CTkFrame(self.main, fg_color="transparent")
        tmux_frame.pack(fill="x", padx=20, pady=(10, 4))

        ctk.CTkLabel(
            tmux_frame, text="📟  Ziel-Tmux",
            font=(FONT[0], 11), text_color=COLOR_FG2
        ).pack(anchor="w")

        self.tmux_var = ctk.StringVar(value="(lade...)")
        self.tmux_drop = ctk.CTkOptionMenu(
            tmux_frame, variable=self.tmux_var, values=["(lade...)"],
            corner_radius=RADIUS_SM, fg_color=COLOR_GLASS,
            button_color=COLOR_PURPLE, button_hover_color=COLOR_PURPLE_HOVER,
            dropdown_fg_color="#1a1a2e", dropdown_hover_color=COLOR_PURPLE,
            text_color=COLOR_FG, font=(FONT[0], 13)
        )
        self.tmux_drop.pack(fill="x", pady=(4, 0))

        # Send row
        send_row = ctk.CTkFrame(self.main, fg_color="transparent")
        send_row.pack(fill="x", padx=20, pady=(4, 0))

        self.send_btn = ctk.CTkButton(
            send_row, text="📨  In Tmux einfuegen",
            corner_radius=RADIUS_SM, fg_color=COLOR_PURPLE,
            hover_color=COLOR_PURPLE_HOVER, text_color="#ffffff",
            font=(FONT[0], 12, "bold"), state="disabled",
            command=self.send_to_tmux
        )
        self.send_btn.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            send_row, text="🔄", width=40, height=36,
            corner_radius=RADIUS_SM, fg_color=COLOR_GLASS,
            hover_color=COLOR_GLASS_HOVER, text_color=COLOR_FG2,
            font=(FONT[0], 14), command=self.refresh_tmux
        ).pack(side="right", padx=(6, 0))

        # ── Text Output ──
        text_area = ctk.CTkFrame(self.main, fg_color="transparent")
        text_area.pack(fill="both", expand=True, padx=20, pady=(10, 16))

        self.text_box = ctk.CTkTextbox(
            text_area, corner_radius=RADIUS_SM,
            fg_color=COLOR_GLASS, border_color=COLOR_BORDER, border_width=1,
            text_color=COLOR_FG, font=(FONT_MONO[0], 12),
            wrap="word", height=100
        )
        self.text_box.pack(side="left", fill="both", expand=True)
        self.text_box.insert("1.0", "Transkribierter Text erscheint hier...")
        self.text_box.configure(state="disabled")

        ctk.CTkButton(
            text_area, text="📋", width=40, height=100,
            corner_radius=RADIUS_SM, fg_color=COLOR_GLASS,
            hover_color=COLOR_GLASS_HOVER, text_color=COLOR_FG2,
            font=(FONT[0], 18), command=self.copy_text
        ).pack(side="right", padx=(6, 0))

        # ── Bottom Bar ──
        bottom = ctk.CTkFrame(self.main, fg_color="transparent", height=30)
        bottom.pack(fill="x", padx=20, pady=(0, 12))

        self.dot = ctk.CTkLabel(
            bottom, text="●", font=(FONT[0], 8), text_color=COLOR_GREEN
        )
        self.dot.pack(side="left")

        ctk.CTkLabel(
            bottom, text=" verbunden",
            font=(FONT[0], 10), text_color=COLOR_FG2
        ).pack(side="left", padx=(4, 0))

        ctk.CTkButton(
            bottom, text="⚙️", width=28, height=28,
            corner_radius=14, fg_color="transparent",
            hover_color=COLOR_GLASS_HOVER, text_color=COLOR_FG2,
            font=(FONT[0], 12), command=self.show_settings
        ).pack(side="right")

    # ── Connection ──
    def check_connection(self):
        def _check():
            result = self.server.check_connection()
            if "error" in result:
                self.after(0, lambda: self.status_lbl.configure(text=f"❌ {result['error'][:40]}"))
                self.after(0, lambda: self.dot.configure(text_color=COLOR_RED))
            else:
                self.after(0, lambda: self.status_lbl.configure(text=f"✅ Server: {SERVER_HOST}"))
                self.after(0, lambda: self.dot.configure(text_color=COLOR_GREEN))
        threading.Thread(target=_check, daemon=True).start()

    # ── Recording ──
    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if sd is None:
            self.status_lbl.configure(text="❌ sounddevice nicht installiert")
            return
        self.recording = True
        self.audio_data = []
        self.record_btn.configure(text="⏹  STOP", fg_color=COLOR_RED, hover_color=COLOR_RED_HOVER)
        self.rec_lbl.configure(text="🔴 Aufnahme laeuft...")
        self.text_box.configure(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", "🎤 Hoer zu... sprich ins Mikrofon")
        self.text_box.configure(state="disabled")

        def callback(indata, frames, time_info, status):
            if self.recording:
                self.audio_data.append(indata.copy())

        try:
            self.audio_stream = sd.InputStream(
                samplerate=self.samplerate, channels=1, dtype="float32", callback=callback
            )
            self.audio_stream.start()
        except Exception as e:
            self.recording = False
            self.record_btn.configure(text="⏺  AUFNEHMEN", fg_color=COLOR_ACCENT)
            self.rec_lbl.configure(text=f"❌ {str(e)[:40]}")

    def stop_recording(self):
        self.recording = False
        self.record_btn.configure(text="⏳  TRANSKRIBIERE...", fg_color=COLOR_PURPLE, state="disabled")
        self.rec_lbl.configure(text="⏳ Sende zum Server...")

        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None

        if self.audio_data and len(self.audio_data) > 0:
            threading.Thread(target=self._transcribe_thread, daemon=True).start()
        else:
            self._reset_recording()

    def _transcribe_thread(self):
        try:
            arr = np.concatenate(self.audio_data, axis=0)
            import io
            buf = io.BytesIO()
            sf.write(buf, arr, self.samplerate, format="WAV")
            wav = buf.getvalue()
            result = self.server.transcribe(wav)
            self.after(0, lambda: self._handle_result(result))
        except Exception as e:
            self.after(0, lambda: self.status_lbl.configure(text=f"❌ {str(e)[:50]}"))
            self.after(0, lambda: self._reset_recording())

    def _handle_result(self, result):
        if "error" in result:
            self.rec_lbl.configure(text=f"❌ {result['error'][:40]}")
            self.status_lbl.configure(text="❌ Transkription fehlgeschlagen")
            self._reset_recording()
            return

        text = result.get("text", "")
        lang = result.get("language", "?")
        conf = result.get("language_probability", 0) * 100

        self.transcribed_text = text
        self.text_box.configure(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)
        self.text_box.configure(state="disabled")

        self.rec_lbl.configure(text=f"✅ {lang.upper()} ({conf:.0f}%) · {result.get('duration_s', 0):.1f}s Audio")
        self.send_btn.configure(state="normal" if text.strip() else "disabled")
        self._reset_recording()

    def _reset_recording(self):
        self.record_btn.configure(text="⏺  AUFNEHMEN", fg_color=COLOR_ACCENT, state="normal")
        if not self.rec_lbl.cget("text").startswith("✅"):
            self.rec_lbl.configure(text="")

    # ── Tmux ──
    def refresh_tmux(self):
        def _refresh():
            sessions = self.server.get_tmux_sessions()
            self.after(0, lambda: self._update_tmux(sessions))
        threading.Thread(target=_refresh, daemon=True).start()

    def _update_tmux(self, sessions):
        if sessions:
            self.tmux_drop.configure(values=sessions)
            self.tmux_var.set(sessions[0])

    def auto_refresh_tmux(self):
        self.refresh_tmux()
        self.after(15000, self.auto_refresh_tmux)

    def send_to_tmux(self):
        session = self.tmux_var.get()
        if not session or not self.transcribed_text:
            return
        self.send_btn.configure(state="disabled", text="📨 Sende...")

        def _send():
            ok = self.server.send_to_tmux(session, self.transcribed_text)
            self.after(0, lambda: self._send_result(ok))
        threading.Thread(target=_send, daemon=True).start()

    def _send_result(self, ok):
        if ok:
            self.send_btn.configure(text="✅  Gesendet!", state="normal")
            self.after(2000, lambda: self.send_btn.configure(text="📨  In Tmux einfuegen"))
        else:
            self.send_btn.configure(text="❌  Fehlgeschlagen", fg_color=COLOR_RED, state="normal")
            self.after(2000, lambda: self.send_btn.configure(
                text="📨  In Tmux einfuegen", fg_color=COLOR_PURPLE))

    # ── Clipboard ──
    def copy_text(self):
        if self.transcribed_text:
            self.clipboard_clear()
            self.clipboard_append(self.transcribed_text)
            self.status_lbl.configure(text="📋 In Zwischenablage kopiert!")
            self.after(2000, lambda: self.status_lbl.configure(text=f"✅ Server: {SERVER_HOST}"))

    # ── Settings ──
    def show_settings(self):
        d = ctk.CTkToplevel(self)
        d.title("Settings")
        d.geometry(f"300x250+{self.winfo_x()+40}+{self.winfo_y()+80}")
        d.configure(fg_color="#1a1a2e")
        d.attributes("-topmost", True)
        d.transient(self)
        d.grab_set()

        ctk.CTkLabel(
            d, text="⚙️  Einstellungen",
            font=(FONT[0], 16, "bold"), text_color=COLOR_FG
        ).pack(pady=(16, 12))

        # Auto-start
        autostart = CONFIG.getboolean("Widget", "autostart")
        self.as_var = ctk.BooleanVar(value=autostart)

        def toggle_as():
            startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            shortcut = startup / "VoiceWidget.bat"
            script = Path(__file__).resolve()

            if self.as_var.get():
                with open(shortcut, "w") as f:
                    venv_python = script.parent / "venv" / "Scripts" / "pythonw.exe"
                    f.write(f'@echo off\nstart "" "{venv_python}" "{script}"\n')
                CONFIG.set("Widget", "autostart", "true")
            else:
                if shortcut.exists():
                    shortcut.unlink()
                CONFIG.set("Widget", "autostart", "false")

            with open(CONFIG_FILE, "w") as f:
                CONFIG.write(f)

        ctk.CTkSwitch(
            d, text="Auto-Start (mit Windows)",
            variable=self.as_var, command=toggle_as,
            font=(FONT[0], 12), text_color=COLOR_FG,
            progress_color=COLOR_ACCENT, button_color=COLOR_PURPLE
        ).pack(pady=8)

        ctk.CTkLabel(
            d, text=f"Opacity: {WIDGET_OPACITY:.0%}",
            font=(FONT[0], 12), text_color=COLOR_FG2
        ).pack(pady=(12, 4))

        def set_opacity(val):
            o = float(val) / 100
            self.attributes("-alpha", o)
            CONFIG.set("Widget", "opacity", str(o))
            with open(CONFIG_FILE, "w") as f:
                CONFIG.write(f)

        ctk.CTkSlider(
            d, from_=30, to=100, number_of_steps=70,
            command=set_opacity, progress_color=COLOR_ACCENT,
            button_color=COLOR_PURPLE
        ).pack(fill="x", padx=20)
        ctk.CTkSlider(d).pack()

        ctk.CTkButton(
            d, text="Schliessen", command=d.destroy,
            corner_radius=RADIUS_SM, fg_color=COLOR_PURPLE, text_color="#ffffff"
        ).pack(pady=(16, 8))

    def quit_app(self):
        self.quit()
        self.destroy()


# ── Main ──
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = VoiceWidget()

    # Windows 11 Acrylic/Mica
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(app.winfo_id())
            DWMWA_SYSTEMBACKDROP_TYPE = 38
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(ctypes.c_int(2)), 4
            )
        except:
            pass

    app.mainloop()
