#!/usr/bin/env python3
"""VoiceWidget — Dynamic Island Style. Weißer Hintergrund, Lila/Blau Gradient."""
import sys, os, json, configparser, threading, subprocess, io, time
from pathlib import Path

CFG = Path(__file__).parent / "config.ini"
D = {"Server": {"host": "192.168.1.182", "user": "server", "port": "22", "whisper_port": "8766"},
     "Widget": {"opacity": "1.0"}}
c = configparser.ConfigParser()
if CFG.exists(): c.read(CFG)
for s, k in D.items():
    for kk, v in k.items():
        if not c.has_option(s, kk): c.set(s, kk, v)
with open(CFG, "w") as f: c.write(f)

H = c.get("Server", "host"); U = c.get("Server", "user"); WP = c.get("Server", "whisper_port")
WU = f"http://{H}:{WP}"; OP = float(c.get("Widget", "opacity"))

import customtkinter as ctk
try:
    import sounddevice as sd, numpy as np, soundfile as sf
except:
    sd = np = sf = None

# ── Modern Palette (White Island + Purple/Blue) ──
WHITE = "#ffffff"
BG_ISLAND = "#f8f9fc"
DARK = "#1a1a2e"
GRAY = "#6b7280"
GRAY_LIGHT = "#e5e7eb"
PURPLE = "#7c3aed"
PURPLE_LIGHT = "#a855f7"
BLUE = "#3b82f6"
BLUE_LIGHT = "#60a5fa"
GREEN = "#10b981"
RED = "#ef4444"
FG = "#1f2937"
FG2 = "#9ca3af"
R = 22  # corner radius

class Srv:
    def check(self):
        import urllib.request
        try:
            with urllib.request.urlopen(f"{WU}/health", timeout=4) as r:
                return json.loads(r.read())
        except: return {"error": "x"}
    def x(self, wav):
        import urllib.request
        b = b"---B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"v.wav\"\r\nContent-Type: audio/wav\r\n\r\n" + wav + b"\r\n---B--\r\n"
        r = urllib.request.Request(f"{WU}/transcribe", data=b, headers={"Content-Type": "multipart/form-data; boundary=--B"})
        try:
            with urllib.request.urlopen(r, timeout=120) as f:
                return json.loads(f.read())
        except Exception as ex: return {"error": str(ex)[:30]}
    def tmux(self):
        try:
            r = subprocess.run(["ssh", "-o", "ConnectTimeout=3", f"{U}@{H}", "tmux list-sessions -F '#{session_name}' 2>/dev/null"], capture_output=True, text=True, timeout=8)
            return [s.strip() for s in r.stdout.split("\n") if s.strip()]
        except: return []
    def st(self, s, t):
        try:
            safe = t.replace("'", "'\"'\"'").replace("\n", "\\n")
            subprocess.run(["ssh", "-o", "ConnectTimeout=3", f"{U}@{H}", f"tmux send-keys -t '{s}' '{safe}' Enter"], capture_output=True, timeout=8)
        except: pass

class Island(ctk.CTk):
    W = 200
    H = 48

    def __init__(self):
        super().__init__()
        self.srv = Srv()
        self.rec = False; self.ad = []; self.ast = None; self.txt = ""
        self.sr = 16000; self._t0 = 0

        self.title("")
        self.configure(fg_color=BG_ISLAND)
        self.overrideredirect(True)
        self.attributes("-topmost", True, "-alpha", OP)
        sw = self.winfo_screenwidth()
        self.geometry(f"{self.W}x{self.H}+{sw//2-self.W//2}+40")
        self.bind("<Button-1>", self._ds)
        self.bind("<B1-Motion>", self._dm)
        self._dx = self._dy = 0

        # Island shadow/glow
        self._island = ctk.CTkFrame(self, fg_color=WHITE, corner_radius=R,
            border_width=0)
        self._island.pack(fill="both", expand=True)
        self._island.configure(border_color=GRAY_LIGHT, border_width=1)

        self._idle()
        threading.Thread(target=self._hc, daemon=True).start()

    def _ds(self, e): self._dx, self._dy = e.x, e.y
    def _dm(self, e): self.geometry(f"+{self.winfo_x()+e.x-self._dx}+{self.winfo_y()+e.y-self._dy}")

    def _clear(self):
        for w in self._island.winfo_children(): w.destroy()

    def _btn(self, parent, text, cmd=None, bg=PURPLE, fg="#fff", w=36, h=36, font_size=14):
        return ctk.CTkButton(parent, text=text, width=w, height=h, corner_radius=w//2,
            fg_color=bg, hover_color=bg, text_color=fg, font=("Segoe UI", font_size),
            command=cmd, border_width=0)

    # ── IDLE: Kleine weiße Insel ──
    def _idle(self):
        self._clear()
        self.geometry(f"{self.W}x{self.H}")
        self._island.configure(border_color=GRAY_LIGHT)
        row = ctk.CTkFrame(self._island, fg_color="transparent")
        row.pack(expand=True, fill="both", padx=6, pady=4)

        self._btn(row, "🎤", self._click, PURPLE, "#fff", 38, 38, 16).pack(side="left", padx=(2, 6))

        ctk.CTkLabel(row, text="Voice", font=("Segoe UI", 13, "bold"),
            text_color=DARK).pack(side="left")

        ctk.CTkLabel(row, text="●", font=("Segoe UI", 8), text_color=GREEN).pack(side="right", padx=6)

    # ── RECORDING ──
    def _rec_ui(self):
        self._clear()
        w = 260
        self.geometry(f"{w}x{self.H}")
        self._island.configure(border_color=RED)
        row = ctk.CTkFrame(self._island, fg_color="transparent")
        row.pack(expand=True, fill="both", padx=6, pady=4)

        self._btn(row, "⏹", self._click, RED, "#fff", 38, 38, 16).pack(side="left", padx=(2, 6))

        self._rt = ctk.CTkLabel(row, text="0:00", font=("Segoe UI", 14, "bold"),
            text_color=DARK, width=40)
        self._rt.pack(side="left")

        self._vu = ctk.CTkLabel(row, text="▁▁▁▁▁▁▁▁", font=("Segoe UI", 10),
            text_color=PURPLE, width=80)
        self._vu.pack(side="left", padx=(6, 0))

        ctk.CTkLabel(row, text="●", font=("Segoe UI", 8), text_color=RED).pack(side="right", padx=8)

    # ── LOADING ──
    def _load_ui(self):
        self._clear()
        self.geometry(f"160x{self.H}")
        self._island.configure(border_color=GRAY_LIGHT)
        ctk.CTkLabel(self._island, text="⏳ Transkribieren...",
            font=("Segoe UI", 13), text_color=GRAY).pack(expand=True)

    # ── RESULT ──
    def _res_ui(self):
        self._clear()
        w = 340
        self.geometry(f"{w}x{self.H+60}")
        self._island.configure(border_color=PURPLE_LIGHT)
        # Close btn top-right
        top = ctk.CTkFrame(self._island, fg_color="transparent", height=20)
        top.pack(fill="x", padx=8, pady=(4, 0))
        self._sl = ctk.CTkLabel(top, text="✅", font=("Segoe UI", 10), text_color=GREEN)
        self._sl.pack(side="left")
        ctk.CTkButton(top, text="✕", width=20, height=20, corner_radius=10,
            fg_color="transparent", hover_color=GRAY_LIGHT, text_color=GRAY,
            font=("Segoe UI", 10), command=self._dismiss).pack(side="right")

        # Text preview
        self._pv = ctk.CTkLabel(self._island, text="", font=("Segoe UI", 12),
            text_color=FG, anchor="w", justify="left", wraplength=310)
        self._pv.pack(fill="x", padx=14, pady=(4, 0))

        # Actions
        acts = ctk.CTkFrame(self._island, fg_color="transparent")
        acts.pack(fill="x", padx=8, pady=(4, 8))

        self._cp_btn = self._btn(acts, "📋", self._cp, PURPLE, "#fff", 34, 34, 13)
        self._cp_btn.pack(side="left", padx=(4, 2))

        self._tb = self._btn(acts, "📟", self._send, BLUE, "#fff", 34, 34, 13)
        self._tb.pack(side="left", padx=2)
        self._tb.configure(state="disabled")

        self._tv = ctk.StringVar(value="?")
        ctk.CTkOptionMenu(acts, variable=self._tv, values=["(keine)"], width=90, height=34,
            corner_radius=17, fg_color=GRAY_LIGHT, button_color=BLUE, button_hover_color=BLUE_LIGHT,
            dropdown_fg_color=WHITE, dropdown_hover_color=BLUE_LIGHT,
            text_color=DARK, font=("Segoe UI", 11, "bold")
        ).pack(side="left", padx=2)

        # Progress bar
        self._prog = ctk.CTkProgressBar(self._island, height=2, corner_radius=1,
            fg_color=GRAY_LIGHT, progress_color=PURPLE, mode="determinate")
        self._prog.pack(fill="x", padx=0, pady=0)
        self._prog.set(1.0)

        threading.Thread(target=self._lt, daemon=True).start()

    # ── Actions ──
    def _click(self):
        if self.rec: self._stop()
        else: self._record()

    def _record(self):
        if sd is None: return
        self.rec = True; self.ad = []; self._rec_ui(); self._t0 = time.time()
        def cb(indata, frames, t, status):
            if self.rec:
                self.ad.append(indata.copy())
                try:
                    l = int(np.abs(indata).mean() * 30)
                    el = int(time.time() - self._t0)
                    m, s = el // 60, el % 60
                    vu = "█" * min(l // 3, 8) + "▁" * max(8 - min(l // 3, 8), 0)
                    self.after(0, lambda v=vu, m=m, s=s: (
                        self._vu.configure(text=v),
                        self._rt.configure(text=f"{m}:{s:02d}"),
                    ))
                except: pass
        try:
            self.ast = sd.InputStream(samplerate=self.sr, channels=1, dtype="float32", callback=cb)
            self.ast.start()
        except: self.rec = False; self._idle()

    def _stop(self):
        self.rec = False
        if self.ast: self.ast.stop(); self.ast.close(); self.ast = None
        if not self.ad: self._idle(); return
        self._load_ui()
        threading.Thread(target=self._tx, daemon=True).start()

    def _tx(self):
        try:
            arr = np.concatenate(self.ad, axis=0)
            buf = io.BytesIO()
            sf.write(buf, arr, self.sr, format="WAV")
            r = self.srv.x(buf.getvalue())
            self.after(0, lambda: self._rx(r))
        except: self.after(0, self._idle)

    def _rx(self, r):
        if "error" in r: self._idle(); return
        self.txt = r.get("text", "")
        if not self.txt.strip(): self._idle(); return
        lang = r.get("language", "?"); conf = r.get("language_probability", 0) * 100
        dur = r.get("duration_s", 0)
        self._res_ui()
        self._sl.configure(text=f"✅ {lang.upper()}  {conf:.0f}%  ·  {dur:.1f}s")
        self._pv.configure(text=self.txt[:110]+("…" if len(self.txt)>110 else ""))
        self.clipboard_clear(); self.clipboard_append(self.txt)

    def _cp(self):
        self.clipboard_clear(); self.clipboard_append(self.txt)
        self._sl.configure(text="📋  Kopiert!"); self.after(1500, lambda: self._sl.configure(text=""))

    def _lt(self):
        ss = self.srv.tmux()
        if ss:
            self.after(0, lambda s=ss: (self._tv.set(s[0]), self._tb.configure(state="normal"),
                       self._tb.master.winfo_children()[3].configure(values=s)))

    def _send(self):
        s = self._tv.get()
        if s and self.txt and not s.startswith("("):
            self.srv.st(s, self.txt); self._sl.configure(text="📨  Gesendet!")
            self.after(1500, self._dismiss)

    def _dismiss(self): self.txt = ""; self._idle()
    def _hc(self):
        ok = "error" not in self.srv.check()
        self.after(0, lambda: self._idle())


if __name__ == "__main__":
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    app = Island()
    try: app.mainloop()
    except KeyboardInterrupt: app.quit_app()
