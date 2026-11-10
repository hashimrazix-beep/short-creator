"""Command-line control for Short Creator (talks to the running app). Meant for Claude and scripts.

  python cli.py list                               all projects
  python cli.py new <url-or-file> [min-max] [n]    create shorts from a link or a local video file
  python cli.py show <project>                     project + clips (captions shortened)
  python cli.py clip <project> <clip>              one clip in full, including captions
  python cli.py transcript <project> [from] [to]   transcript words with timestamps (seconds)
  python cli.py set <project> <clip> key=value ... edit a clip, e.g. start=12.5 subtitles.size=96 framing=blur
  python cli.py captions <project> <clip> <file>   replace captions from a JSON file [{start,end,text}, ...]
  python cli.py add <project> <start> <end> [title]
  python cli.py delete <project> <clip>
  python cli.py render <project> [clip]            render one clip, or every changed clip
  python cli.py wait <project>                     block until processing and rendering finish
"""
import json
import mimetypes
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import engine

BASE = f"http://127.0.0.1:{engine.config()['port']}/api"


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Error {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError:
        sys.exit("Short Creator is not running. Start it with run.bat first.")


def upload(path, settings):
    f = Path(path)
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"settings\"\r\n\r\n{json.dumps(settings)}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{f.name}\"\r\n"
            f"Content-Type: {mimetypes.guess_type(f.name)[0] or 'video/mp4'}\r\n\r\n").encode()
    body = head + f.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/projects/upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.loads(r.read())


def parse_value(v):
    try:
        return json.loads(v)
    except ValueError:
        return v


def out(x):
    print(json.dumps(x, indent=1, ensure_ascii=False))


def main(a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd = a[0]
    if cmd == "list":
        out(call("/projects"))
    elif cmd == "new":
        s = {}
        if len(a) > 2:
            lo, hi = a[2].split("-")
            s.update(min_len=float(lo), max_len=float(hi))
        if len(a) > 3:
            s["max_clips"] = int(a[3])
        p = call("/projects/url", "POST", {"url": a[1], "settings": s}) if a[1].startswith("http") else upload(a[1], s)
        print(p["id"])
    elif cmd == "show":
        p = call(f"/projects/{a[1]}")
        for c in p["clips"]:
            c["captions"] = f"<{len(c['captions'])} captions; use `clip` to see them>"
        out(p)
    elif cmd == "clip":
        p = call(f"/projects/{a[1]}")
        out(next(c for c in p["clips"] if c["id"] == a[2]))
    elif cmd == "transcript":
        t = call(f"/projects/{a[1]}/transcript")
        lo = float(a[2]) if len(a) > 2 else 0
        hi = float(a[3]) if len(a) > 3 else 1e9
        line, start = [], None
        for w in t["words"]:
            if not lo <= w["s"] <= hi:
                continue
            start = w["s"] if start is None else start
            line.append(w["w"])
            if w["w"][-1:] in ".?!" or len(line) >= 30:
                print(f"[{start:8.2f} - {w['e']:8.2f}] {' '.join(line)}")
                line, start = [], None
        if line:
            print(f"[{start:8.2f}] {' '.join(line)}")
    elif cmd == "set":
        patch = {}
        for kv in a[3:]:
            k, v = kv.split("=", 1)
            node = patch
            *parents, last = k.split(".")
            for part in parents:
                node = node.setdefault(part, {})
            node[last] = parse_value(v)
        c = call(f"/projects/{a[1]}/clips/{a[2]}", "PUT", patch)
        c["captions"] = f"<{len(c['captions'])} captions>"
        out(c)
    elif cmd == "captions":
        caps = json.loads(Path(a[3]).read_text(encoding="utf-8"))
        c = call(f"/projects/{a[1]}/clips/{a[2]}", "PUT", {"captions": caps})
        print(f"{len(c['captions'])} captions saved")
    elif cmd == "add":
        out(call(f"/projects/{a[1]}/clips", "POST", {"start": float(a[2]), "end": float(a[3]),
                                                     "title": a[4] if len(a) > 4 else None}))
    elif cmd == "delete":
        out(call(f"/projects/{a[1]}/clips/{a[2]}", "DELETE"))
    elif cmd == "render":
        if len(a) > 2:
            call(f"/projects/{a[1]}/clips/{a[2]}/render", "POST")
        else:
            call(f"/projects/{a[1]}/render", "POST", {"only_stale": True})
        main(["wait", a[1]])
    elif cmd == "wait":
        while True:
            p = call(f"/projects/{a[1]}")
            busy = [c for c in p["clips"] if c["render"]["status"] in ("queued", "rendering")]
            if p["status"] == "error":
                sys.exit("Failed: " + p["message"])
            if p["status"] == "ready" and not busy:
                break
            time.sleep(2)
        for n, c in enumerate(p["clips"], 1):
            r = c["render"]
            print(f"{n:2d}. {c['id']}  {c['start']:7.1f}-{c['end']:7.1f}  {r['status']:5s} "
                  f"{engine.pdir(p['id']) / r['file'] if r.get('file') else r.get('error', '')}  | {c['title']}")
    else:
        sys.exit("Unknown command. Run: python cli.py help")


if __name__ == "__main__":
    main(sys.argv[1:])
