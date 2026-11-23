import os,uuid,shutil,subprocess,json,re,socket,ipaddress,urllib.parse,urllib.request
from pathlib import Path
from typing import Optional
from fastapi import FastAPI,UploadFile,File,Form,HTTPException,BackgroundTasks
from fastapi.responses import HTMLResponse,FileResponse
D=Path(os.getenv("DATA_DIR","./data")); U=D/"uploads"; O=D/"outputs"
U.mkdir(parents=True,exist_ok=True); O.mkdir(parents=True,exist_ok=True)
app=FastAPI(title="CinematicFlow"); jobs={}
def run(a):
 p=subprocess.run(a,capture_output=True,text=True)
 if p.returncode: raise RuntimeError((p.stderr or "Media processing error")[-1000:])
 return p.stdout
def safe(u):
 x=urllib.parse.urlparse(u or "")
 if x.scheme!="https" or not x.hostname or x.username or x.password: raise ValueError("Use a direct HTTPS video-file URL.")
 for r in socket.getaddrinfo(x.hostname,None):
  if not ipaddress.ip_address(r[4][0]).is_global: raise ValueError("Private URLs are blocked.")
 return u
def download(u,path):
 with urllib.request.urlopen(urllib.request.Request(safe(u),headers={"User-Agent":"CinematicFlow"}),timeout=45) as r:
  safe(r.geturl()); n=0
  with open(path,"wb") as f:
   while b:=r.read(1024*1024):
    n+=len(b)
    if n>1_000_000_000: raise ValueError("Maximum video size is 1 GB.")
    f.write(b)
def work(jid,src,ratio,count,lo,hi):
 j=jobs[jid]; j.update(status="processing",progress=5,message="Checking video…")
 try:
  duration=float(json.loads(run(["ffprobe","-v","error","-show_entries","format=duration","-of","json",str(src)]))["format"]["duration"])
  if duration<8: raise ValueError("Video must be at least 8 seconds.")
  j.update(progress=15,message="AI transcription with Whisper…")
  from faster_whisper import WhisperModel
  model=WhisperModel(os.getenv("WHISPER_MODEL","tiny"),device="cpu",compute_type="int8")
  segs,_=model.transcribe(str(src),vad_filter=True)
  rows=[(float(s.start),float(s.end),s.text.strip()) for s in segs]
  j.update(progress=45,message="Finding highlights…")
  hooks=("secret","mistake","never","best","worst","why","how","truth","shocking","amazing","important","actually","because","imagine","finally","top")
  cand=[]
  for a,b,t in rows:
   a=max(0,a-2); b=min(duration,max(b+4,a+lo),a+hi)
   score=2+sum(1.4 for w in hooks if re.search(r"\\b"+w+r"\\b",t.lower()))+min(len(t)/100,2)+(1 if "?" in t or "!" in t else 0)
   cand.append((score,a,b,t))
  if not cand: cand=[(1,0,min(duration,hi),"")]
  cand.sort(reverse=True); chosen=[]
  for x in cand:
   if all(x[2]<=y[1] or x[1]>=y[2] for y in chosen): chosen.append(x)
   if len(chosen)>=count: break
  chosen.sort(key=lambda x:x[1]); folder=O/jid; folder.mkdir(exist_ok=True)
  dims={"9:16":"1080:1920","1:1":"1080:1080","4:5":"1080:1350","16:9":"1920:1080"}; w,h=dims[ratio].split(":"); clips=[]
  for i,(_,a,b,t) in enumerate(chosen,1):
   name=f"clip-{i}.mp4"; out=folder/name; vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
   run(["ffmpeg","-y","-ss",str(a),"-i",str(src),"-t",str(b-a),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(out)])
   clips.append({"name":name,"url":f"/media/{jid}/{name}","start":round(a,1),"end":round(b,1),"highlight":t[:150]})
   j["progress"]=60+int(38*i/max(1,len(chosen)))
  j.update(status="completed",progress=100,message="Your clips are ready.",clips=clips)
 except Exception as e: j.update(status="failed",progress=0,message=str(e)[:900])
@app.get("/",response_class=HTMLResponse)
def home(): return PAGE
@app.get("/health")
def health(): return {"status":"ok"}
@app.post("/api/jobs")
async def create(background_tasks:BackgroundTasks,video:Optional[UploadFile]=File(None),url:Optional[str]=Form(None),ratio:str=Form("9:16"),count:int=Form(3),min_len:int=Form(20),max_len:int=Form(60)):
 if not video and not url: raise HTTPException(400,"Upload a video or paste a URL.")
 if ratio not in ("9:16","1:1","4:5","16:9") or not 1<=count<=5 or not 10<=min_len<=90 or not min_len<=max_len<=180: raise HTTPException(400,"Invalid settings.")
 jid=uuid.uuid4().hex[:12]; src=U/(jid+".mp4")
 try:
  if video:
   n=0
   with open(src,"wb") as f:
    while b:=await video.read(1024*1024):
     n+=len(b)
     if n>1_000_000_000: raise ValueError("Maximum upload size is 1 GB.")
     f.write(b)
  else: download(url,src)
  run(["ffprobe","-v","error","-show_entries","format=duration","-of","json",str(src)])
  jobs[jid]={"id":jid,"status":"queued","progress":0,"message":"Queued","clips":[]}
  background_tasks.add_task(work,jid,src,ratio,count,min_len,max_len); return jobs[jid]
 except Exception as e:
  src.unlink(missing_ok=True); raise HTTPException(400,str(e))
@app.get("/api/jobs/{jid}")
def status(jid):
 if jid not in jobs: raise HTTPException(404,"Job not found")
 return jobs[jid]
@app.get("/media/{jid}/{name}")
def media(jid,name):
 f=O/jid/Path(name).name
 if not f.is_file(): raise HTTPException(404,"Not found")
 return FileResponse(f,media_type="video/mp4",filename=f.name)
PAGE=r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CinematicFlow</title><style>
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 15% 0%,#30234b,transparent 36%),#090a10;color:#f8f8fc;font:15px system-ui}.wrap{max-width:1000px;margin:auto;padding:28px 20px}.brand{font-size:23px;font-weight:850}.brand span{color:#e879f9}.hero{text-align:center;padding:65px 0 35px}.tag{color:#dba4ff;letter-spacing:2px;font-size:12px;font-weight:bold}.hero h1{font-size:clamp(40px,7vw,68px);line-height:1.05;letter-spacing:-3px}.hero em{font-style:normal;background:linear-gradient(90deg,#e879f9,#8b9cff);background-clip:text;color:transparent}.hero p,.note{color:#999caf;line-height:1.7}.panel{max-width:800px;margin:auto;padding:24px;border:1px solid #37394d;border-radius:22px;background:#151724;box-shadow:0 25px 90px #0008}.tabs{display:flex;gap:8px;margin-bottom:18px}button,.tab{cursor:pointer}.tab{padding:11px 16px;background:#202231;border:1px solid #303347;color:#ddd;border-radius:10px}.active{background:#392647;border-color:#9254a7}.drop{display:block;padding:32px;text-align:center;border:1px dashed #666987;border-radius:15px;background:#0d0f18;cursor:pointer}.drop strong{display:block;margin:10px}input[type=file]{display:none}.url,select{width:100%;padding:14px;background:#0d0f18;border:1px solid #303347;border-radius:10px;color:white}.settings{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0}.field label{display:block;color:#999caf;font-size:12px;margin-bottom:8px}.go{width:100%;padding:16px;border:0;border-radius:12px;background:linear-gradient(90deg,#a855f7,#6366f1);color:white;font-weight:800}.status{display:none;margin-top:18px;padding:16px;background:#0d0f18;border-radius:12px}.bar{height:7px;background:#333;border-radius:9px;margin:12px 0}.bar i{display:block;height:100%;background:linear-gradient(90deg,#e879f9,#818cf8);width:0}.clips{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.clip{padding:10px;background:#171927;border-radius:12px}.clip video{width:100%}.clip a{color:#e3a8ff}.note{font-size:12px}.features{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:36px auto}.features div{padding:18px;border:1px solid #2c2f40;border-radius:14px;background:#12141d}.features p{color:#999caf;font-size:13px}@media(max-width:600px){.settings,.features{grid-template-columns:1fr}.hero h1{letter-spacing:-1px}.panel{padding:15px}}</style></head><body><div class="wrap"><div class="brand">Cinematic<span>Flow</span> ✦</div><header class="hero"><div class="tag">AI VIDEO CLIP MAKER</div><h1>Your best moments.<br><em>Automatically clipped.</em></h1><p>Upload a video, let AI find compelling moments, and create ready-to-share clips.</p></header><section class="panel"><div class="tabs"><button class="tab active" id="ut" onclick="mode('u')">⬆ Upload video</button><button class="tab" id="rt" onclick="mode('r')">↗ Import URL</button></div><form id="form"><div id="up"><label class="drop" for="v">☁️<strong id="fn">Drop your video or browse files</strong><small>MP4, MOV, MKV · max 1 GB</small></label><input id="v" type="file" accept="video/*"></div><div id="rp" style="display:none"><input id="url" class="url" type="url" placeholder="https://example.com/video.mp4"><p class="note">Direct HTTPS video-file URLs only; watch-page links may not work.</p></div><div class="settings"><div class="field"><label>Aspect ratio</label><select id="ratio"><option>9:16</option><option>1:1</option><option>4:5</option><option>16:9</option></select></div><div class="field"><label>Number of clips</label><select id="count"><option>3</option><option>1</option><option>2</option><option>4</option><option>5</option></select></div><div class="field"><label>Clip length</label><select id="len"><option value="20,60">20–60 seconds</option><option value="15,30">15–30 seconds</option><option value="30,90">30–90 seconds</option><option value="10,20">10–20 seconds</option></select></div></div><button class="go" id="go">✦ Generate AI clips</button></form><div class="status" id="s"><b id="st">Processing…</b><div class="bar"><i id="bar"></i></div><div class="note" id="msg"></div><div class="clips" id="clips"></div></div><p class="note">Upload only videos you own or are allowed to process. Current MVP uses centered crops; face tracking and saved project history are not included.</p></section><section class="features"><div>✦ <b>AI highlights</b><p>Whisper transcription helps find interesting speech and hooks.</p></div><div>▣ <b>Social formats</b><p>Vertical, square, portrait and landscape MP4s.</p></div><div>⇩ <b>Downloads</b><p>Preview and download your generated clips.</p></div></section></div><script>
let m="u";function mode(x){m=x;up.style.display=x==="u"?"block":"none";rp.style.display=x==="r"?"block":"none";ut.classList.toggle("active",x==="u");rt.classList.toggle("active",x==="r")}v.onchange=e=>fn.textContent=e.target.files[0]?.name||"Browse video";form.onsubmit=async e=>{e.preventDefault();let d=new FormData();if(m==="u"){if(!v.files[0])return alert("Choose a video.");d.append("video",v.files[0])}else{if(!url.value)return alert("Paste a video URL.");d.append("url",url.value)}d.append("ratio",ratio.value);d.append("count",count.value);let [a,b]=len.value.split(",");d.append("min_len",a);d.append("max_len",b);go.disabled=true;go.textContent="Working…";s.style.display="block";clips.innerHTML="";try{let r=await fetch("/api/jobs",{method:"POST",body:d}),j=await r.json();if(!r.ok)throw Error(j.detail);poll(j.id)}catch(x){msg.textContent=x.message;go.disabled=false;go.textContent="Generate AI clips"}};async function poll(id){try{let j=await(await fetch("/api/jobs/"+id)).json();st.textContent=j.status==="completed"?"Your clips are ready!":j.status==="failed"?"Processing failed":"Creating your clips…";bar.style.width=(j.progress||0)+"%";msg.textContent=j.message;if(j.status==="completed"){clips.innerHTML=j.clips.map(c=>`<div class="clip"><video controls playsinline src="${c.url}"></video><b>${c.name}</b><p class="note">${c.start}s – ${c.end}s</p><a href="${c.url}" download>Download MP4 ↓</a></div>`).join("");go.disabled=false;go.textContent="Generate more clips"}else if(j.status==="failed"){go.disabled=false;go.textContent="Try again"}else setTimeout(()=>poll(id),2500)}catch(e){msg.textContent=e.message;go.disabled=false}}</script></body></html>"""
