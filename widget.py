#!/usr/bin/env python3
"""
VoiceWidget — Orb Edition
==========================
Rundes Floating-Orb: Ein Klick aufnehmen, transkribieren, in Zwischenablage.

Usage:
    python widget.py
"""
import sys, os, json, configparser, threading, subprocess, io
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.ini"
DEFAULT = {
    "Server": {"host": "192.168.1.182", "user": "server", "port": "22", "whisper_port": "8766"},
    "Widget": {"opacity": "0.92"},
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
except:
    ctk = None

try:
    import sounddevice as sd, numpy as np, soundfile as sf
except:
    sd = np = sf = None

# ── Neon Palette ──
BG = "#08080f"
GLASS = "#141428"
GLASS2 = "#1c1c3a"
PURPLE = "#a855f7"
PURPLE_DARK = "#7c3aed"
PINK = "#ec4899"
PINK_BRIGHT = "#ff7eb3"
RED = "#ef4444"
RED_DARK = "#dc2626"
GREEN = "#22c55e"
TEAL = "#06b6d4"
FG = "#f0f0ff"
FG2 = "#8888bb"
BORDER = "#2a2a4e"
RAD = 999  # fully round


class Server:
    def check(self):
        try:
            import urllib.request
            with urllib.request.urlopen(f"{WHISPER_URL}/health", timeout=4) as r:
                return json.loads(r.read())
        except:
            return {"error": "offline"}

    def transcribe(self, wav):
        import urllib.request
        b = b"------B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"v.wav\"\r\nContent-Type: audio/wav\r\n\r\n" + wav + b"\r\n------B--\r\n"
        req = urllib.request.Request(f"{WHISPER_URL}/transcribe", data=b,
            headers={"Content-Type": "multipart/form-data; boundary=----B"})
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


class OrbWidget(ctk.CTk):
    S = 56  # orb size

    def __init__(self):
        super().__init__()
        self.srv = Server()
        self.recording = False
        self.audio_data = []
        self.audio_stream = None
        self.text = ""
        self.sr = 16000
        self._t0 = 0

        self.title("")
        self.configure(fg_color=BG)
        self.overrideredirect(True)
        self.attributes("-topmost", True, "-alpha", OPACITY)
        sw = self.winfo_screenwidth()
        self.geometry(f"{self.S}x{self.S}+{sw-self.S-24}+80")

        self.bind("<Button-1>", self._drag_start)
        self.bind("<B1-Motion>", self._drag)
        self._dx = self._dy = 0

        self._orb_idle()
        self._check()
        self.after(10000, self._poll)

    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        self.geometry(f"+{self.winfo_x()+e.x-self._dx}+{self.winfo_y()+e.y-self._dy}")

    # ── Builders ──
    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _orb(self, color, text, cmd=None, border=PURPLE):
        """Render a perfectly round orb."""
        self._clear()
        self.geometry(f"{self.S}x{self.S}")
        f = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, border_width=0)
        f.pack(fill="both", expand=True)
        btn = ctk.CTkButton(f, text=text, width=self.S, height=self.S,
            corner_radius=RAD, fg_color=color, hover_color=color,
            text_color="#fff", font=("Segoe UI", 20), command=cmd,
            border_color=border, border_width=2)
        btn.pack(expand=True)

    def _orb_idle(self):
        self._orb(GLASS, "🎤", self._click, PURPLE)

    def _orb_rec(self):
        self._clear()
        self.geometry(f"{self.S+80}x{self.S}")
        f = ctk.CTkFrame(self, fg_color=GLASS, corner_radius=RAD,
            border_color=RED, border_width=2)
        f.pack(fill="both", expand=True)

        btn = ctk.CTkButton(f, text="⏹", width=self.S, height=self.S,
            corner_radius=RAD, fg_color=RED, hover_color=RED_DARK,
            text_color="#fff", font=("Segoe UI", 20), command=self._click,
            border_width=0)
        btn.pack(side="left")

        info = ctk.CTkFrame(f, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(6, 10))

        self.rec_time = ctk.CTkLabel(info, text="0s", font=("Segoe UI", 14, "bold"),
            text_color=PINK_BRIGHT, anchor="w")
        self.rec_time.pack(anchor="w")

        self.vu = ctk.CTkLabel(info, text="▁▁▁", font=("Segoe UI", 10),
            text_color=PURPLE, anchor="w")
        self.vu.pack(anchor="w")

    def _orb_result(self):
        self._clear()
        h = self.S + 80
        self.geometry(f"300x{h}")
        f = ctk.CTkFrame(self, fg_color=GLASS, corner_radius=RAD,
            border_color=GREEN, border_width=2)
        f.pack(fill="both", expand=True)

        # Top: check + status
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 0))

        self.status_lbl = ctk.CTkLabel(top, text="✅", font=("Segoe UI", 12),
            text_color=GREEN)
        self.status_lbl.pack(side="left")

        # Text area
        self.preview = ctk.CTkLabel(f, text="",
            font=("Segoe UI", 11), text_color=FG, anchor="w", justify="left",
            wraplength=260)
        self.preview.pack(fill="x", padx=14, pady=(6, 0))

        # Actions row
        acts = ctk.CTkFrame(f, fg_color="transparent")
        acts.pack(fill="x", padx=8, pady=(6, 8))

        ctk.CTkButton(acts, text="📋", width=36, height=32,
            corner_radius=RAD, fg_color=GLASS2, hover_color="#2a2a4e",
            text_color=FG, font=("Segoe UI", 13), command=self._copy
        ).pack(side="left", padx=(4, 2))

        self.tmux_btn = ctk.CTkButton(acts, text="📟", width=36, height=32,
            corner_radius=RAD, fg_color=GLASS2, hover_color="#2a2a4e",
            text_color=FG, font=("Segoe UI", 13), state="disabled",
            command=self._send_tmux)
        self.tmux_btn.pack(side="left", padx=2)

        self.tmux_var = ctk.StringVar(value="?")
        ctk.CTkOptionMenu(acts, variable=self.tmux_var,
            values=["(keine)"], width=90, height=32, corner_radius=RAD,
            fg_color=GLASS2, button_color=PURPLE, button_hover_color=PURPLE_DARK,
            dropdown_fg_color=GLASS, dropdown_hover_color=PURPLE_DARK,
            text_color=FG, font=("Segoe UI", 10)
        ).pack(side="left", padx=2)

        ctk.CTkButton(acts, text="✕", width=32, height=32,
            corner_radius=RAD, fg_color="transparent",
            hover_color="#2a2a3e", text_color="#555",
            font=("Segoe UI", 13), command=self._dismiss
        ).pack(side="right", padx=(4, 4))

        threading.Thread(target=self._load_tmux, daemon=True).start()

    def _orb_loading(self):
        self._orb(GLASS, "⏳", None, PURPLE)

    # ── Actions ──
    def _click(self):
        if self.recording:
            self._stop()
        else:
            self._record()

    def _record(self):
        if sd is None:
            return
        self.recording = True
        self.audio_data = []
        self._orb_rec()
        self._t0 = time()

        def cb(indata, frames, t, status):
            if self.recording:
                self.audio_data.append(indata.copy())
                try:
                    lvl = int(np.abs(indata).mean() * 30)
                    vu = "▁▂▃▄▅▆▇█"[min(lvl // 4, 7)]
                    el = int(time() - self._t0)
                    self.after(0, lambda: self.vu.configure(text=f"{'█'*min(lvl//3,8)}{'▁'*max(8-min(lvl//3,8),0)}"))
                    self.after(0, lambda: self.rec_time.configure(text=f"{el}s"))
                except:
                    pass

        try:
            self.audio_stream = sd.InputStream(
                samplerate=self.sr, channels=1, dtype="float32", callback=cb)
            self.audio_stream.start()
        except Exception as e:
            self.recording = False
            self._orb_idle()

    def _stop(self):
        self.recording = False
        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None

        if not self.audio_data:
            self._orb_idle()
            return

        self._orb_loading()
        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        try:
            arr = np.concatenate(self.audio_data, axis=0)
            buf = io.BytesIO()
            sf.write(buf, arr, self.sr, format="WAV")
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
            self._orb_idle()
            return
        lang = r.get("language", "?")
        conf = r.get("language_probability", 0) * 100
        dur = r.get("duration_s", 0)
        self._orb_result()
        self.status_lbl.configure(text=f"✅ {lang.upper()}  {conf:.0f}%  ·  {dur:.1f}s")
        self.preview.configure(text=self.text[:90]+("…" if len(self.text)>90 else ""))
        self.clipboard_clear()
        self.clipboard_append(self.text)

    def _on_error(self, msg):
        self._orb_idle()

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.text)
        self.status_lbl.configure(text="📋  Kopiert!")
        self.after(1500, lambda: self.status_lbl.configure(text=""))

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
            self.status_lbl.configure(text="📨  Gesendet!")
            self.after(1500, self._dismiss)

    def _dismiss(self):
        self.text = ""
        self._orb_idle()

    def _check(self):
        def c():
            r = self.srv.check()
            ok = "error" not in r
            self.after(0, lambda: self._orb_idle())
        threading.Thread(target=c, daemon=True).start()

    def _poll(self):
        self._check()
        self.after(15000, self._poll)

    def quit_app(self):
        self.quit()
        self.destroy()


if __name__ == "__main__":
    from time import time
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = OrbWidget()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app.quit_app()
