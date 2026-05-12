@echo off
REM tools/ci/petalinux_build_dryrun.bat — Windows wrapper for the bash dryrun.
REM Petalinux is Linux-only; on Win this just delegates to git-bash + the .sh.
setlocal
set ROOT=%~dp0..\..
where bash >NUL 2>&1
if errorlevel 1 (
    echo [dryrun.bat] bash.exe not on PATH ^- install Git-for-Windows or run on Linux. 1>&2
    exit /b 1
)
bash "%~dp0petalinux_build_dryrun.sh" %*
exit /b %ERRORLEVEL%
