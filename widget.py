#!/usr/bin/env python3
"""VoiceWidget — einfaches rundes Orb. Ein Klick aufnehmen, Text in Zwischenablage."""
import sys, os, json, configparser, threading, subprocess, io, time
from pathlib import Path

CFG = Path(__file__).parent / "config.ini"
D = {"Server": {"host": "192.168.1.182", "user": "server", "port": "22", "whisper_port": "8766"},
     "Widget": {"opacity": "0.92"}}
c = configparser.ConfigParser()
if CFG.exists(): c.read(CFG)
for s, k in D.items():
    for kk, v in k.items():
        if not c.has_option(s, kk): c.set(s, kk, v)
with open(CFG, "w") as f: c.write(f)

H = c.get("Server", "host")
U = c.get("Server", "user")
WP = c.get("Server", "whisper_port")
WU = f"http://{H}:{WP}"
OP = float(c.get("Widget", "opacity"))

import customtkinter as ctk
try:
    import sounddevice as sd, numpy as np, soundfile as sf
except:
    sd = np = sf = None

# ── Farben ──
BG = "#08080f"
GL = "#141428"
GL2 = "#1c1c3a"
PU = "#a855f7"
PUD = "#7c3aed"
PK = "#ec4899"
RD = "#ef4444"
GN = "#22c55e"
FG = "#f0f0ff"
R = 999

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

class Orb(ctk.CTk):
    S = 56
    def __init__(self):
        super().__init__()
        self.srv = Srv()
        self.rec = False
        self.ad = []
        self.ast = None
        self.txt = ""
        self.sr = 16000
        self._t0 = 0
        self._loading = False
        self._result_widgets = False

        self.title("")
        self.configure(fg_color=BG)
        self.overrideredirect(True)
        self.attributes("-topmost", True, "-alpha", OP)
        sw = self.winfo_screenwidth()
        self.geometry(f"{self.S}x{self.S}+{sw-self.S-24}+80")
        self.bind("<Button-1>", self._ds)
        self.bind("<B1-Motion>", self._dm)
        self._dx = self._dy = 0
        self._idle()
        threading.Thread(target=self._hc, daemon=True).start()

    def _ds(self, e): self._dx, self._dy = e.x, e.y
    def _dm(self, e): self.geometry(f"+{self.winfo_x()+e.x-self._dx}+{self.winfo_y()+e.y-self._dy}")
    def _clr(self):
        self._result_widgets = False
        for w in self.winfo_children(): w.destroy()

    def _idle(self, color=GL, border=PU):
        self._clr()
        self.geometry(f"{self.S}x{self.S}")
        self._loading = False
        f = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, border_width=0)
        f.pack(fill="both", expand=True)
        ctk.CTkButton(f, text="🎤", width=self.S, height=self.S,
            corner_radius=R, fg_color=color, hover_color=color,
            text_color="#fff", font=("Segoe UI", 20), command=self._click,
            border_color=border, border_width=2).pack(expand=True)

    def _rec_ui(self):
        self._clr()
        self.geometry(f"{self.S+80}x{self.S}")
        f = ctk.CTkFrame(self, fg_color=GL, corner_radius=R, border_color=RD, border_width=2)
        f.pack(fill="both", expand=True)
        ctk.CTkButton(f, text="⏹", width=self.S, height=self.S, corner_radius=R,
            fg_color=RD, hover_color="#dc2626", text_color="#fff",
            font=("Segoe UI", 20), command=self._click, border_width=0).pack(side="left")
        info = ctk.CTkFrame(f, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(6, 10))
        self._rt = ctk.CTkLabel(info, text="0s", font=("Segoe UI", 14, "bold"),
            text_color=PK, anchor="w")
        self._rt.pack(anchor="w")
        self._vu = ctk.CTkLabel(info, text="▁▁▁", font=("Segoe UI", 10), text_color=PU, anchor="w")
        self._vu.pack(anchor="w")

    def _load_ui(self):
        self._clr()
        self.geometry(f"{self.S}x{self.S}")
        self._loading = True
        f = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, border_width=0)
        f.pack(fill="both", expand=True)
        ctk.CTkLabel(f, text="⏳", font=("Segoe UI", 24), text_color=PU).pack(expand=True)

    def _res_ui(self):
        self._clr()
        self._result_widgets = True
        h = self.S + 80
        self.geometry(f"300x{h}")
        f = ctk.CTkFrame(self, fg_color=GL, corner_radius=R, border_color=GN, border_width=2)
        f.pack(fill="both", expand=True)
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 0))
        self._sl = ctk.CTkLabel(top, text="✅", font=("Segoe UI", 12), text_color=GN)
        self._sl.pack(side="left")
        self._pv = ctk.CTkLabel(f, text="", font=("Segoe UI", 11), text_color=FG,
            anchor="w", justify="left", wraplength=260)
        self._pv.pack(fill="x", padx=14, pady=(6, 0))
        acts = ctk.CTkFrame(f, fg_color="transparent")
        acts.pack(fill="x", padx=8, pady=(6, 8))
        ctk.CTkButton(acts, text="📋", width=36, height=32, corner_radius=R,
            fg_color=GL2, hover_color="#2a2a4e", text_color=FG, font=("Segoe UI", 13),
            command=self._cp).pack(side="left", padx=(4, 2))
        self._tb = ctk.CTkButton(acts, text="📟", width=36, height=32, corner_radius=R,
            fg_color=GL2, hover_color="#2a2a4e", text_color=FG, font=("Segoe UI", 13),
            state="disabled", command=self._send)
        self._tb.pack(side="left", padx=2)
        self._tv = ctk.StringVar(value="?")
        ctk.CTkOptionMenu(acts, variable=self._tv, values=["(keine)"], width=90, height=32,
            corner_radius=R, fg_color=GL2, button_color=PU, button_hover_color=PUD,
            dropdown_fg_color=GL, dropdown_hover_color=PUD, text_color=FG, font=("Segoe UI", 10)
        ).pack(side="left", padx=2)
        ctk.CTkButton(acts, text="✕", width=32, height=32, corner_radius=R,
            fg_color="transparent", hover_color="#2a2a3e", text_color="#555",
            font=("Segoe UI", 13), command=self._dismiss).pack(side="right", padx=(4, 4))
        threading.Thread(target=self._lt, daemon=True).start()

    def _click(self):
        if self._loading: return
        if self.rec: self._stop()
        else: self._record()

    def _record(self):
        if sd is None: return
        self.rec = True
        self.ad = []
        self._rec_ui()
        self._t0 = time.time()
        def cb(indata, frames, t, status):
            if self.rec:
                self.ad.append(indata.copy())
                try:
                    l = int(np.abs(indata).mean() * 30)
                    el = int(time.time() - self._t0)
                    vu = "█" * min(l // 3, 8) + "▁" * max(8 - min(l // 3, 8), 0)
                    self.after(0, lambda v=vu, e=el: self._vu.configure(text=v) or self._rt.configure(text=f"{e}s"))
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
        except Exception as ex:
            self.after(0, lambda: self._idle())

    def _rx(self, r):
        if "error" in r: self._idle(); return
        self.txt = r.get("text", "")
        if not self.txt.strip(): self._idle(); return
        lang = r.get("language", "?")
        conf = r.get("language_probability", 0) * 100
        dur = r.get("duration_s", 0)
        self._res_ui()
        self._sl.configure(text=f"✅ {lang.upper()}  {conf:.0f}%  ·  {dur:.1f}s")
        self._pv.configure(text=self.txt[:90]+("…" if len(self.txt)>90 else ""))
        self.clipboard_clear(); self.clipboard_append(self.txt)

    def _cp(self):
        self.clipboard_clear(); self.clipboard_append(self.txt)
        self._sl.configure(text="📋  Kopiert!")
        self.after(1500, lambda: self._sl.configure(text=""))

    def _lt(self):
        ss = self.srv.tmux()
        if ss:
            self.after(0, lambda s=ss: self._tv.set(s[0]) or self._tb.configure(state="normal") or
                       self._tb.master.winfo_children()[3].configure(values=s))

    def _send(self):
        s = self._tv.get()
        if s and self.txt and not s.startswith("("):
            self.srv.st(s, self.txt)
            self._sl.configure(text="📨  Gesendet!")
            self.after(1500, self._dismiss)

    def _dismiss(self):
        self.txt = ""
        self._idle()

    def _hc(self):
        ok = "error" not in self.srv.check()
        self.after(0, lambda: self._idle(GL if ok else GL2, GN if ok else RD))


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = Orb()
    try: app.mainloop()
    except KeyboardInterrupt: app.quit_app()
