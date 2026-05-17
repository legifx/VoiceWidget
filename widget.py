#!/usr/bin/env python3
"""VoiceWidget — Dynamic Island. Transparente Ecken, Größe nur bei Result."""
import sys,os,json,configparser,threading,subprocess,io,time
from pathlib import Path
from urllib.parse import urlparse

CFG=Path(__file__).parent/"config.ini"
D={"Server":{"host":"192.168.1.182","user":"server","port":"22","whisper_port":"8766"},
   "Widget":{"opacity":"1.0"}}
c=configparser.ConfigParser()
if CFG.exists():c.read(CFG)
for s,k in D.items():
    for kk,v in k.items():
        if not c.has_option(s,kk):c.set(s,kk,v)
with open(CFG,"w")as f:c.write(f)
H=c.get("Server","host");U=c.get("Server","user");WP=c.get("Server","whisper_port")
WU=f"http://{H}:{WP}";OP=float(c.get("Widget","opacity"))

import customtkinter as ctk
try:
    import sounddevice as sd; import numpy as np; import soundfile as sf
    HAS_AUDIO=True
except Exception as e:
    print(f"[AUDIO ERROR] {e}"); sd=np=sf=None; HAS_AUDIO=False

# Farben (Apple Dynamic Island)
BG_W="#f5f6fa"; CARD="#ffffff"; FG="#1a1a2e"
ACC="#007aff"; ACC_LT="#60a5fa"; REC="#ff3b30"
SUCCESS="#22c55e"; SEC="#86868b"; DIV="#d2d2d7"
PURP="#8b5cf6"; PURP_LT="#a78bfa"

def mp_enc(bound, files):
    buf=io.BytesIO()
    for n,(fn,dt,mime) in files.items():
        buf.write(b"--"+bound+b"\r\n")
        buf.write(f'Content-Disposition: form-data; name="{n}"; filename="{fn}"\r\n'.encode())
        buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
        buf.write(dt); buf.write(b"\r\n")
    buf.write(b"--"+bound+b"--\r\n")
    return buf.getvalue()

def http_post(url, wav):
    import http.client
    p=urlparse(url)
    conn=http.client.HTTPConnection(p.hostname, p.port or 80, timeout=120)
    body=mp_enc(b"----VW", {"file": ("v.wav", wav, "audio/wav")})
    conn.request("POST", p.path, body, {"Content-Type":"multipart/form-data; boundary=----VW"})
    return json.loads(conn.getresponse().read())

class Srv:
    def health(self):
        import urllib.request
        try: return json.loads(urllib.request.urlopen(f"{WU}/health", timeout=4).read())
        except: return{"error":1}
    def trans(self, wav):
        try: return http_post(f"{WU}/transcribe", wav)
        except Exception as e: return{"error":str(e)}
    def tmux_ls(self):
        try:
            r=subprocess.run(["ssh","-o","ConnectTimeout=3",f"{U}@{H}","tmux list-sessions -F '#{session_name}' 2>/dev/null"],capture_output=True,text=True,timeout=8)
            return[s.strip()for s in r.stdout.split("\n")if s.strip()]
        except:return[]
    def tmux_send(self, sess, txt):
        try:
            safe=txt.replace("'","'\"'\"'").replace("\n","\\n")
            subprocess.run(["ssh","-o","ConnectTimeout=3",f"{U}@{H}",f"tmux send-keys -t '{sess}' '{safe}' Enter"],capture_output=True,timeout=8)
        except:pass

class Island(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.srv=Srv()
        self.rec=False; self.ad=[]; self.ast=None; self.txt=""
        self.sr=16000; self._t0=0; self._state="idle"

        # Fenster: transparente Ecken (Windows: Farbkey), Topmost
        self.configure(fg_color=BG_W)
        self.overrideredirect(True)
        self.attributes("-topmost",True,"-alpha",OP)
        self.wm_attributes("-transparentcolor","#000001")

        sw=self.winfo_screenwidth()
        self.geometry(f"240x64+{sw//2-120}+48")
        self.bind("<Button-1>",self._down); self.bind("<B1-Motion>",self._move)
        self._dx=self._dy=0

        # Haupt-Frame: weisse Pille mit max. Rundung
        self.main=ctk.CTkFrame(self, fg_color=CARD, corner_radius=999)
        self.main.pack(fill="both", expand=True, padx=8, pady=8)

        self._idle()
        threading.Thread(target=self._hc, daemon=True).start()

    def _down(self, e): self._dx,self._dy=e.x,e.y
    def _move(self, e):
        x=self.winfo_x()+e.x-self._dx; y=self.winfo_y()+e.y-self._dy
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{x}+{y}")
    def _clear(self):
        for w in self.main.winfo_children(): w.destroy()

    def _animate(self, target_w, target_h, steps=12, delay=15):
        cur_w=self.winfo_width(); cur_h=self.winfo_height()
        if cur_w==target_w and cur_h==target_h:
            self.geometry(f"{target_w}x{target_h}"); return
        def step(i):
            if i>=steps:
                self.geometry(f"{target_w}x{target_h}"); return
            t=i/steps
            w=int(cur_w + (target_w-cur_w)*t)
            h=int(cur_h + (target_h-cur_h)*t)
            self.geometry(f"{w}x{h}")
            self.after(delay, lambda: step(i+1))
        step(0)

    # ── IDLE: konstant 240x64 ──
    def _idle(self):
        self._clear(); self._state="idle"; self.geometry("240x64")
        r=ctk.CTkFrame(self.main, fg_color="transparent"); r.pack(fill="both", expand=True, padx=16, pady=12)
        ctk.CTkButton(r, text="🎤", width=40, height=40, corner_radius=20,
            fg_color=PURP, hover_color=PURP_LT, text_color=CARD, font=("Segoe UI",17),
            command=self._toggle, border_width=0).pack(side="left")
        ctk.CTkLabel(r, text="Voice", font=("Segoe UI",14,"bold"), text_color=FG).pack(side="left", padx=10)
        ctk.CTkLabel(r, text="●", font=("Segoe UI",8), text_color=SUCCESS).pack(side="right")

    # ── RECORDING: konstant 240x64 ──
    def _rec_ui(self):
        self._clear(); self._state="rec"; self.geometry("240x64")
        r=ctk.CTkFrame(self.main, fg_color="transparent"); r.pack(fill="both", expand=True, padx=16, pady=12)
        ctk.CTkButton(r, text="⏹", width=40, height=40, corner_radius=20,
            fg_color=REC, hover_color="#e02020", text_color=CARD, font=("Segoe UI",17),
            command=self._toggle, border_width=0).pack(side="left")
        self._timer=ctk.CTkLabel(r, text="0:00", font=("Segoe UI",14,"bold"), text_color=FG); self._timer.pack(side="left", padx=10)
        self._vu=ctk.CTkLabel(r, text="▁▁▁▁▁▁", font=("Segoe UI",9), text_color=REC); self._vu.pack(side="left")
        ctk.CTkLabel(r, text="●", font=("Segoe UI",8), text_color=REC).pack(side="right")

    # ── LOADING: konstant 240x64 ──
    def _load_ui(self):
        self._clear(); self._state="load"; self.geometry("240x64")
        r=ctk.CTkFrame(self.main, fg_color="transparent"); r.pack(fill="both", expand=True, padx=16, pady=12)
        ctk.CTkLabel(r, text="⏳", font=("Segoe UI",17), text_color=SEC).pack(side="left")
        ctk.CTkLabel(r, text="Transkribieren...", font=("Segoe UI",13), text_color=SEC).pack(side="left", padx=8)

    # ── RESULT: animiert auf dynamische Höhe ──
    def _res_ui(self, text, lang, conf, dur):
        self._clear(); self._state="result"; self.txt=text
        r=ctk.CTkFrame(self.main, fg_color="transparent"); r.pack(fill="both", expand=True, padx=16, pady=12)

        # Header
        hdr=ctk.CTkFrame(r, fg_color="transparent"); hdr.pack(fill="x", pady=(0,4))
        self._stat=ctk.CTkLabel(hdr, text=f"✅  {lang.upper()}  {conf:.0f}%  ·  {dur:.1f}s",
            font=("Segoe UI",11), text_color=SUCCESS); self._stat.pack(side="left")
        ctk.CTkButton(hdr, text="✕", width=22, height=22, corner_radius=11,
            fg_color="transparent", hover_color=DIV, text_color=SEC,
            font=("Segoe UI",10), command=self._reset).pack(side="right")

        # Text (bis zu 8 Zeilen)
        lines = self._wrap_text(text, 38)
        preview = "\n".join(lines[:8]) + ("…" if len(lines) > 8 else "")
        ctk.CTkLabel(r, text=preview, font=("Segoe UI",12), text_color=FG,
            anchor="w", justify="left", wraplength=330).pack(fill="x", pady=(0,8))

        # Actions
        acts=ctk.CTkFrame(r, fg_color="transparent"); acts.pack(fill="x")
        ctk.CTkButton(acts, text="📋", width=36, height=36, corner_radius=18,
            fg_color=PURP, hover_color=PURP_LT, text_color=CARD, font=("Segoe UI",14),
            command=self._copy, border_width=0).pack(side="left", padx=(0,6))
        self._send_btn=ctk.CTkButton(acts, text="📟", width=36, height=36, corner_radius=18,
            fg_color=ACC, hover_color=ACC_LT, text_color=CARD, font=("Segoe UI",14),
            command=self._send, border_width=0, state="disabled")
        self._send_btn.pack(side="left", padx=(0,6))
        self._sess=ctk.StringVar(value="(keine)")
        ctk.CTkOptionMenu(acts, variable=self._sess, values=["(keine)"],
            width=110, height=36, corner_radius=18, fg_color=DIV, button_color=ACC,
            button_hover_color=ACC_LT, dropdown_fg_color=CARD, dropdown_hover_color=ACC_LT,
            text_color=FG, font=("Segoe UI",11)).pack(side="left")

        self.clipboard_clear(); self.clipboard_append(text)
        threading.Thread(target=self._load_sess, daemon=True).start()

        # Dynamische Höhe berechnen + smooth animation
        line_h=18; pad=40; hdr_h=30; acts_h=50
        total_h = hdr_h + (min(len(lines),8)*line_h) + 8 + acts_h + pad
        total_h = max(140, min(total_h, 300))
        self.after(100, lambda: self._animate(380, total_h))

    def _wrap_text(self, text, width):
        words=text.split(); lines=[]; cur=""
        for w in words:
            if len(cur)+len(w)+1 <= width:
                cur = (cur+" "+w).strip()
            else:
                lines.append(cur); cur=w
        if cur: lines.append(cur)
        return lines

    def _toggle(self):
        if self._state=="rec": self._stop()
        else: self._start()

    def _start(self):
        if not HAS_AUDIO: return
        self.rec=True; self.ad=[]; self._rec_ui(); self._t0=time.time()
        def cb(indata,frames,t,status):
            if not self.rec: return
            self.ad.append(indata.copy())
            try:
                rms=float(np.abs(indata).mean())
                lvl=min(int(rms*200),24)
                vu="█"*lvl+"▁"*(24-lvl)
                el=int(time.time()-self._t0); m,s=el//60,el%60
                self.after(0, lambda v=vu,mm=m,ss=s:(
                    self._vu.configure(text=v) if hasattr(self,"_vu") else None,
                    self._timer.configure(text=f"{mm}:{ss:02d}") if hasattr(self,"_timer") else None,
                ))
            except: pass
        try:
            self.ast=sd.InputStream(samplerate=self.sr, channels=1, dtype="float32", callback=cb)
            self.ast.start()
        except Exception as e:
            print(f"[START] {e}"); self.rec=False; self._idle()

    def _stop(self):
        self.rec=False
        if self.ast:
            try: self.ast.stop(); self.ast.close()
            except: pass
            self.ast=None
        if sum(len(b) for b in self.ad)==0: self._idle(); return
        self._load_ui()
        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        try:
            arr=np.concatenate(self.ad,axis=0)
            buf=io.BytesIO()
            sf.write(buf, arr, self.sr, format="WAV")
            r=self.srv.trans(buf.getvalue())
            self.after(0, lambda res=r: self._show(res))
        except Exception as e:
            print(f"[TX] {e}"); self.after(0, self._idle)

    def _show(self, r):
        if "error" in r or "detail" in r: self._idle(); return
        txt=r.get("text","")
        if not txt.strip(): self._idle(); return
        self._res_ui(txt, r.get("language","?"), r.get("language_probability",0)*100, r.get("duration_s",0))

    def _copy(self):
        self.clipboard_clear(); self.clipboard_append(self.txt)
        self._stat.configure(text="📋 Kopiert!", text_color=PURP)
        self.after(1000, self._reset)

    def _load_sess(self):
        ss=self.srv.tmux_ls()
        if ss:
            self.after(0, lambda s=ss:(
                self._sess.set(s[0]),
                self._send_btn.configure(state="normal"),
                self._send_btn.master.winfo_children()[2].configure(values=s)
            ))

    def _send(self):
        s=self._sess.get()
        if s and self.txt and not s.startswith("("):
            self.srv.tmux_send(s, self.txt)
            self._stat.configure(text="📨 Gesendet!", text_color=ACC)
            self.after(1000, self._reset)

    def _reset(self):
        self.txt=""; self._idle()

    def _hc(self):
        r=self.srv.health(); print(f"[HC] {r}")

if __name__=="__main__":
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    app=Island()
    try: app.mainloop()
    except: pass