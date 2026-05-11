@echo off
REM hw/vivado/scripts/cleanup_ip_repo.bat -- Windows backup for cleanup_ip_repo.sh.
REM Usage:
REM   cleanup_ip_repo.bat           soft cleanup (workdir only)
REM   cleanup_ip_repo.bat --hard    also drop submodule + .git/modules entry

setlocal
for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set REPO_ROOT=%%i
set SUBPATH=hw/vivado/ip_repo/digilent/vivado-library
set DEST=%REPO_ROOT%\hw\vivado\ip_repo\digilent\vivado-library

if /i "%1"=="--hard" goto :hard

if not exist "%DEST%" (
    echo [cleanup_ip_repo] nothing to clean ^(no %SUBPATH%^)
    goto :done
)
echo [cleanup_ip_repo] soft cleanup -- removing %SUBPATH% workdir only
rmdir /s /q "%DEST%"
echo [cleanup_ip_repo] re-run setup_ip_repo.bat to restore
goto :done

:hard
echo [cleanup_ip_repo] hard cleanup -- removing submodule registration
git -C "%REPO_ROOT%" ls-files --error-unmatch "%SUBPATH%" >nul 2>&1
if not errorlevel 1 (
    git -C "%REPO_ROOT%" submodule deinit -f -- "%SUBPATH%"
    git -C "%REPO_ROOT%" rm -rf "%SUBPATH%"
)
if exist "%DEST%" rmdir /s /q "%DEST%"
if exist "%REPO_ROOT%\.git\modules\%SUBPATH:/=\%" rmdir /s /q "%REPO_ROOT%\.git\modules\%SUBPATH:/=\%"
echo [cleanup_ip_repo] hard cleanup done -- review 'git status' and commit if intended

:done
endlocal
