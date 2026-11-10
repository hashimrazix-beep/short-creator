@echo off
rem Installs the /short-creator skill for Claude Code, pointing it at this folder.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$app = (Get-Location).Path; $dst = Join-Path $env:USERPROFILE '.claude\skills\short-creator';" ^
  "New-Item -ItemType Directory -Force $dst | Out-Null;" ^
  "(Get-Content 'skills\short-creator\SKILL.md' -Raw).Replace('{{APP_DIR}}', $app) | Set-Content (Join-Path $dst 'SKILL.md') -Encoding utf8;" ^
  "Write-Host ('Skill installed to ' + $dst + '. Start a new Claude Code session and type /short-creator <video link>')"
pause
