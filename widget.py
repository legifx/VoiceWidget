#!/usr/bin/env python3
"""VoiceWidget — Dynamic Island. Weiss, Rund, Minimal."""
import sys,os,json,configparser,threading,subprocess,io,time
from pathlib import Path

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
    import sounddevice as sd,numpy as np,soundfile as sf
    HAS_AUDIO=True
except:
    sd=np=sf=None; HAS_AUDIO=False

W="#ffffff";BG="#f5f6fa";DARK="#1a1a2e";GR="#e0e3ea"
PU="#8b5cf6";PUL="#a78bfa";BL="#60a5fa";BLL="#93c5fd"
GN="#34d399";RD="#f87171";GY="#9ca3af";FG="#374151"

def http_post(url, fields, files):
    """Multipart form via stdlib http.client. fields={str:str}, files={str:(name,data,mime)}"""
    import email.mime.multipart, email.mime.base, email.generator
    import io as _io, http.client as hc

    boundary = b"----VoiceWidget123"
    buf = _io.BytesIO()

    # fields
    for k, v in fields.items():
        buf.write(b"--" + boundary + b"\r\n")
        buf.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        buf.write(v.encode()); buf.write(b"\r\n")

    # files
    for k, (fname, data, mime) in files.items():
        buf.write(b"--" + boundary + b"\r\n")
        buf.write(f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'.encode())
        buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
        buf.write(data); buf.write(b"\r\n")

    buf.write(b"--" + boundary + b"--\r\n")

    _, hostport = url.split("://")
    host, portpath = hostport.split("/", 1)
    path = "/" + portpath.split("/", 1)[-1] if "/" in portpath else "/"
    port = int(host.split(":")[-1]) if ":" in host else 80

    conn = hc.HTTPConnection(host.split(":")[0], port, timeout=120)
    conn.connect()
    conn.request("POST", path, buf.getvalue(),
        {"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"})
    resp = conn.getresponse()
    return resp.read()

class Srv:
    def check(self):
        import urllib.request
        try:
            with urllib.request.urlopen(f"{WU}/health",timeout=4)as r:
                return json.loads(r.read())
        except:return{"error":"x"}
    def x(self,wav):
        try:
            data=http_post(f"{WU}/transcribe",{},{"file":("v.wav",wav,"audio/wav")})
            return json.loads(data)
        except Exception as ex:
            return{"error":str(ex)}
    def tmux(self):
        try:
            r=subprocess.run(["ssh","-o","ConnectTimeout=3",f"{U}@{H}","tmux list-sessions -F '#{session_name}' 2>/dev/null"],capture_output=True,text=True,timeout=8)
            return[s.strip()for s in r.stdout.split("\n")if s.strip()]
        except:return[]
    def st(self,s,t):
        try:
            safe=t.replace("'","'\"'\"'").replace("\n","\\n")
            subprocess.run(["ssh","-o","ConnectTimeout=3",f"{U}@{H}",f"tmux send-keys -t '{s}' '{safe}' Enter"],capture_output=True,timeout=8)
        except:pass

class V(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.srv=Srv()
        self.rec=False;self.ad=[];self.ast=None;self.txt=""
        self.sr=16000;self._t0=0;self._state="idle"
        self.title("");self.configure(fg_color=BG);self.overrideredirect(True)
        self.attributes("-topmost",True,"-alpha",OP)
        sw=self.winfo_screenwidth()
        self.geometry("220x58+"+str(sw//2-110)+"+48")
        self.bind("<Button-1>",self._ds);self.bind("<B1-Motion>",self._dm)
        self._dx=self._dy=0
        self.main=ctk.CTkFrame(self,fg_color=W,corner_radius=29)
        self.main.pack(fill="both",expand=True)
        self._idle(); threading.Thread(target=self._hc,daemon=True).start()

    def _ds(self,e):self._dx,self._dy=e.x,e.y
    def _dm(self,e):
        p=self.winfo_x()+e.x-self._dx; n=self.winfo_y()+e.y-self._dy
        self.geometry(f"220x58+{p}+{n}")
    def _clear(self):
        for w in self.main.winfo_children():w.destroy()

    def _idle(self):
        self._clear(); self._state="idle"; self.geometry("220x58")
        r=ctk.CTkFrame(self.main,fg_color="transparent"); r.pack(fill="both",expand=True,padx=12,pady=0)
        ctk.CTkButton(r,text="🎤",width=44,height=44,corner_radius=22,
            fg_color=PU,hover_color=PUL,text_color=W,font=("Segoe UI",18),
            command=self._toggle,border_width=0).pack(side="left",padx=(2,12))
        ctk.CTkLabel(r,text="Voice",font=("Segoe UI",15,"bold"),text_color=DARK).pack(side="left",padx=(0,8))
        ctk.CTkLabel(r,text="●",font=("Segoe UI",10),text_color=GN).pack(side="right",padx=8)

    def _rec(self):
        self._clear(); self._state="rec"; self.geometry("290x58")
        r=ctk.CTkFrame(self.main,fg_color="transparent"); r.pack(fill="both",expand=True,padx=12,pady=0)
        ctk.CTkButton(r,text="⏹",width=44,height=44,corner_radius=22,
            fg_color=RD,hover_color="#ef4444",text_color=W,font=("Segoe UI",18),
            command=self._toggle,border_width=0).pack(side="left",padx=(2,12))
        self._rt=ctk.CTkLabel(r,text="0:00",font=("Segoe UI",16,"bold"),text_color=DARK)
        self._rt.pack(side="left",padx=(0,10))
        self._vu=ctk.CTkLabel(r,text="▁▁▁▁▁▁",font=("Segoe UI",10),text_color=PU)
        self._vu.pack(side="left")

    def _load(self):
        self._clear(); self._state="load"; self.geometry("180x58")
        r=ctk.CTkFrame(self.main,fg_color="transparent"); r.pack(fill="both",expand=True,padx=12,pady=0)
        ctk.CTkLabel(r,text="⏳",font=("Segoe UI",18),text_color=GY).pack(side="left",padx=(4,8))
        ctk.CTkLabel(r,text="Transkribieren...",font=("Segoe UI",13),text_color=GY).pack(side="left")

    def _res(self,text,lang,conf,dur):
        self._clear(); self._state="res"; self.geometry("360x120")
        self.txt=text
        r=ctk.CTkFrame(self.main,fg_color="transparent"); r.pack(fill="both",expand=True,padx=12,pady=0)
        top=ctk.CTkFrame(r,fg_color="transparent"); top.pack(fill="x",pady=(0,6))
        self._sl=ctk.CTkLabel(top,text=f"✅  {lang.upper()}  {conf:.0f}%  ·  {dur:.1f}s",
            font=("Segoe UI",11),text_color=GN); self._sl.pack(side="left")
        ctk.CTkButton(top,text="✕",width=24,height=24,corner_radius=12,
            fg_color="transparent",hover_color=GR,text_color=GY,
            font=("Segoe UI",10),command=self._dismiss).pack(side="right")
        ctk.CTkLabel(r,text=text[:110]+("…"if len(text)>110 else""),
            font=("Segoe UI",12),text_color=FG,anchor="w",justify="left",wraplength=325
        ).pack(fill="x",pady=(0,8))
        acts=ctk.CTkFrame(r,fg_color="transparent"); acts.pack(fill="x")
        ctk.CTkButton(acts,text="📋",width=38,height=38,corner_radius=19,
            fg_color=PU,hover_color=PUL,text_color=W,font=("Segoe UI",15),
            command=self._cp,border_width=0).pack(side="left",padx=(0,8))
        self._tb=ctk.CTkButton(acts,text="📟",width=38,height=38,corner_radius=19,
            fg_color=BL,hover_color=BLL,text_color=W,font=("Segoe UI",15),
            command=self._send,border_width=0,state="disabled")
        self._tb.pack(side="left",padx=(0,8))
        self._tv=ctk.StringVar(value="(keine)")
        ctk.CTkOptionMenu(acts,variable=self._tv,values=["(keine)"],
            width=120,height=38,corner_radius=19,
            fg_color=GR,button_color=BL,button_hover_color=BLL,
            dropdown_fg_color=W,dropdown_hover_color=BLL,
            text_color=DARK,font=("Segoe UI",12,"bold")).pack(side="left")
        self.clipboard_clear(); self.clipboard_append(text)
        threading.Thread(target=self._lt,daemon=True).start()

    def _toggle(self):
        if self._state=="rec": self._stop()
        else: self._record()

    def _record(self):
        if not HAS_AUDIO: return
        self.rec=True; self.ad=[]; self._rec(); self._t0=time.time()
        def cb(indata,frames,t,status):
            if not self.rec: return
            self.ad.append(indata.copy())
            try:
                rms=float(np.abs(indata).mean())
                l=int(rms*200); el=int(time.time()-self._t0)
                m,s=el//60,el%60
                vu="█"*min(l//4,6)+"▁"*max(6-l//4,0)
                self.after(0,lambda v=vu,mm=m,ss=s:(
                    self._vu.configure(text=v)if hasattr(self,'_vu')else None,
                    self._rt.configure(text=f"{mm}:{ss:02d}")if hasattr(self,'_rt')else None,
                ))
            except: pass
        try:
            self.ast=sd.InputStream(samplerate=self.sr,channels=1,dtype="float32",callback=cb)
            self.ast.start()
        except Exception as e:
            print(f"[REC ERROR] {e}"); self.rec=False; self._idle()

    def _stop(self):
        print(f"[STOP] ad={len(self.ad)}"); self.rec=False
        if self.ast:
            try: self.ast.stop(); self.ast.close()
            except Exception as e: print(f"[STOP AST ERROR] {e}")
            self.ast=None
        if len(self.ad)==0:
            print("[STOP] no audio"); self._idle(); return
        self._load()
        threading.Thread(target=self._tx,daemon=True).start()

    def _tx(self):
        try:
            arr=np.concatenate(self.ad,axis=0)
            buf=io.BytesIO()
            sf.write(buf,arr,self.sr,format="WAV")
            wav=buf.getvalue()
            print(f"[TX] wav_size={len(wav)}")
            r=self.srv.x(wav)
            print(f"[TX] response={r}")
            self.after(0,lambda res=r:self._rx(res))
        except Exception as e:
            print(f"[TX ERROR] {e}"); self.after(0,self._idle)

    def _rx(self,r):
        print(f"[RX] {r}")
        if "error" in r: self._idle(); return
        txt=r.get("text",""); lang=r.get("language","?")
        conf=r.get("language_probability",0)*100; dur=r.get("duration_s",0)
        if not txt.strip(): self._idle(); return
        self._res(txt,lang,conf,dur)

    def _cp(self):
        self.clipboard_clear(); self.clipboard_append(self.txt)
        self._sl.configure(text="📋 Kopiert!")
        self.after(1500,lambda:self._sl.configure(text=f"✅"))

    def _lt(self):
        ss=self.srv.tmux()
        if ss:
            self.after(0,lambda s=ss:(
                self._tv.set(s[0]), self._tb.configure(state="normal"),
                self._tb.master.winfo_children()[2].configure(values=s)
            ))

    def _send(self):
        s=self._tv.get()
        if s and self.txt and not s.startswith("("):
            self.srv.st(s,self.txt)
            self._sl.configure(text="📨 Gesendet!")
            self.after(1500,self._dismiss)

    def _dismiss(self): self.txt=""; self._idle()
    def _hc(self):
        r=self.srv.check(); print(f"[HC] {r}")

if __name__=="__main__":
    ctk.set_appearance_mode("light"); ctk.set_default_color_theme("dark-blue")
    app=V()
    try: app.mainloop()
    except: pass