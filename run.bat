@echo off
setlocal

REM UTF-8 콘솔 코드페이지로 전환합니다. run.ps1 출력은 ASCII 위주라 깨짐 가능성을 낮춥니다.
chcp 65001 > nul

REM PowerShell 실행 정책은 이 프로세스에서만 우회합니다.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"

endlocal