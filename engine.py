"""Short Creator engine: download, transcribe, pick highlights, render vertical shorts."""
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "projects"
CONFIG_PATH = ROOT / "config.json"
DEFAULT_CONFIG = {
    "port": 8765,
    "whisper_model": "base",       # tiny | base | small | medium  (bigger = slower, more accurate)
    "language": "",                # "" = auto-detect, or e.g. "en"
    "anthropic_api_key": "",       # optional: lets Claude choose the highlights
    "claude_model": "claude-sonnet-5-5",
}
OUT_W, OUT_H = 1080, 1920
FONTS = ["Arial Black", "Impact", "Segoe UI", "Bahnschrift", "Verdana", "Comic Sans MS", "Georgia"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_lock = threading.RLock()
_projects = {}
_render_pool = ThreadPoolExecutor(max_workers=2)
_whisper = {}


# ---------------------------------------------------------------- config / tools
def config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    else:
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    if not cfg.get("anthropic_api_key"):
        cfg["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    return cfg


def tool(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} was not found on PATH. Install FFmpeg and restart.")
    return path


def probe(path):
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError("This file could not be read as a video. It may be damaged or not a video file.")
    info = json.loads(out.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        raise RuntimeError("This file has no video track.")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270):
        w, h = h, w
    return {
        "duration": float(info["format"].get("duration") or v.get("duration") or 0),
        "width": w, "height": h, "vcodec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
        "has_audio": a is not None, "format": info["format"].get("format_name", ""),
    }


def run_ffmpeg(args, duration=0, on_progress=None, cwd=None):
    cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", cwd=cwd, creationflags=NO_WINDOW)
    tail = []
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                t = int(line.split("=")[1]) / 1e6
                if on_progress and duration > 0:
                    on_progress(max(0.0, min(1.0, t / duration)))
            except ValueError:
                pass
        elif "=" not in line or " " in line:
            tail.append(line)
            tail = tail[-25:]
    if proc.wait() != 0:
        raise RuntimeError("FFmpeg failed: " + " | ".join(tail)[-600:])


# ---------------------------------------------------------------- project store
def pdir(pid):
    return DATA / pid


def save(p):
    with _lock:
        d = pdir(p["id"])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "project.json.tmp"
        tmp.write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, d / "project.json")


def load_all():
    DATA.mkdir(parents=True, exist_ok=True)
    with _lock:
        for d in DATA.iterdir():
            f = d / "project.json"
            if not f.exists():
                continue
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if p.get("status") not in ("ready", "error"):
                p["status"], p["message"] = "error", "Interrupted when the app was closed. Delete and try again."
            for c in p.get("clips", []):
                if c["render"]["status"] in ("queued", "rendering"):
                    c["render"]["status"] = "none"
            _projects[p["id"]] = p
            save(p)


def list_projects():
    with _lock:
        items = sorted(_projects.values(), key=lambda p: p["created"], reverse=True)
        return [{k: p.get(k) for k in ("id", "title", "status", "progress", "message", "created", "duration")}
                | {"clips": len(p.get("clips", [])),
                   "thumb": next((c["id"] for c in p.get("clips", []) if c["render"]["status"] == "done"), None)}
                for p in items]


def get(pid):
    with _lock:
        p = _projects.get(pid)
    if not p:
        raise KeyError("No such project")
    return p


def get_clip(p, cid):
    for c in p["clips"]:
        if c["id"] == cid:
            return c
    raise KeyError("No such clip")


def transcript(pid):
    f = pdir(pid) / "transcript.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"language": "", "words": []}


def new_project(title, settings=None):
    pid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    s = {"min_len": 30, "max_len": 60, "max_clips": 0, "framing": "crop", "subtitles": True}
    s.update({k: v for k, v in (settings or {}).items() if k in s and v is not None})
    s["min_len"] = max(5, float(s["min_len"]))
    s["max_len"] = max(s["min_len"] + 1, float(s["max_len"]))
    p = {"id": pid, "title": title, "status": "queued", "progress": 0, "message": "Starting",
         "created": time.time(), "duration": 0, "width": 0, "height": 0, "has_audio": False,
         "settings": s, "clips": []}
    with _lock:
        _projects[pid] = p
    save(p)
    return p


def delete_project(pid):
    with _lock:
        _projects.pop(pid, None)
    shutil.rmtree(pdir(pid), ignore_errors=True)
    leftover = pdir(pid) / "project.json"  # a file still open elsewhere can block the delete on Windows
    if leftover.exists():
        try:
            leftover.unlink()
        except OSError:
            pass


def _status(p, status, message, progress=0.0):
    p["status"], p["message"], p["progress"] = status, message, round(progress, 3)
    if status in ("ready", "error") or progress == 0:
        save(p)


# ---------------------------------------------------------------- stage 1: get the video
def download(p, url):
    import yt_dlp
    d = pdir(p["id"])

    def hook(s):
        if s["status"] == "downloading":
            total = s.get("total_bytes") or s.get("total_bytes_estimate") or 0
            if total:
                _status(p, "downloading", "Downloading video", max(0.01, s.get("downloaded_bytes", 0) / total))

    opts = {
        "format": "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4", "outtmpl": str(d / "download.%(ext)s"), "noplaylist": True,
        "quiet": True, "no_warnings": True, "progress_hooks": [hook],
        "ffmpeg_location": str(Path(tool("ffmpeg")).parent), "windowsfilenames": True,
    }
    if shutil.which("node"):
        opts["js_runtimes"] = {"node": {}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except (TypeError, ValueError):
        opts.pop("js_runtimes", None)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    files = [f for f in d.glob("download.*") if f.suffix not in (".part", ".ytdl")]
    if not files:
        raise RuntimeError("Download produced no file.")
    if info.get("title"):
        p["title"] = info["title"]
    return max(files, key=lambda f: f.stat().st_size)


def normalize(p, raw):
    """Make sure the source is a browser-playable H.264 MP4 named source.mp4."""
    d = pdir(p["id"])
    info = probe(raw)
    dst = d / "source.mp4"
    ok = (info["vcodec"] == "h264" and info["pix_fmt"] in ("yuv420p", "yuvj420p")
          and "mp4" in info["format"] and max(info["width"], info["height"]) <= 1920)
    if ok:
        os.replace(raw, dst)
    else:
        _status(p, "preparing", "Converting video to MP4")
        args = ["-i", str(raw), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p",
                "-vf", "scale='min(1920,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)]
        run_ffmpeg(args, info["duration"], lambda f: _status(p, "preparing", "Converting video to MP4", max(0.01, f)))
        Path(raw).unlink(missing_ok=True)
        info = probe(dst)
    p.update(duration=info["duration"], width=info["width"], height=info["height"], has_audio=info["has_audio"])
    save(p)


# ---------------------------------------------------------------- stage 2: transcribe
def transcribe(p):
    d = pdir(p["id"])
    result = {"language": "", "words": []}
    if p["has_audio"]:
        cfg = config()
        _status(p, "transcribing", "Loading speech model (first run downloads it)")
        wav = d / "audio.wav"
        run_ffmpeg(["-i", str(d / "source.mp4"), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
        from faster_whisper import WhisperModel
        name = cfg["whisper_model"]
        if name not in _whisper:
            _whisper[name] = WhisperModel(name, device="cpu", compute_type="int8")
        import wave
        import numpy as np
        with wave.open(str(wav), "rb") as wf:  # decode ourselves; avoids PyAV version quirks
            audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        segs, info = _whisper[name].transcribe(audio, word_timestamps=True, vad_filter=True,
                                               language=cfg.get("language") or None)
        result["language"] = info.language
        for seg in segs:
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    result["words"].append({"s": round(w.start, 3), "e": round(w.end, 3), "w": text})
            _status(p, "transcribing", "Transcribing speech", max(0.01, min(1, seg.end / max(1, p["duration"]))))
        wav.unlink(missing_ok=True)
    (d / "transcript.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


# ---------------------------------------------------------------- stage 3: pick highlights
HOOK_STARTS = ("how ", "why ", "what ", "when ", "who ", "here's", "here is", "imagine", "did you", "do you",
               "have you", "the secret", "the truth", "the biggest", "the best", "the worst", "the first",
               "the reason", "the problem", "this is", "if you", "you ", "never ", "stop ", "let me", "so here",
               "most people", "nobody", "everyone", "one thing", "number one", "i was", "i never", "i learned")
POWER = ("secret", "mistake", "truth", "crazy", "insane", "never", "always", "best", "worst", "biggest", "money",
         "million", "billion", "important", "problem", "love", "hate", "fear", "amazing", "incredible", "shocking",
         "actually", "literally", "story", "lesson", "learned", "changed", "realized", "nobody", "everyone",
         "free", "easy", "hard", "fail", "failed", "win", "won", "lost", "die", "life", "simple", "trick", "hack")
WEAK_STARTS = ("and ", "but ", "so ", "because ", "or ", "then ", "also ", "which ", "that ", "it ", "he ",
               "she ", "they ", "this ", "those ", "these ")


def sentences_from_words(words):
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else 9
        if w["w"][-1:] in ".?!" or gap > 0.9 or len(cur) >= 45:
            sents.append({"start": cur[0]["s"], "end": cur[-1]["e"], "text": " ".join(x["w"] for x in cur),
                          "n": len(cur)})
            cur = []
    return sents


def _score(sents, i, j, lo, hi):
    first = sents[i]["text"].lower()
    body = " ".join(s["text"] for s in sents[i:j + 1]).lower()
    dur = sents[j]["end"] - sents[i]["start"]
    nwords = sum(s["n"] for s in sents[i:j + 1])
    score, why = 0.0, []
    if "?" in first:
        score += 2; why.append("opens with a question")
    if first.startswith(HOOK_STARTS) or re.match(r"^\d", first):
        score += 1.5; why.append("strong opening line")
    if first.startswith(WEAK_STARTS):
        score -= 1.5
    hits = sum(body.count(w) for w in POWER)
    score += min(2.5, hits * 0.35)
    if hits >= 3:
        why.append("emotive wording")
    wps = nwords / max(dur, 1)
    score += min(wps / 3.0, 1.0) * 2
    if wps > 2.6:
        why.append("fast, dense speech")
    score += min(1.0, (body.count("?") + body.count("!")) * 0.2)
    if sents[j]["text"][-1:] in ".?!":
        score += 1; why.append("ends on a complete sentence")
    if i > 0 and sents[i]["start"] - sents[i - 1]["end"] > 1.0:
        score += 0.5; why.append("starts after a pause")
    target = (lo + hi) / 2
    score += 0.8 * (1 - abs(dur - target) / max(target, 1))
    return score, ", ".join(why) or "steady speech"


def _claude_pick(sents, lo, hi, count, cfg):
    lines = "\n".join(f"[{i}] {s['start']:.1f}-{s['end']:.1f}s: {s['text']}" for i, s in enumerate(sents))
    prompt = (f"Below is a video transcript split into numbered sentences with timestamps. Pick the {count} best "
              f"self-contained moments for vertical short-form video (strong hook, complete thought, no missing "
              f"context). Each must run {lo:.0f}-{hi:.0f} seconds, start and end on sentence boundaries, and not "
              f"overlap. Reply with ONLY a JSON array of objects: "
              f'{{"first": <sentence index>, "last": <sentence index>, "title": "<catchy title under 60 chars>", '
              f'"reason": "<short reason>"}}.\n\n{lines}')
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": cfg["claude_model"], "max_tokens": 2000,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"x-api-key": cfg["anthropic_api_key"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.loads(r.read())["content"][0]["text"]
    picks = json.loads(text[text.index("["):text.rindex("]") + 1])
    out = []
    for k in picks:
        i, j = int(k["first"]), int(k["last"])
        if 0 <= i <= j < len(sents) and 3 <= sents[j]["end"] - sents[i]["start"] <= hi * 1.3:
            out.append((10.0, i, j, str(k.get("reason", "Chosen by Claude")), str(k.get("title", ""))[:80]))
    return out


def pick_clips(p, words):
    s = p["settings"]
    lo, hi, dur = s["min_len"], s["max_len"], p["duration"]
    count = int(s.get("max_clips") or 0) or max(1, min(12, round(dur / 60)))
    spans = []  # (start, end, title, score, reason)
    sents = sentences_from_words(words)
    if dur <= max(lo * 1.2, hi):
        spans.append((0, dur, p["title"], 0, "Whole video (already short enough)"))
    elif len(sents) >= 2:
        chosen = []
        cfg = config()
        if cfg.get("anthropic_api_key"):
            try:
                _status(p, "picking", "Claude is choosing the best moments", 0.3)
                chosen = _claude_pick(sents, lo, hi, count, cfg)
            except Exception as e:
                print("Claude pick failed, using local scoring:", e)
        if not chosen:
            cands = []
            for i in range(len(sents)):
                for j in range(i, len(sents)):
                    d = sents[j]["end"] - sents[i]["start"]
                    if d > hi:
                        break
                    if d >= lo:
                        sc, why = _score(sents, i, j, lo, hi)
                        cands.append((sc, i, j, why, ""))
            cands.sort(reverse=True)
            for c in cands:
                if len(chosen) >= count:
                    break
                if all(c[2] < o[1] or c[1] > o[2] for o in chosen):
                    chosen.append(c)
        for sc, i, j, why, title in chosen:
            title = title or sents[i]["text"].strip()
            if len(title) > 60:
                title = title[:57].rsplit(" ", 1)[0] + "..."
            spans.append((max(0, sents[i]["start"] - 0.15), min(dur, sents[j]["end"] + 0.3), title, sc, why))
    if not spans:  # no usable speech: even splits
        target = min(dur, hi, max(lo, (lo + hi) / 2))
        n = max(1, min(count, int(dur // target)))
        gap = (dur - n * target) / (n + 1)
        for k in range(n):
            st = gap * (k + 1) + target * k
            spans.append((st, st + target, f"{p['title']} - part {k + 1}", 0, "Even split (no speech detected)"))
    spans.sort()
    p["clips"] = []
    for st, en, title, sc, why in spans:
        c = default_clip(st, en, title, s["framing"], sc, why)
        c["subtitles"]["enabled"] = bool(s.get("subtitles", True))
        c["captions"] = build_captions(words, c["start"], c["end"], c["subtitles"]["words_per"])
        p["clips"].append(c)
    save(p)


# ---------------------------------------------------------------- clips
def default_clip(start, end, title, framing="crop", score=0.0, reason=""):
    return {
        "id": uuid.uuid4().hex[:8], "title": title, "start": round(start, 2), "end": round(end, 2),
        "score": round(score, 2), "reason": reason,
        "framing": framing, "pan_x": 0.5, "pan_y": 0.5, "zoom": 1.0, "speed": 1.0, "volume": 1.0,
        "subtitles": {"enabled": True, "font": "Arial Black", "size": 84, "color": "#FFFFFF",
                      "highlight": "#FFE600", "highlight_on": True, "outline": 7, "pos_y": 70,
                      "uppercase": True, "words_per": 3},
        "title_overlay": {"enabled": False, "text": title, "size": 64, "color": "#FFFFFF", "pos_y": 12,
                          "duration": 0},
        "captions": [], "captions_edited": False,
        "render": {"status": "none", "progress": 0, "file": None, "stale": True, "error": ""},
    }


def build_captions(words, start, end, words_per=3):
    sel = [w for w in words if start - 0.05 <= (w["s"] + w["e"]) / 2 <= end + 0.05]
    caps, cur = [], []
    for i, w in enumerate(sel):
        cur.append(w)
        gap = sel[i + 1]["s"] - w["e"] if i + 1 < len(sel) else 9
        chars = sum(len(x["w"]) + 1 for x in cur)
        if len(cur) >= words_per or gap > 0.6 or w["w"][-1:] in ".?!" or chars > 26:
            caps.append({"start": round(max(start, cur[0]["s"]), 3), "end": round(min(end, cur[-1]["e"]), 3),
                         "text": " ".join(x["w"] for x in cur),
                         "words": [{"s": x["s"], "e": x["e"], "w": x["w"]} for x in cur]})
            cur = []
    for a, b in zip(caps, caps[1:]):  # close tiny gaps so captions do not flicker
        if 0 < b["start"] - a["end"] < 0.35:
            a["end"] = b["start"]
    return [c for c in caps if c["end"] > c["start"]]


def _merge(dst, patch, allowed):
    for k, v in patch.items():
        if k in allowed:
            dst[k] = v


def update_clip(pid, cid, patch):
    p = get(pid)
    if not isinstance(patch, dict):
        raise ValueError("Expected an object of clip settings")
    with _lock:
        live = get_clip(p, cid)
        c = json.loads(json.dumps(live))  # edit a copy so a bad value cannot leave the clip half-changed
        c["render"] = live["render"]
        before = (c["start"], c["end"], c["subtitles"]["words_per"])
        _merge(c, patch, ("title", "start", "end", "framing", "pan_x", "pan_y", "zoom", "speed", "volume"))
        if isinstance(patch.get("subtitles"), dict):
            _merge(c["subtitles"], patch["subtitles"], c["subtitles"].keys())
        if isinstance(patch.get("title_overlay"), dict):
            _merge(c["title_overlay"], patch["title_overlay"], c["title_overlay"].keys())
        c["start"] = round(max(0.0, min(float(c["start"]), p["duration"] - 0.5)), 2)
        c["end"] = round(max(c["start"] + 0.5, min(float(c["end"]), p["duration"])), 2)
        c["speed"] = max(0.5, min(2.0, float(c["speed"])))
        c["volume"] = max(0.0, min(3.0, float(c["volume"])))
        c["zoom"] = max(1.0, min(3.0, float(c["zoom"])))
        c["pan_x"] = max(0.0, min(1.0, float(c["pan_x"])))
        c["pan_y"] = max(0.0, min(1.0, float(c["pan_y"])))
        if c["framing"] not in ("crop", "blur", "fit"):
            c["framing"] = "crop"
        c["title"] = str(c["title"])[:200]
        sub, ttl = c["subtitles"], c["title_overlay"]
        if sub["font"] not in FONTS:
            sub["font"] = "Arial Black"
        sub["words_per"] = max(1, min(8, int(sub["words_per"])))
        sub["size"] = max(20, min(240, int(float(sub["size"]))))
        sub["outline"] = max(0.0, min(20.0, float(sub["outline"])))
        sub["pos_y"] = max(0.0, min(100.0, float(sub["pos_y"])))
        ttl["size"] = max(20, min(240, int(float(ttl["size"]))))
        ttl["pos_y"] = max(0.0, min(100.0, float(ttl["pos_y"])))
        ttl["duration"] = max(0.0, float(ttl["duration"] or 0))
        ttl["text"] = str(ttl["text"])
        for owner, key in ((sub, "color"), (sub, "highlight"), (ttl, "color")):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(owner[key])):
                raise ValueError(f"{key} must be a colour like #FFE600")
        for owner, key in ((sub, "enabled"), (sub, "highlight_on"), (sub, "uppercase"), (ttl, "enabled")):
            owner[key] = bool(owner[key])
        if isinstance(patch.get("captions"), list):
            c["captions"] = [_clean_caption(x) for x in patch["captions"] if str(x.get("text", "")).strip()]
            c["captions_edited"] = True
        if patch.get("captions_edited") is False:
            c["captions_edited"] = False
        after = (c["start"], c["end"], c["subtitles"]["words_per"])
        if not c["captions_edited"] and (before != after or patch.get("captions_edited") is False):
            c["captions"] = build_captions(transcript(pid)["words"], c["start"], c["end"],
                                           c["subtitles"]["words_per"])
        c["render"]["stale"] = True
        p["clips"][p["clips"].index(live)] = c
        save(p)
        return c


def _clean_caption(x):
    cap = {"start": round(float(x["start"]), 3), "end": round(float(x["end"]), 3), "text": str(x["text"]).strip()}
    if cap["end"] <= cap["start"]:
        cap["end"] = cap["start"] + 0.5
    ws = x.get("words")
    if isinstance(ws, list) and len(ws) == len(cap["text"].split()):
        cap["words"] = [{"s": float(w["s"]), "e": float(w["e"]), "w": t} for w, t in zip(ws, cap["text"].split())]
    return cap


def add_clip(pid, start, end, title=None):
    p = get(pid)
    with _lock:
        start = max(0.0, float(start))
        end = min(p["duration"], float(end))
        if end - start < 0.5:
            raise ValueError("Clip is too short")
        c = default_clip(start, end, title or f"Clip {len(p['clips']) + 1}", p["settings"]["framing"], 0, "Added manually")
        c["captions"] = build_captions(transcript(pid)["words"], c["start"], c["end"], c["subtitles"]["words_per"])
        p["clips"].append(c)
        save(p)
        return c


def delete_clip(pid, cid):
    p = get(pid)
    with _lock:
        p["clips"] = [c for c in p["clips"] if c["id"] != cid]
        save(p)
    for ext in ("mp4", "ass", "jpg"):
        (pdir(pid) / "clips" / f"{cid}.{ext}").unlink(missing_ok=True)


# ---------------------------------------------------------------- subtitles (ASS)
def _ass_color(hex_color):
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_text(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def caption_words(cap):
    """Per-word timings for a caption; interpolated by length when the text was hand-edited."""
    toks = cap["text"].split()
    ws = cap.get("words")
    if ws and len(ws) == len(toks):
        return [{"s": w["s"], "e": w["e"], "w": t} for w, t in zip(ws, toks)]
    total = sum(len(t) + 1 for t in toks) or 1
    out, t0 = [], cap["start"]
    for t in toks:
        d = (cap["end"] - cap["start"]) * (len(t) + 1) / total
        out.append({"s": t0, "e": t0 + d, "w": t})
        t0 += d
    return out


def build_ass(c):
    sub, ttl = c["subtitles"], c["title_overlay"]
    speed = c["speed"]
    dur = (c["end"] - c["start"]) / speed
    rel = lambda t: max(0.0, min(dur, (t - c["start"]) / speed))
    font = sub["font"] if sub["font"] in FONTS else "Arial Black"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{int(sub['size'])},{_ass_color(sub['color'])},&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{float(sub['outline'])},2,5,70,70,0,1
Style: Title,{font},{int(ttl['size'])},{_ass_color(ttl['color'])},&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,6,2,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if ttl["enabled"] and ttl["text"].strip():
        end = dur if not ttl["duration"] else min(dur, float(ttl["duration"]))
        pos = f"{{\\an5\\pos({OUT_W // 2},{int(OUT_H * ttl['pos_y'] / 100)})}}"
        ev.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(end)},Title,,0,0,0,,{pos}{_ass_text(ttl['text'])}")
    if sub["enabled"]:
        pos = f"{{\\an5\\pos({OUT_W // 2},{int(OUT_H * sub['pos_y'] / 100)})}}"
        up = (lambda s: s.upper()) if sub["uppercase"] else (lambda s: s)
        base, hi = _ass_color(sub["color"]), _ass_color(sub["highlight"])
        for cap in c["captions"]:
            a, b = rel(cap["start"]), rel(cap["end"])
            if b - a < 0.02:
                continue
            ws = caption_words(cap)
            if not sub["highlight_on"] or len(ws) < 1:
                ev.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Cap,,0,0,0,,{pos}{_ass_text(up(cap['text']))}")
                continue
            for i, w in enumerate(ws):
                t0 = a if i == 0 else rel(w["s"])
                t1 = b if i == len(ws) - 1 else rel(ws[i + 1]["s"])
                if t1 - t0 < 0.01:
                    continue
                parts = [(f"{{\\c{hi}&}}{_ass_text(up(x['w']))}{{\\c{base}&}}" if k == i else _ass_text(up(x["w"])))
                         for k, x in enumerate(ws)]
                ev.append(f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},Cap,,0,0,0,,{pos}{' '.join(parts)}")
    return head + "\n".join(ev) + "\n"


# ---------------------------------------------------------------- rendering
def _video_filter(c):
    px, py, z = c["pan_x"], c["pan_y"], c["zoom"]
    zw, zh = int(round(OUT_W * z / 2)) * 2, int(round(OUT_H * z / 2)) * 2
    cover = (f"scale={zw}:{zh}:force_original_aspect_ratio=increase:force_divisible_by=2,"
             f"crop={OUT_W}:{OUT_H}:(iw-{OUT_W})*{px:.4f}:(ih-{OUT_H})*{py:.4f}")
    if c["framing"] == "blur":
        g = (f"[0:v]split[b0][f0];[b0]scale={OUT_W // 4}:{OUT_H // 4}:force_original_aspect_ratio=increase,"
             f"crop={OUT_W // 4}:{OUT_H // 4},boxblur=12:2,scale={OUT_W}:{OUT_H},eq=brightness=-0.08[bg];"
             f"[f0]scale={zw}:{zh}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
    elif c["framing"] == "fit":
        g = (f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
             f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black[base]")
    else:
        g = f"[0:v]{cover}[base]"
    return g + f";[base]setpts=PTS/{c['speed']:.4f},fps=30,setsar=1,ass='{c['id']}.ass',format=yuv420p[v]"


def render_clip(pid, cid):
    p = get(pid)
    c = get_clip(p, cid)
    r = c["render"]
    try:
        r.update(status="rendering", progress=0, error="")
        out_dir = pdir(pid) / "clips"
        out_dir.mkdir(exist_ok=True)
        snap = json.loads(json.dumps(c))
        (out_dir / f"{cid}.ass").write_text(build_ass(snap), encoding="utf-8")
        length = snap["end"] - snap["start"]
        fc = _video_filter(snap)
        args = ["-ss", f"{snap['start']:.3f}", "-t", f"{length:.3f}", "-i", "../source.mp4"]
        maps = ["-map", "[v]"]
        if p["has_audio"]:
            fc += f";[0:a:0]atempo={snap['speed']:.4f},volume={snap['volume']:.3f}[a]"
            maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        tmp = f"{cid}.tmp.mp4"
        args += ["-filter_complex", fc] + maps + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                                   "-movflags", "+faststart", tmp]
        run_ffmpeg(args, length / snap["speed"], lambda f: r.update(progress=round(f, 3)), cwd=str(out_dir))
        os.replace(out_dir / tmp, out_dir / f"{cid}.mp4")
        try:
            run_ffmpeg(["-ss", f"{min(1.0, length / snap['speed'] / 2):.2f}", "-i", f"{cid}.mp4", "-frames:v", "1",
                        "-vf", "scale=360:-2", "-q:v", "4", f"{cid}.jpg"], cwd=str(out_dir))
        except Exception:
            pass
        cur = next((x for x in p["clips"] if x["id"] == cid), None)  # the clip may have been edited meanwhile
        same = cur is not None and all(snap[k] == cur[k] for k in snap if k != "render")
        r.update(status="done", progress=1, file=f"clips/{cid}.mp4", stale=not same, version=int(time.time()))
    except Exception as e:
        traceback.print_exc()
        r.update(status="error", error=str(e)[-400:])
    save(p)


def queue_render(pid, cid):
    p = get(pid)
    c = get_clip(p, cid)
    if c["render"]["status"] in ("queued", "rendering"):
        return c
    c["render"].update(status="queued", progress=0, error="")
    _render_pool.submit(render_clip, pid, cid)
    return c


def queue_all(pid, only_stale=False):
    for c in get(pid)["clips"]:
        if not only_stale or c["render"]["stale"] or c["render"]["status"] != "done":
            queue_render(pid, c["id"])


# ---------------------------------------------------------------- pipeline
def run_pipeline(pid, url=None, raw=None):
    p = get(pid)
    try:
        if url:
            _status(p, "downloading", "Downloading video")
            raw = download(p, url)
        _status(p, "preparing", "Checking video")
        normalize(p, raw)
        words = transcribe(p)["words"]
        _status(p, "picking", "Finding the best moments", 0.5)
        pick_clips(p, words)
        _status(p, "ready", f"{len(p['clips'])} shorts found")
        queue_all(pid)
    except Exception as e:
        traceback.print_exc()
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
        if url and type(e).__module__.startswith("yt_dlp"):
            msg = ("Could not download a video from this link. Check that it opens in your browser and is public "
                   "(private, age-restricted and region-locked videos cannot be downloaded). Details: "
                   + msg.replace("ERROR: ", "")[:240])
        _status(p, "error", msg[-500:] or "Something went wrong")


def start_pipeline(pid, url=None, raw=None):
    threading.Thread(target=run_pipeline, args=(pid,), kwargs={"url": url, "raw": raw}, daemon=True).start()


def repick(pid, settings):
    """Re-run highlight picking with new length / count settings (keeps the transcript)."""
    p = get(pid)
    for k in ("min_len", "max_len", "max_clips", "framing", "subtitles"):
        if settings.get(k) is not None:
            p["settings"][k] = settings[k]
    p["settings"]["min_len"] = max(5, float(p["settings"]["min_len"]))
    p["settings"]["max_len"] = max(p["settings"]["min_len"] + 1, float(p["settings"]["max_len"]))
    for c in list(p["clips"]):
        delete_clip(pid, c["id"])
    pick_clips(p, transcript(pid)["words"])
    _status(p, "ready", f"{len(p['clips'])} shorts found")
    queue_all(pid)
    return p
