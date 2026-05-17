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
    # Fill defaults for missing keys
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
    print(f"❌ Fehlende Abhängigkeit: {e}")
    print("Bitte installieren: pip install customtkinter Pillow")
    sys.exit(1)

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
except ImportError:
    print("⚠️  sounddevice nicht installiert. Audio-Aufnahme deaktiviert.")
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
        """Prüft ob Server erreichbar ist."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.whisper_url}/health")
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)}

    def transcribe(self, wav_data):
        """Sendet Audio an Whisper API und gibt Text zurück."""
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
            return sessions if sessions else ["(keine Sessions)"]
        except Exception as e:
            return [f"(Fehler: {str(e)[:30]})"]

    def send_to_tmux(self, session_name, text):
        """Fügt Text in eine Tmux Session ein."""
        try:
            # Escape the text for shell
            escaped_text = text.replace("'", "'\\''")
            cmd = [
                "ssh", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=5",
                f"{self.user}@{self.host}",
                "-p", str(self.port),
                f"tmux send-keys -t '{session_name}' '{escaped_text}' Enter"
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except Exception as e:
            return False


# ── Liquid Glass Theme ─────────────────────────────────
THEME = {
    "bg_main": "#1a1a2e",
    "bg_glass": "rgba(255, 255, 255, 0.08)",
    "bg_glass_hover": "rgba(255, 255, 255, 0.15)",
    "fg_primary": "#ffffff",
    "fg_secondary": "rgba(255, 255, 255, 0.6)",
    "accent_primary": "#ff7eb3",
    "accent_secondary": "#7c3aed",
    "border": "rgba(255, 255, 255, 0.12)",
    "border_focus": "rgba(255, 255, 255, 0.25)",
    "radius": 24,
    "radius_small": 14,
    "font": ("SF Pro Display", "Segoe UI", "Helvetica Neue", "sans-serif"),
    "font_mono": ("SF Mono", "Cascadia Code", "Consolas", "monospace"),
}


# ── Main Widget ────────────────────────────────────────
class VoiceWidget(ctk.CTk):
    """Liquid Glass Voice Transcription Widget."""

    def __init__(self):
        super().__init__()

        self.server = ServerHelper()
        self.recording = False
        self.audio_data = []
        self.samplerate = 16000
        self.transcribed_text = ""
        self.audio_stream = None

        # ── Window Setup ──
        self.title("VoiceWidget")
        self.configure(fg_color="#1a1a2e")
        self.overrideredirect(True)  # Frameless
        self.attributes("-topmost", True)
        self.attributes("-alpha", WIDGET_OPACITY)
        self.geometry("380x520+50+50")

        # Windows-specific: transparent background hack
        if sys.platform == "win32":
            try:
                self.wm_attributes("-transparentcolor", "#1a1a2e")
            except:
                pass

        # ── Center window on screen ──
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = sw - 420
        y = 80
        self.geometry(f"380x520+{x}+{y}")

        # ── Drag functionality ──
        self.bind("<Button-1>", self.start_drag)
        self.bind("<B1-Motion>", self.do_drag)
        self.drag_x = 0
        self.drag_y = 0

        # ── Build UI ──
        self.build_ui()

        # ── Auto-refresh tmux ──
        self.refresh_tmux()
        self.after(10000, self.auto_refresh_tmux)

    # ── Window dragging ──
    def start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def do_drag(self, event):
        x = self.winfo_x() + event.x - self.drag_x
        y = self.winfo_y() + event.y - self.drag_y
        self.geometry(f"+{x}+{y}")

    # ── Build UI ──
    def build_ui(self):
        # Main container with glass effect
        self.main_frame = ctk.CTkFrame(
            self,
            corner_radius=THEME["radius"],
            fg_color=THEME["bg_glass"],
            border_color=THEME["border"],
            border_width=1,
        )
        self.main_frame.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Title Bar ──
        title_frame = ctk.CTkFrame(
            self.main_frame, fg_color="transparent", height=40
        )
        title_frame.pack(fill="x", padx=20, pady=(16, 0))

        ctk.CTkLabel(
            title_frame,
            text="🎤  VoiceWidget",
            font=(THEME["font"][0], 16, "bold"),
            text_color=THEME["fg_primary"],
        ).pack(side="left")

        # Close button
        close_btn = ctk.CTkButton(
            title_frame,
            text="✕",
            width=32, height=32,
            corner_radius=16,
            fg_color="transparent",
            hover_color=THEME["bg_glass_hover"],
            text_color=THEME["fg_secondary"],
            font=(THEME["font"][0], 14),
            command=self.quit_app,
        )
        close_btn.pack(side="right")

        # ── Connection Status ──
        self.status_label = ctk.CTkLabel(
            self.main_frame,
            text="🔌 Verbinde...",
            font=(THEME["font"][0], 11),
            text_color=THEME["fg_secondary"],
        )
        self.status_label.pack(pady=(4, 0))
        self.check_connection()

        # ── Record Button ──
        btn_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        btn_frame.pack(pady=(20, 10))

        self.record_btn = ctk.CTkButton(
            btn_frame,
            text="⏺  AUFNEHMEN",
            width=200, height=100,
            corner_radius=50,
            fg_color=THEME["accent_primary"],
            hover_color="#ff5588",
            text_color="#ffffff",
            font=(THEME["font"][0], 18, "bold"),
            command=self.toggle_recording,
        )
        self.record_btn.pack()

        # ── Recording indicator ──
        self.rec_indicator = ctk.CTkLabel(
            self.main_frame,
            text="",
            font=(THEME["font"][0], 11),
            text_color=THEME["accent_primary"],
        )
        self.rec_indicator.pack()

        # ── Tmux Session Selector ──
        tmux_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        tmux_frame.pack(fill="x", padx=20, pady=(10, 4))

        ctk.CTkLabel(
            tmux_frame,
            text="📟  Ziel-Tmux",
            font=(THEME["font"][0], 11),
            text_color=THEME["fg_secondary"],
        ).pack(anchor="w")

        self.tmux_var = ctk.StringVar(value="(lade...)")
        self.tmux_dropdown = ctk.CTkOptionMenu(
            tmux_frame,
            variable=self.tmux_var,
            values=["(lade...)"],
            corner_radius=THEME["radius_small"],
            fg_color=THEME["bg_glass"],
            button_color=THEME["accent_secondary"],
            button_hover_color="#6d28d9",
            dropdown_fg_color="#2a2a4e",
            dropdown_hover_color=THEME["accent_secondary"],
            text_color=THEME["fg_primary"],
            font=(THEME["font"][0], 13),
        )
        self.tmux_dropdown.pack(fill="x", pady=(4, 0))

        # Send button next to dropdown
        send_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        send_frame.pack(fill="x", padx=20, pady=(4, 0))

        self.send_btn = ctk.CTkButton(
            send_frame,
            text="📨  In Tmux einfügen",
            corner_radius=THEME["radius_small"],
            fg_color=THEME["accent_secondary"],
            hover_color="#6d28d9",
            text_color="#ffffff",
            font=(THEME["font"][0], 12, "bold"),
            state="disabled",
            command=self.send_to_tmux,
        )
        self.send_btn.pack(side="left", fill="x", expand=True)

        self.refresh_btn = ctk.CTkButton(
            send_frame,
            text="🔄",
            width=40, height=36,
            corner_radius=THEME["radius_small"],
            fg_color=THEME["bg_glass"],
            hover_color=THEME["bg_glass_hover"],
            text_color=THEME["fg_secondary"],
            font=(THEME["font"][0], 14),
            command=self.refresh_tmux,
        )
        self.refresh_btn.pack(side="right", padx=(6, 0))

        # ── Text Output ──
        text_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        text_frame.pack(fill="both", expand=True, padx=20, pady=(10, 16))

        self.text_box = ctk.CTkTextbox(
            text_frame,
            corner_radius=THEME["radius_small"],
            fg_color=THEME["bg_glass"],
            border_color=THEME["border"],
            border_width=1,
            text_color=THEME["fg_primary"],
            font=(THEME["font_mono"][0], 12),
            wrap="word",
            height=100,
        )
        self.text_box.pack(side="left", fill="both", expand=True)
        self.text_box.insert("1.0", "Transkribierter Text erscheint hier...")
        self.text_box.configure(state="disabled")

        # Copy button
        copy_btn = ctk.CTkButton(
            text_frame,
            text="📋",
            width=40, height=100,
            corner_radius=THEME["radius_small"],
            fg_color=THEME["bg_glass"],
            hover_color=THEME["bg_glass_hover"],
            text_color=THEME["fg_secondary"],
            font=(THEME["font"][0], 18),
            command=self.copy_text,
        )
        copy_btn.pack(side="right", padx=(6, 0))

        # ── Bottom bar ──
        bottom_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent", height=30)
        bottom_frame.pack(fill="x", padx=20, pady=(0, 12))

        # Animated dot
        self.dot = ctk.CTkLabel(
            bottom_frame,
            text="●",
            font=(THEME["font"][0], 8),
            text_color="#22c55e",
        )
        self.dot.pack(side="left")

        ctk.CTkLabel(
            bottom_frame,
            text=" verbunden",
            font=(THEME["font"][0], 10),
            text_color=THEME["fg_secondary"],
        ).pack(side="left", padx=(4, 0))

        # Settings gear
        settings_btn = ctk.CTkButton(
            bottom_frame,
            text="⚙️",
            width=28, height=28,
            corner_radius=14,
            fg_color="transparent",
            hover_color=THEME["bg_glass_hover"],
            text_color=THEME["fg_secondary"],
            font=(THEME["font"][0], 12),
            command=self.show_settings,
        )
        settings_btn.pack(side="right")

    # ── Connection ──
    def check_connection(self):
        def _check():
            result = self.server.check_connection()
            if "error" in result:
                self.after(0, lambda: self.status_label.configure(
                    text=f"❌ {result['error'][:40]}"))
                self.after(0, lambda: self.dot.configure(text_color="#ef4444"))
            else:
                self.after(0, lambda: self.status_label.configure(
                    text=f"✅ Server: {SERVER_HOST}"))
                self.after(0, lambda: self.dot.configure(text_color="#22c55e"))

        threading.Thread(target=_check, daemon=True).start()

    # ── Recording ──
    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if sd is None:
            self.status_label.configure(text="❌ sounddevice nicht installiert")
            return

        self.recording = True
        self.audio_data = []
        self.record_btn.configure(
            text="⏹  STOP",
            fg_color="#ef4444",
            hover_color="#dc2626",
        )
        self.rec_indicator.configure(text="🔴 Aufnahme läuft...")
        self.text_box.configure(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", "🎤 Hör zu... sprich ins Mikrofon")
        self.text_box.configure(state="disabled")

        def callback(indata, frames, time_info, status):
            if self.recording:
                self.audio_data.append(indata.copy())

        try:
            self.audio_stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=1,
                dtype="float32",
                callback=callback,
            )
            self.audio_stream.start()
        except Exception as e:
            self.recording = False
            self.record_btn.configure(text="⏺  AUFNEHMEN", fg_color=THEME["accent_primary"])
            self.rec_indicator.configure(text=f"❌ {str(e)[:40]}")

    def stop_recording(self):
        self.recording = False
        self.record_btn.configure(
            text="⏳  TRANSKRIBIERE...",
            fg_color=THEME["accent_secondary"],
            state="disabled",
        )
        self.rec_indicator.configure(text="⏳ Sende zum Server...")

        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None

        # Convert audio to WAV bytes
        if self.audio_data and len(self.audio_data) > 0:
            threading.Thread(target=self._transcribe_thread, daemon=True).start()
        else:
            self._reset_recording()

    def _transcribe_thread(self):
        try:
            audio_array = np.concatenate(self.audio_data, axis=0)

            import io
            buf = io.BytesIO()
            sf.write(buf, audio_array, self.samplerate, format="WAV")
            wav_bytes = buf.getvalue()

            result = self.server.transcribe(wav_bytes)

            self.after(0, lambda: self._handle_result(result))
        except Exception as e:
            self.after(0, lambda: self.status_label.configure(text=f"❌ {str(e)[:50]}"))
            self.after(0, lambda: self._reset_recording())

    def _handle_result(self, result):
        if "error" in result:
            self.rec_indicator.configure(text=f"❌ {result['error'][:40]}")
            self.status_label.configure(text="❌ Transkription fehlgeschlagen")
            self._reset_recording()
            return

        text = result.get("text", "")
        language = result.get("language", "?")
        confidence = result.get("language_probability", 0) * 100

        self.transcribed_text = text
        self.text_box.configure(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)
        self.text_box.configure(state="disabled")

        self.rec_indicator.configure(
            text=f"✅ {language.upper()} ({confidence:.0f}%) · {result.get('duration_s', 0):.1f}s Audio"
        )
        self.send_btn.configure(state="normal" if text.strip() else "disabled")
        self._reset_recording()

    def _reset_recording(self):
        self.record_btn.configure(
            text="⏺  AUFNEHMEN",
            fg_color=THEME["accent_primary"],
            state="normal",
        )
        if not self.rec_indicator.cget("text").startswith("✅"):
            self.rec_indicator.configure(text="")

    # ── Tmux ──
    def refresh_tmux(self):
        def _refresh():
            sessions = self.server.get_tmux_sessions()
            self.after(0, lambda: self._update_tmux(sessions))

        threading.Thread(target=_refresh, daemon=True).start()

    def _update_tmux(self, sessions):
        if sessions and sessions[0] != self.tmux_var.get():
            self.tmux_dropdown.configure(values=sessions)
            if sessions[0] and not sessions[0].startswith("("):
                self.tmux_var.set(sessions[0])

    def auto_refresh_tmux(self):
        self.refresh_tmux()
        self.after(15000, self.auto_refresh_tmux)

    def send_to_tmux(self):
        session = self.tmux_var.get()
        if not session or session.startswith("(") or not self.transcribed_text:
            return

        self.send_btn.configure(state="disabled", text="📨 Sende...")

        def _send():
            success = self.server.send_to_tmux(session, self.transcribed_text)
            self.after(0, lambda: self._send_result(success))

        threading.Thread(target=_send, daemon=True).start()

    def _send_result(self, success):
        if success:
            self.send_btn.configure(text="✅  Gesendet!", state="normal")
            self.after(2000, lambda: self.send_btn.configure(text="📨  In Tmux einfügen"))
        else:
            self.send_btn.configure(
                text="❌  Fehlgeschlagen", fg_color="#ef4444", state="normal"
            )
            self.after(2000, lambda: self.send_btn.configure(
                text="📨  In Tmux einfügen", fg_color=THEME["accent_secondary"]
            ))

    # ── Clipboard ──
    def copy_text(self):
        if self.transcribed_text:
            self.clipboard_clear()
            self.clipboard_append(self.transcribed_text)
            self.status_label.configure(text="📋 In Zwischenablage kopiert!")
            self.after(2000, lambda: self.status_label.configure(
                text=f"✅ Server: {SERVER_HOST}"
            ))

    # ── Settings ──
    def show_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("300x250+{}+{}".format(
            self.winfo_x() + 40, self.winfo_y() + 80
        ))
        dialog.configure(fg_color="#2a2a4e")
        dialog.attributes("-topmost", True)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="⚙️  Einstellungen",
            font=(THEME["font"][0], 16, "bold"),
            text_color=THEME["fg_primary"],
        ).pack(pady=(16, 12))

        # Auto-start toggle
        autostart = CONFIG.getboolean("Widget", "autostart")
        self.autostart_var = ctk.BooleanVar(value=autostart)

        def toggle_autostart():
            startup_dir = Path(os.environ.get(
                "APPDATA", ""
            )) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            shortcut = startup_dir / "VoiceWidget.lnk"

            if self.autostart_var.get():
                # Create shortcut
                script_path = Path(__file__).resolve()
                try:
                    import win32com.client
                    shell = win32com.client.Dispatch("WScript.Shell")
                    shortcut_file = shell.CreateShortCut(str(shortcut))
                    shortcut_file.TargetPath = sys.executable
                    shortcut_file.Arguments = f'"{script_path}"'
                    shortcut_file.WorkingDirectory = str(script_path.parent)
                    shortcut_file.Save()
                except:
                    # Fallback: batch file
                    bat = startup_dir / "VoiceWidget.bat"
                    with open(bat, "w") as f:
                        f.write(f'@echo off\nstart "" "{sys.executable}" "{script_path}"\n')
                    shortcut = bat
                CONFIG.set("Widget", "autostart", "true")
            else:
                if shortcut.exists():
                    shortcut.unlink()
                bat = startup_dir / "VoiceWidget.bat"
                if bat.exists():
                    bat.unlink()
                CONFIG.set("Widget", "autostart", "false")

            with open(CONFIG_FILE, "w") as f:
                CONFIG.write(f)

        ctk.CTkSwitch(
            dialog,
            text="Auto-Start (mit Windows)",
            variable=self.autostart_var,
            command=toggle_autostart,
            font=(THEME["font"][0], 12),
            text_color=THEME["fg_primary"],
            progress_color=THEME["accent_primary"],
            button_color=THEME["accent_secondary"],
        ).pack(pady=8)

        # Opacity slider
        ctk.CTkLabel(
            dialog,
            text=f"Opacity: {WIDGET_OPACITY:.0%}",
            font=(THEME["font"][0], 12),
            text_color=THEME["fg_secondary"],
        ).pack(pady=(12, 4))

        def set_opacity(val):
            opacity = float(val) / 100
            self.attributes("-alpha", opacity)
            CONFIG.set("Widget", "opacity", str(opacity))
            with open(CONFIG_FILE, "w") as f:
                CONFIG.write(f)

        opacity_slider = ctk.CTkSlider(
            dialog,
            from_=30, to=100,
            number_of_steps=70,
            command=set_opacity,
            progress_color=THEME["accent_primary"],
            button_color=THEME["accent_secondary"],
        )
        opacity_slider.set(int(WIDGET_OPACITY * 100))
        opacity_slider.pack(fill="x", padx=20)

        # Close button
        ctk.CTkButton(
            dialog,
            text="Schließen",
            command=dialog.destroy,
            corner_radius=THEME["radius_small"],
            fg_color=THEME["accent_secondary"],
            text_color="#ffffff",
        ).pack(pady=(16, 8))

    # ── Quit ──
    def quit_app(self):
        self.quit()
        self.destroy()


# ── Main ──────────────────────────────────────────────
if __name__ == "__main__":
    # Set appearance
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = VoiceWidget()

    # Apply blur behind window (Windows 11)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            # Windows 11 acrylic/blur effect
            hwnd = ctypes.windll.user32.GetParent(app.winfo_id())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_MICA_EFFECT = 1029
            DWMWA_SYSTEMBACKDROP_TYPE = 38
            # Try MICA first (Windows 11)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(ctypes.c_int(2)), 4
            )
        except:
            pass

    app.mainloop()
