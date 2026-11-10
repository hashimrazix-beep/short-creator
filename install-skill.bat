@echo off
rem Installs the /short-creator skill for Claude Code, pointing it at this folder.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$app = (Get-Location).Path; $dst = Join-Path $env:USERPROFILE '.claude\skills\short-creator';" ^
  "New-Item -ItemType Directory -Force $dst | Out-Null;" ^
  "$text = [IO.File]::ReadAllText((Join-Path $app 'skills\short-creator\SKILL.md')).Replace('{{APP_DIR}}', $app);" ^
  "[IO.File]::WriteAllText((Join-Path $dst 'SKILL.md'), $text, (New-Object Text.UTF8Encoding($false)));" ^
  "Write-Host ('Skill installed to ' + $dst + '. Start a new Claude Code session and type /short-creator <video link>')"
pause
