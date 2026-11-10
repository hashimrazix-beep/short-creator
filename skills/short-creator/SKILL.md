---
name: short-creator
description: Open the Short Creator app and turn a video into vertical 9:16 shorts. Use when the user types /short-creator, pastes a video link (YouTube, TikTok, Vimeo, X, ...) or a local video file and asks for shorts, reels or clips, or asks to edit, re-subtitle, trim or re-render shorts made by Short Creator.
---

# Short Creator

Short Creator is a local app installed at `{{APP_DIR}}`. It downloads or imports a video, transcribes it,
picks the best moments, and renders subtitled 1080x1920 shorts. You drive it with its command-line client.

All commands below run from `{{APP_DIR}}` with its own Python:

```
cd "{{APP_DIR}}"; .venv\Scripts\python cli.py <command>
```

## 1. Make sure the app is running

Check: `curl -s http://127.0.0.1:8765/api/meta` (any JSON reply means it is running).

If it is not running, start it in its own window, then wait a few seconds and check again (the very first
start installs the Python packages and can take a few minutes):

```
Start-Process "{{APP_DIR}}\run.bat"
```

`run.bat` also opens the app in the user's browser at http://localhost:8765. If the app was already running and
the user asked to "open" it, open that address for them (`Start-Process "http://localhost:8765"`).

## 2. Create shorts from the link or file

Arguments after `/short-creator` are the video link (or a file path), optionally followed by a length range and a
count. If no link or file was given, just open the app and ask for the link.

```
.venv\Scripts\python cli.py new "<url-or-file>" [min-max seconds] [count]
```

- Defaults: 30-60 second shorts, automatic count. Pass e.g. `15-30 5` only if the user asked for it.
- The command prints the project id. Then wait for processing and rendering (run this in the background for
  long videos; transcription is on CPU and can take a while):

```
.venv\Scripts\python cli.py wait <project>
```

`wait` prints each short's clip id, time range, title and output file. If it reports a failure, show the
message to the user (private, age-restricted or region-locked links cannot be downloaded).

## 3. Report back

Tell the user how many shorts were made, list their titles, and give the link
`http://localhost:8765/#/p/<project>` where they can preview, edit and download them (single files or a zip).
The rendered files are in `{{APP_DIR}}\data\projects\<project>\clips\`.

## Editing shorts on request

Read `{{APP_DIR}}\CLAUDE.md` for the full list of commands and clip settings. In short:

```
cli.py list                                  projects
cli.py show <project>                        clips and settings
cli.py transcript <project> [from] [to]      timestamped transcript, to find moments by what is said
cli.py add <project> <start> <end> [title]   cut a new short by hand
cli.py set <project> <clip> key=value ...    e.g. start=12.5 framing=blur subtitles.size=96 title_overlay.enabled=true
cli.py captions <project> <clip> file.json   replace caption text
cli.py render <project> [clip]               render the changed shorts and wait
```

Edits are not re-encoded until `render`. Never edit `project.json` by hand while the app is running.
