"""Short Creator web server. Start with run.bat (or: .venv\\Scripts\\python server.py)."""
import re
import shutil
import threading
import webbrowser
import zipfile
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import engine

app = FastAPI(title="Short Creator")
STATIC = Path(__file__).parent / "static"


@app.exception_handler(KeyError)
async def not_found(_, exc):
    return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)


@app.exception_handler(ValueError)
async def bad_request(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def safe_name(s):
    return (re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s).strip()[:80] or "short").rstrip(". ")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/meta")
def meta():
    cfg = engine.config()
    return {"fonts": engine.FONTS, "whisper_model": cfg["whisper_model"], "claude": bool(cfg["anthropic_api_key"])}


@app.get("/api/projects")
def projects():
    return engine.list_projects()


@app.post("/api/projects/url")
def create_from_url(body: dict = Body(...)):
    url = str(body.get("url", "")).strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "Paste a full video link starting with http:// or https://")
    p = engine.new_project(url, body.get("settings"))
    engine.start_pipeline(p["id"], url=url)
    return p


@app.post("/api/projects/upload")
def create_from_upload(file: UploadFile = File(...), settings: str = Form("{}")):
    import json
    name = Path(file.filename or "video.mp4").name
    p = engine.new_project(Path(name).stem, json.loads(settings or "{}"))
    d = engine.pdir(p["id"])
    raw = d / ("upload" + (Path(name).suffix.lower() or ".mp4"))
    with open(raw, "wb") as f:
        shutil.copyfileobj(file.file, f, 1024 * 1024)
    engine.start_pipeline(p["id"], raw=raw)
    return p


@app.get("/api/projects/{pid}")
def project(pid: str):
    return engine.get(pid)


@app.delete("/api/projects/{pid}")
def project_delete(pid: str):
    engine.delete_project(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/transcript")
def project_transcript(pid: str):
    engine.get(pid)
    return engine.transcript(pid)


@app.post("/api/projects/{pid}/repick")
def project_repick(pid: str, body: dict = Body(default={})):
    if engine.get(pid)["status"] != "ready":
        raise HTTPException(400, "Project is still processing")
    return engine.repick(pid, body)


@app.post("/api/projects/{pid}/clips")
def clip_add(pid: str, body: dict = Body(...)):
    if "start" not in body or "end" not in body:
        raise HTTPException(400, "start and end (seconds) are required")
    return engine.add_clip(pid, body["start"], body["end"], body.get("title"))


@app.put("/api/projects/{pid}/clips/{cid}")
def clip_update(pid: str, cid: str, body: dict = Body(...)):
    return engine.update_clip(pid, cid, body)


@app.delete("/api/projects/{pid}/clips/{cid}")
def clip_delete(pid: str, cid: str):
    engine.delete_clip(pid, cid)
    return {"ok": True}


@app.post("/api/projects/{pid}/clips/{cid}/render")
def clip_render(pid: str, cid: str):
    return engine.queue_render(pid, cid)


@app.post("/api/projects/{pid}/render")
def render_all(pid: str, body: dict = Body(default={})):
    engine.queue_all(pid, only_stale=bool(body.get("only_stale")))
    return engine.get(pid)


@app.get("/api/projects/{pid}/clips/{cid}/download")
def clip_download(pid: str, cid: str):
    p = engine.get(pid)
    c = engine.get_clip(p, cid)
    f = engine.pdir(pid) / "clips" / f"{cid}.mp4"
    if not f.exists():
        raise HTTPException(404, "This short has not been rendered yet")
    n = p["clips"].index(c) + 1
    return FileResponse(f, media_type="video/mp4", filename=f"{n:02d} - {safe_name(c['title'])}.mp4")


@app.get("/api/projects/{pid}/download")
def project_download(pid: str):
    p = engine.get(pid)
    z = engine.pdir(pid) / "shorts.zip"
    count = 0
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for n, c in enumerate(p["clips"], 1):
            f = engine.pdir(pid) / "clips" / f"{c['id']}.mp4"
            if f.exists():
                zf.write(f, f"{n:02d} - {safe_name(c['title'])}.mp4")
                count += 1
    if not count:
        raise HTTPException(404, "No rendered shorts yet")
    return FileResponse(z, media_type="application/zip", filename=f"{safe_name(p['title'])} - shorts.zip")


engine.load_all()
app.mount("/media", StaticFiles(directory=engine.DATA), name="media")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import sys
    import socket
    port = engine.config()["port"]
    with socket.socket() as s:  # already running? just open it instead of failing on the busy port
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(f"Short Creator is already running at http://localhost:{port}")
            if "--no-browser" not in sys.argv:
                webbrowser.open(f"http://localhost:{port}")
            sys.exit(0)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print(f"\n  Short Creator is running:  http://localhost:{port}\n  Close this window to stop it.\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
