#!/usr/bin/env python3
"""VoiceWidget — Dynamic Island. Weiss, Rund, Apple-Style."""
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
    print(f"[AUDIO INIT ERROR] {e}"); sd=None; np=None; sf=None; HAS_AUDIO=False

# ── Farben (Apple Dynamic Island Palette) ──
BG_Window="#e8eaed"; BG_Card="#ffffff"; FG_Text="#1d1d1f"
Accent="#007aff"; Accent_Light="#60a5fa"; Record="#ff3b30"
Success="#34c34c"; Text_Second="#86868b"; Divider="#d2d2d7"
Purple="#bf5af2"; Purple_Light="#da8fff"

def mp_encode(boundary, fields, files):
    """Encode multipart/form-data. returns (Content-Type, bytes)"""
    buf=io.BytesIO()
    for k,v in fields.items():
        buf.write(b"--"+boundary+b"\r\n")
        buf.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        buf.write(v.encode()); buf.write(b"\r\n")
    for k,(fname,data,mime) in files.items():
        buf.write(b"--"+boundary+b"\r\n")
        buf.write(f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'.encode())
        buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
        buf.write(data); buf.write(b"\r\n")
    buf.write(b"--"+boundary+b"--\r\n")
    return f"multipart/form-data; boundary={boundary.decode()}", buf.getvalue()

def http_post(url, fields, files):
    """POST multipart/form-data using stdlib http.client"""
    import http.client
    boundary=b"----VW123XYZ"
    ctype,body=mp_encode(boundary,fields,files)
    p=urlparse(url)
    host=p.hostname; port=p.port or 80
    conn=http.client.HTTPConnection(host,port,timeout=120)
    conn.connect()
    conn.request("POST",p.path,body,{"Content-Type":ctype})
    resp=conn.getresponse()
    return resp.read()

class Srv:
    def check(self):
        import urllib.request
        try:
            with urllib.request.urlopen(f"{WU}/health",timeout=4)as r:return json.loads(r.read())
        except:return{"error":"x"}
    def transcribe(self,wav):
        try:
            data=http_post(f"{WU}/transcribe",{},{"file":("voice.wav",wav,"audio/wav")})
            return json.loads(data)
        except Exception as ex:return{"error":str(ex)}
    def tmux_sessions(self):
        try:
            r=subprocess.run(["ssh","-o","ConnectTimeout=3",f"{U}@{H}",
                "tmux list-sessions -F '#{session_name}' 2>/dev/null"],
                capture_output=True,text=True,timeout=8)
            return[s.strip()for s in r.stdout.split("\n")if s.strip()]
        except:return[]
    def tmux_send(self,session,text):
        try:
            safe=text.replace("'","'\"'\"'").replace("\n","\\n")
            subprocess.run(["ssh","-o","ConnectTimeout=3",f"{U}@{H}",
                f"tmux send-keys -t '{session}' '{safe}' Enter"],capture_output=True,timeout=8)
        except:pass

class Island(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.srv=Srv()
        self.rec=False; self.ad=[]; self.ast=None
        self.txt=""; self._state="idle"; self.sr=16000; self._t0=0

        # Fenster
        self.configure(fg_color=BG_Window); self.overrideredirect(True)
        self.attributes("-topmost",True,"-alpha",OP)
        sw=self.winfo_screenwidth()
        self.geometry(f"240x64+{sw//2-120}+48")
        self.bind("<Button-1>",self._down); self.bind("<B1-Motion>",self._move)
        self._dx=self._dy=0

        # Haupt-Frame — weisse Dynamic Island, voll gerundet
        self.main=ctk.CTkFrame(self,fg_color=BG_Card,corner_radius=32)
        self.main.pack(fill="both",expand=True,padx=8,pady=8)

        self._idle(); threading.Thread(target=self._healthcheck,daemon=True).start()

    def _down(self,e): self._dx,self._dy=e.x,e.y
    def _move(self,e):
        self.geometry(f"240x64+{self.winfo_x()+e.x-self._dx}+{self.winfo_y()+e.y-self._dy}")

    def _clear(self):
        for w in self.main.winfo_children(): w.destroy()

    def _resize(self,w,h):
        self.geometry(f"{w}x{h}")

    # ── IDLE ──
    def _idle(self):
        self._clear(); self._state="idle"; self._resize(240,64)
        row=ctk.CTkFrame(self.main,fg_color="transparent"); row.pack(fill="both",expand=True,padx=16,pady=0)

        # Mic-Button (lila, rund)
        mb=ctk.CTkButton(row,text="🎤",width=40,height=40,corner_radius=20,
            fg_color=Purple,hover_color=Purple_Light,text_color=BG_Card,
            font=("Segoe UI",17),command=self._toggle,border_width=0,anchor="center")
        mb.pack(side="left")

        # Voice Label
        ctk.CTkLabel(row,text="Voice",font=("SF Pro Display",15,"bold"),text_color=FG_Text).pack(side="left",padx=10)

        # Status-Leuchte (gruen)
        dot=ctk.CTkLabel(row,text="●",font=("Segoe UI",8),text_color="#34c34c")
        dot.pack(side="right")

    # ── RECORDING ──
    def _rec_ui(self):
        self._clear(); self._state="rec"; self._resize(320,64)
        row=ctk.CTkFrame(self.main,fg_color="transparent"); row.pack(fill="both",expand=True,padx=16,pady=0)

        # Stop-Button (rot, rund)
        sb=ctk.CTkButton(row,text="⏹",width=40,height=40,corner_radius=20,
            fg_color=Record,hover_color="#e02020",text_color=BG_Card,
            font=("Segoe UI",17),command=self._toggle,border_width=0)
        sb.pack(side="left")

        # Timer
        self._timer=ctk.CTkLabel(row,text="0:00",font=("SF Pro Display",15,"bold"),text_color=FG_Text)
        self._timer.pack(side="left",padx=10)

        # VU-Meter
        self._vu=ctk.CTkLabel(row,text="▁▁▁▁▁▁",font=("Segoe UI",9),text_color=Record)
        self._vu.pack(side="left",padx=4)

        # Aufnahme-Dot
        dot=ctk.CTkLabel(row,text="●",font=("Segoe UI",8),text_color=Record)
        dot.pack(side="right")

    # ── LOADING ──
    def _load_ui(self):
        self._clear(); self._state="load"; self._resize(200,64)
        row=ctk.CTkFrame(self.main,fg_color="transparent"); row.pack(fill="both",expand=True,padx=16,pady=0)
        ctk.CTkLabel(row,text="⏳",font=("Segoe UI",17),text_color=Text_Second).pack(side="left")
        ctk.CTkLabel(row,text="Transkribieren...",font=("SF Pro Display",14),text_color=Text_Second).pack(side="left",padx=8)

    # ── RESULT ──
    def _res_ui(self,text,lang,conf,dur):
        self._clear(); self._state="result"; self._resize(400,148)
        self.txt=text
        row=ctk.CTkFrame(self.main,fg_color="transparent"); row.pack(fill="both",expand=True,padx=16,pady=0)

        # Header: Status + Sprache + Dismiss
        hdr=ctk.CTkFrame(row,fg_color="transparent"); hdr.pack(fill="x",pady=(0,6))
        self._status=ctk.CTkLabel(hdr,text=f"✅  {lang.upper()}  {conf:.0f}%  ·  {dur:.1f}s",
            font=("SF Pro Display",11),text_color="#34c34c")
        self._status.pack(side="left")
        ctk.CTkButton(hdr,text="✕",width=22,height=22,corner_radius=11,
            fg_color="transparent",hover_color=Divider,text_color=Text_Second,
            font=("Segoe UI",10),command=self._dismiss).pack(side="right")

        # Text
        ctk.CTkLabel(row,text=text[:140]+("…"if len(text)>140 else""),
            font=("SF Pro Display",13),text_color=FG_Text,
            anchor="w",justify="left",wraplength=358
        ).pack(fill="x",pady=(0,10))

        # Actions Row
        acts=ctk.CTkFrame(row,fg_color="transparent"); acts.pack(fill="x")

        # Copy-Button
        ctk.CTkButton(acts,text="📋",width=38,height=38,corner_radius=19,
            fg_color=Purple,hover_color=Purple_Light,text_color=BG_Card,
            font=("Segoe UI",14),command=self._copy,border_width=0).pack(side="left",padx=(0,8))

        # Send-Button
        self._send_btn=ctk.CTkButton(acts,text="📟",width=38,height=38,corner_radius=19,
            fg_color=Accent,hover_color=Accent_Light,text_color=BG_Card,
            font=("Segoe UI",14),command=self._send,border_width=0,state="disabled")
        self._send_btn.pack(side="left",padx=(0,8))

        # Session-Waehler
        self._session_var=ctk.StringVar(value="(keine)")
        ctk.CTkOptionMenu(acts,variable=self._session_var,values=["(keine)"],
            width=130,height=38,corner_radius=19,
            fg_color=Divider,button_color=Accent,button_hover_color=Accent_Light,
            dropdown_fg_color=BG_Card,dropdown_hover_color=Accent_Light,
            text_color=FG_Text,font=("SF Pro Display",12,"bold")).pack(side="left")

        # Clipboard
        self.clipboard_clear(); self.clipboard_append(text)
        threading.Thread(target=self._load_sessions,daemon=True).start()

    def _toggle(self):
        print(f"[TOGGLE] state={self._state} rec={self.rec}")
        if self._state=="rec": self._stop()
        else: self._start()

    def _start(self):
        if not HAS_AUDIO: return
        self.rec=True; self.ad=[]; self._rec_ui(); self._t0=time.time()
        print("[START] recording...")
        def cb(indata,frames,t,status):
            if not self.rec: return
            self.ad.append(indata.copy())
            try:
                rms=float(np.abs(indata).mean())
                lvl=min(int(rms*200),24)
                vu="█"*lvl+"▁"*(24-lvl)
                el=int(time.time()-self._t0)
                m,s=el//60,el%60
                self.after(0,lambda v=vu,mm=m,ss=s:(
                    self._vu.configure(text=v) if hasattr(self,"_vu") else None,
                    self._timer.configure(text=f"{mm}:{ss:02d}") if hasattr(self,"_timer") else None,
                ))
            except Exception as e: print(f"[CB] {e}")
        try:
            self.ast=sd.InputStream(samplerate=self.sr,channels=1,dtype="float32",callback=cb)
            self.ast.start(); print("[START] stream ok")
        except Exception as e:
            print(f"[START ERROR] {e}"); self.rec=False; self._idle()

    def _stop(self):
        print(f"[STOP] ad={len(self.ad)} frames"); self.rec=False
        if self.ast:
            try: self.ast.stop(); self.ast.close()
            except Exception as e: print(f"[STOP ERR] {e}")
            self.ast=None
        total=sum(len(b)for b in self.ad)
        print(f"[STOP] total={total}")
        if total==0: print("[STOP] empty"); self._idle(); return
        self._load_ui()
        threading.Thread(target=self._transcribe,daemon=True).start()

    def _transcribe(self):
        try:
            arr=np.concatenate(self.ad,axis=0)
            buf=io.BytesIO()
            sf.write(buf,arr,self.sr,format="WAV")
            wav=buf.getvalue()
            print(f"[TX] wav={len(wav)} bytes")
            r=self.srv.transcribe(wav)
            print(f"[TX] response={r}")
            self.after(0,lambda res=r:self._show_result(res))
        except Exception as e:
            print(f"[TX FATAL] {e}"); self.after(0,self._idle)

    def _show_result(self,r):
        print(f"[RX] {r}")
        if "error" in r or "detail" in r:
            print(f"[RX] server error: {r}"); self._idle(); return
        txt=r.get("text","")
        if not txt.strip(): print("[RX] empty"); self._idle(); return
        lang=r.get("language","?"); conf=r.get("language_probability",0)*100; dur=r.get("duration_s",0)
        self._res_ui(txt,lang,conf,dur)

    def _copy(self):
        self.clipboard_clear(); self.clipboard_append(self.txt)
        self._status.configure(text="📋 Kopiert!",text_color=Purple)
        self.after(1500,lambda:self._status.configure(text=f"✅  {self._status.cget('text').split('  ',2)[-1]}",text_color="#34c34c"))

    def _load_sessions(self):
        ss=self.srv.tmux_sessions()
        if ss:
            self.after(0,lambda s=ss:(
                self._session_var.set(s[0]),
                self._send_btn.configure(state="normal"),
                # update optionmenu values
                self._send_btn.master.winfo_children()[2].configure(values=s)
            ))

    def _send(self):
        s=self._session_var.get()
        if s and self.txt and not s.startswith("("):
            self.srv.tmux_send(s,self.txt)
            self._status.configure(text="📨 Gesendet!",text_color=Accent)
            self.after(1500,self._dismiss)

    def _dismiss(self): self.txt=""; self._idle()
    def _healthcheck(self):
        r=self.srv.check(); print(f"[HC] {r}")

if __name__=="__main__":
    ctk.set_appearance_mode("light"); ctk.set_default_color_theme("blue")
    app=Island()
    try: app.mainloop()
    except: pass