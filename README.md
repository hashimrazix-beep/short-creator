# Short Creator

Turn any video into vertical shorts on your own PC. Paste a link or upload a file; the app finds the best
moments, crops them to 9:16, burns in word-highlighted subtitles, and gives you MP4s to download. It includes a
built-in editor and a Claude Code skill so Claude can make and edit shorts for you.

Everything runs locally and free: no account, no API key, no GPU needed.

## Features

- **Link or upload** - YouTube, TikTok, Vimeo, X and anything else [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  supports, or any local video file.
- **Automatic highlights** - speech is transcribed with Whisper on your CPU, then moments are scored for strong
  openings, emotive wording, pace and clean sentence endings.
- **Vertical output** - 1080x1920, 30 fps, H.264/AAC. Crop to fill, blurred background, or black bars.
- **Editor** - trim with draggable handles, zoom and pan, speed, volume, subtitle font / size / colours /
  position, editable caption text, title overlay, live preview.
- **Download** - each short on its own, or all of them as a zip.
- **Claude can drive it** - `cli.py` and the `/short-creator` skill.

## Requirements

- Windows 10/11 (the launcher is a `.bat` file; the Python code itself is cross-platform)
- [Python 3.10+](https://www.python.org/downloads/) on PATH
- [FFmpeg](https://ffmpeg.org/download.html) on PATH (`winget install Gyan.FFmpeg`)
- [Node.js](https://nodejs.org/) is recommended; yt-dlp uses it for YouTube links

## Install and run

```
git clone https://github.com/hashimrazix-beep/short-creator.git
cd short-creator
run.bat
```

The first run creates a virtual environment and installs the packages (a few minutes), then opens
http://localhost:8765. The first video also downloads the Whisper speech model (about 150 MB).

## Use it from Claude Code

Run `install-skill.bat` once. It copies the skill into `%USERPROFILE%\.claude\skills\short-creator` and points
it at this folder. Then, in a new Claude Code session:

```
/short-creator https://www.youtube.com/watch?v=...
/short-creator https://... 15-30 5      (five shorts of 15-30 seconds)
```

Claude starts the app if needed, imports the video, makes the shorts, and replies with a link to preview, edit
and download them. You can also ask for edits in plain words, e.g. "make the subtitles bigger on short 2".
See [CLAUDE.md](CLAUDE.md) for the commands Claude uses.

## Settings

`config.json` is created on first run:

| Key | Meaning |
| --- | --- |
| `whisper_model` | `tiny`, `base` (default), `small`, `medium` - bigger is slower and more accurate |
| `language` | empty = auto-detect, or a code such as `en` |
| `port` | default `8765` |
| `anthropic_api_key` | optional; if set, Claude chooses the highlights instead of the local scoring |

`config.json` and your videos (`data/`) are git-ignored and never leave your machine.

## Please use responsibly

Only download and re-publish videos you own or have permission to use, and follow the terms of the site the
video comes from.

## License

MIT - see [LICENSE](LICENSE).
