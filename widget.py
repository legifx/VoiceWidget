#!/usr/bin/env python3
"""
VoiceWidget — Minimal Edition
==============================
Winziges Floating Widget: Ein Klick aufnehmen, transkribieren, in Zwischenablage.

Usage:
    python widget.py
"""
import sys, os, json, configparser, threading, subprocess, io
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.ini"
DEFAULT = {
    "Server": {"host": "192.168.1.182", "user": "server", "port": "22", "whisper_port": "8766"},
    "Widget": {"opacity": "0.9"},
}
cfg = configparser.ConfigParser()
if CONFIG_FILE.exists():
    cfg.read(CONFIG_FILE)
for sec, keys in DEFAULT.items():
    for k, v in keys.items():
        if not cfg.has_option(sec, k):
            cfg.set(sec, k, v)
with open(CONFIG_FILE, "w") as f:
    cfg.write(f)

HOST = cfg.get("Server", "host")
USER = cfg.get("Server", "user")
WPORT = cfg.get("Server", "whisper_port")
OPACITY = float(cfg.get("Widget", "opacity"))
WHISPER_URL = f"http://{HOST}:{WPORT}"

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

try:
    import sounddevice as sd, numpy as np, soundfile as sf
except ImportError:
    sd = np = sf = None


# ── Server ──
class Server:
    def check(self):
        try:
            import urllib.request
            with urllib.request.urlopen(f"{WHISPER_URL}/health", timeout=5) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)[:30]}

    def transcribe(self, wav):
        import urllib.request
        b = f"----Boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"v.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode() + wav + b"\r\n------Boundary--\r\n".encode()
        req = urllib.request.Request(f"{WHISPER_URL}/transcribe", data=b,
            headers={"Content-Type": "multipart/form-data; boundary=----Boundary"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)[:30]}

    def tmux_sessions(self):
        try:
            r = subprocess.run(["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=accept-new",
                f"{USER}@{HOST}", "tmux list-sessions -F '#{session_name}' 2>/dev/null"],
                capture_output=True, text=True, timeout=8)
            return [s.strip() for s in r.stdout.split("\n") if s.strip()]
        except:
            return []

    def send_tmux(self, session, text):
        try:
            safe = text.replace("'", "'\"'\"'").replace("\n", "\\n")
            subprocess.run(["ssh", "-o", "ConnectTimeout=3", f"{USER}@{HOST}",
                f"tmux send-keys -t '{session}' '{safe}' Enter"],
                capture_output=True, timeout=8)
            return True
        except:
            return False


# ── Widget ──
class MiniWidget(ctk.CTk):
    W = 260  # width
    H = 52   # height when idle

    def __init__(self):
        super().__init__()
        self.srv = Server()
        self.recording = False
        self.audio_data = []
        self.audio_stream = None
        self.text = ""
        self.samplerate = 16000
        self.expanded = False

        # Window
        self.title("")
        self.configure(fg_color="#0d0d1a")
        self.overrideredirect(True)
        self.attributes("-topmost", True, "-alpha", OPACITY)
        sw = self.winfo_screenwidth()
        self.geometry(f"{self.W}x{self.H}+{sw-self.W-24}+80")

        # Drag
        self.bind("<Button-1>", self._drag_start)
        self.bind("<B1-Motion>", self._drag)
        self._dx = self._dy = 0

        self._build_idle()
        self._check()
        self.after(5000, self._health_poll)

    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        self.geometry(f"+{self.winfo_x()+e.x-self._dx}+{self.winfo_y()+e.y-self._dy}")

    # ── Build: Idle ──
    def _build_idle(self):
        self._clear()
        self.geometry(f"{self.W}x{self.H}")
        self._frm = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=26,
            border_color="#2a2a3e", border_width=1)
        self._frm.pack(fill="both", expand=True, padx=2, pady=2)

        # Row: status dot + record btn + tmux icon
        row = ctk.CTkFrame(self._frm, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=12, pady=0)

        self.dot = ctk.CTkLabel(row, text="●", font=("Segoe UI", 9), text_color="#ef4444")
        self.dot.pack(side="left")

        self.rec_btn = ctk.CTkButton(row, text="🎤", width=38, height=38,
            corner_radius=19, fg_color="#7c3aed", hover_color="#6d28d9",
            text_color="#fff", font=("Segoe UI", 16), command=self._click)
        self.rec_btn.pack(side="left", padx=(8, 0))

        self.status = ctk.CTkLabel(row, text="", font=("Segoe UI", 10),
            text_color="#6666aa", width=80)
        self.status.pack(side="left", padx=(6, 0))

        # Tiny gear for settings
        ctk.CTkButton(row, text="⋯", width=24, height=24, corner_radius=12,
            fg_color="transparent", hover_color="#2a2a3e", text_color="#555",
            font=("Segoe UI", 14), command=self._settings
        ).pack(side="right")

    # ── Build: Recording ──
    def _build_rec(self):
        self._clear()
        self.geometry(f"{self.W}x{self.H+20}")
        f = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=26,
            border_color="#ff7eb3", border_width=1)
        f.pack(fill="both", expand=True, padx=2, pady=2)

        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=12, pady=0)

        self.dot = ctk.CTkLabel(row, text="●", font=("Segoe UI", 9), text_color="#ef4444")
        self.dot.pack(side="left")

        self.rec_btn = ctk.CTkButton(row, text="⏹", width=38, height=38,
            corner_radius=19, fg_color="#ef4444", hover_color="#dc2626",
            text_color="#fff", font=("Segoe UI", 16), command=self._click)
        self.rec_btn.pack(side="left", padx=(8, 0))

        self.rec_time = ctk.CTkLabel(row, text="0s", font=("Segoe UI", 12),
            text_color="#ff7eb3")
        self.rec_time.pack(side="left", padx=(6, 0))

        # VU meter
        self.vu = ctk.CTkLabel(row, text="▁", font=("Segoe UI", 14),
            text_color="#7c3aed")
        self.vu.pack(side="left", padx=(4, 0))

    # ── Build: Result ──
    def _build_result(self):
        self._clear()
        self.geometry(f"{self.W}x{self.H+60}")
        f = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=20,
            border_color="#22c55e", border_width=1)
        f.pack(fill="both", expand=True, padx=2, pady=2)

        # Top bar
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 0))

        ctk.CTkLabel(top, text="✅", font=("Segoe UI", 11)).pack(side="left")
        self.status = ctk.CTkLabel(top, text="", font=("Segoe UI", 9),
            text_color="#22c55e")
        self.status.pack(side="left", padx=(4, 0))

        # Text preview (1 line)
        self.preview = ctk.CTkLabel(f, text=self.text[:50]+("…" if len(self.text)>50 else ""),
            font=("Segoe UI", 10), text_color="#ccc", anchor="w", justify="left")
        self.preview.pack(fill="x", padx=10, pady=(4, 0))

        # Action row
        act = ctk.CTkFrame(f, fg_color="transparent")
        act.pack(fill="x", padx=8, pady=(4, 6))

        ctk.CTkButton(act, text="📋", width=32, height=28, corner_radius=14,
            fg_color="#2a2a3e", hover_color="#3a3a4e", text_color="#ccc",
            font=("Segoe UI", 12), command=self._copy
        ).pack(side="left", padx=(0, 4))

        self.tmux_btn = ctk.CTkButton(act, text="📟", width=32, height=28,
            corner_radius=14, fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="#ccc", font=("Segoe UI", 12), state="disabled",
            command=self._send_tmux)
        self.tmux_btn.pack(side="left")

        # Tmux dropdown (tiny)
        self.tmux_var = ctk.StringVar(value="?")
        self.tmux_drop = ctk.CTkOptionMenu(act, variable=self.tmux_var,
            values=["(keine)"], width=80, height=28, corner_radius=14,
            fg_color="#2a2a3e", button_color="#7c3aed", button_hover_color="#6d28d9",
            dropdown_fg_color="#1a1a2e", dropdown_hover_color="#7c3aed",
            text_color="#ccc", font=("Segoe UI", 9))
        self.tmux_drop.pack(side="left", padx=(4, 0))

        # Load tmux sessions in bg
        threading.Thread(target=self._load_tmux, daemon=True).start()

        ctk.CTkButton(act, text="✕", width=24, height=28, corner_radius=14,
            fg_color="transparent", hover_color="#2a2a3e", text_color="#555",
            font=("Segoe UI", 12), command=self._reset
        ).pack(side="right")

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    # ── Actions ──
    def _click(self):
        if self.recording:
            self._stop()
        else:
            self._record()

    def _record(self):
        if sd is None:
            self.status.configure(text="no snd")
            return
        self.recording = True
        self.audio_data = []
        self._build_rec()
        self._t0 = time()

        def cb(indata, frames, t, status):
            if self.recording:
                self.audio_data.append(indata.copy())
                # Update VU + time on UI thread
                level = int(np.abs(indata).mean() * 20)
                vu = "▁▂▃▄▅▆▇█"[min(level, 7)]
                elapsed = int(time() - self._t0)
                self.after(0, lambda: self.vu.configure(text=vu))
                self.after(0, lambda: self.rec_time.configure(text=f"{elapsed}s"))

        try:
            self.audio_stream = sd.InputStream(
                samplerate=self.samplerate, channels=1, dtype="float32", callback=cb)
            self.audio_stream.start()
        except Exception as e:
            self.recording = False
            self._build_idle()
            self.dot.configure(text_color="#ef4444")
            self.status.configure(text=str(e)[:15])

    def _stop(self):
        self.recording = False
        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None

        if not self.audio_data:
            self._reset()
            return

        self._clear()
        self.geometry(f"{self.W}x{self.H}")
        f = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=26)
        f.pack(fill="both", expand=True, padx=2, pady=2)
        ctk.CTkLabel(f, text="⏳", font=("Segoe UI", 16)).pack(expand=True)

        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        try:
            arr = np.concatenate(self.audio_data, axis=0)
            buf = io.BytesIO()
            sf.write(buf, arr, self.samplerate, format="WAV")
            result = self.srv.transcribe(buf.getvalue())
            self.after(0, lambda: self._on_result(result))
        except Exception as e:
            self.after(0, lambda: self._on_error(str(e)[:30]))

    def _on_result(self, r):
        if "error" in r:
            self._on_error(r["error"])
            return
        self.text = r.get("text", "")
        if not self.text.strip():
            self._reset()
            return
        lang = r.get("language", "?")
        conf = r.get("language_probability", 0) * 100
        self._build_result()
        self.status.configure(text=f"{lang.upper()} {conf:.0f}% · {r.get('duration_s',0):.1f}s")
        self.preview.configure(text=self.text[:80]+("…" if len(self.text)>80 else ""))
        # Auto-copy to clipboard
        self.clipboard_clear()
        self.clipboard_append(self.text)

    def _on_error(self, msg):
        self._build_idle()
        self.dot.configure(text_color="#ef4444")
        self.status.configure(text=msg[:15])

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.text)
        self.status.configure(text="📋 kopiert!")
        self.after(1500, lambda: self.status.configure(text=""))

    def _load_tmux(self):
        sessions = self.srv.tmux_sessions()
        if sessions:
            self.after(0, lambda: self.tmux_drop.configure(values=sessions))
            self.after(0, lambda: self.tmux_var.set(sessions[0]))
            self.after(0, lambda: self.tmux_btn.configure(state="normal"))

    def _send_tmux(self):
        s = self.tmux_var.get()
        if s and self.text and not s.startswith("("):
            self.srv.send_tmux(s, self.text)
            self.status.configure(text="📨 gesendet!")
            self.after(1500, self._reset)

    def _reset(self):
        self.text = ""
        self._build_idle()
        self._check()

    # ── Health ──
    def _check(self):
        def c():
            r = self.srv.check()
            ok = "error" not in r
            self.after(0, lambda: self.dot.configure(
                text_color="#22c55e" if ok else "#ef4444"))
            self.after(0, lambda: self.status.configure(
                text="online" if ok else "offline"))
        threading.Thread(target=c, daemon=True).start()

    def _health_poll(self):
        self._check()
        self.after(15000, self._health_poll)

    # ── Settings ──
    def _settings(self):
        d = ctk.CTkToplevel(self)
        d.title("")
        d.geometry(f"200x100+{self.winfo_x()+30}+{self.winfo_y()+60}")
        d.configure(fg_color="#0d0d1a", borderwidth=1, relief="solid")
        d.overrideredirect(True)
        d.attributes("-topmost", True)
        d.transient(self)
        d.grab_set()

        ctk.CTkLabel(d, text="Opacity", font=("Segoe UI", 10),
            text_color="#666").pack(pady=(8, 2))

        def set_op(v):
            o = float(v) / 100
            self.attributes("-alpha", o)
            cfg.set("Widget", "opacity", str(o))
            with open(CONFIG_FILE, "w") as f:
                cfg.write(f)

        s = ctk.CTkSlider(d, from_=30, to=100, command=set_op,
            progress_color="#7c3aed", button_color="#7c3aed")
        s.set(int(OPACITY * 100))
        s.pack(fill="x", padx=16, pady=4)

        ctk.CTkButton(d, text="Schliessen", command=d.destroy,
            fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="#aaa", font=("Segoe UI", 9), height=24,
            corner_radius=12).pack(pady=(4, 6))

    def quit(self):
        self.quit_app()

    def quit_app(self):
        self.quit()
        self.destroy()


if __name__ == "__main__":
    from time import time
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = MiniWidget()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app.quit_app()
