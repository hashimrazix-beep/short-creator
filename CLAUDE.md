# Short Creator

Local web app that turns a video link or uploaded file into vertical 9:16 shorts, with a built-in editor.

- Start: double-click `run.bat` (opens http://localhost:8765). From Claude Code, use the `short-creator`
  entry in `.claude/launch.json`.
- Needs Python 3.10+ and FFmpeg on PATH. Python packages live in `.venv` (see `requirements.txt`).

## Layout

| File | Purpose |
| --- | --- |
| `engine.py` | Whole pipeline: download (yt-dlp), normalise to H.264 MP4, transcribe (faster-whisper, CPU), pick highlights, build ASS subtitles, render with FFmpeg |
| `server.py` | FastAPI routes under `/api`, serves `static/` and `/media` (project files) |
| `static/` | Vanilla JS front end: home, project grid, clip editor (`app.js`) |
| `cli.py` | Command-line client for the running app - use this to edit videos for the user |
| `config.json` (created on first run) | `whisper_model` (tiny/base/small/medium), `language`, `port`, optional `anthropic_api_key` (Claude picks highlights) |
| `data/projects/<id>/` | `source.mp4`, `transcript.json`, `project.json`, `clips/<clip>.mp4` |

## Editing videos for the user (Claude)

The app must be running. Never edit `project.json` by hand while it runs (the server holds it in memory);
go through `cli.py`, which calls the API. Run it with `.venv\Scripts\python cli.py ...`.

```
cli.py list                                   projects
cli.py new <url-or-file> [min-max] [count]    make shorts, prints the project id
cli.py wait <project>                         wait for processing and renders; prints clip ids and output files
cli.py show <project>                         all clips and their settings
cli.py transcript <project> [from] [to]       timestamped transcript, to find moments by what is said
cli.py add <project> <start> <end> [title]    cut a new short by hand (seconds in the source)
cli.py set <project> <clip> key=value ...     edit a clip
cli.py clip <project> <clip>                  one clip in full, including captions
cli.py captions <project> <clip> file.json    replace captions: [{"start": s, "end": s, "text": "..."}] (source seconds)
cli.py render <project> [clip]                render one clip, or every changed clip, and wait
```

Clip keys for `set` (all times are seconds in the source video):

- `title`, `start`, `end`, `speed` (0.5-2), `volume` (0-3)
- `framing` = `crop` | `blur` | `fit`; `zoom` (1-3); `pan_x`, `pan_y` (0-1, 0.5 = centre)
- `subtitles.enabled`, `.font` (see `engine.FONTS`), `.size`, `.color`, `.highlight`, `.highlight_on`,
  `.outline`, `.pos_y` (percent from top), `.uppercase`, `.words_per`
- `title_overlay.enabled`, `.text`, `.size`, `.color`, `.pos_y`, `.duration` (0 = whole short)
- `captions_edited=false` discards hand-edited caption text and rebuilds from the transcript

Edits mark the clip stale; nothing is re-encoded until `render`. Output is 1080x1920, 30 fps, H.264/AAC.

## Notes

- Highlight picking is local scoring in `engine._score` (hooks, emotive words, speech density, clean sentence
  ends). With an Anthropic key in `config.json` it asks Claude instead and falls back to local scoring on error.
- Subtitles are burned in from a generated `.ass` file; the editor preview imitates it in the browser
  (`FS` table in `app.js` maps libass font sizing to CSS).
