@echo off
REM hw/vivado/scripts/setup_ip_repo.bat -- Windows backup for setup_ip_repo.sh.
REM Fetches Digilent vivado-library under hw/vivado/ip_repo/digilent/.
REM
REM Note: hw/vivado/ip_repo/digilent/.gitignore ignores vivado-library/ to keep
REM hand-unzipped releases out of the index. The -f flag below is intentional.

setlocal
for /f "delims=" %%i in ('git rev-parse --show-toplevel') do set REPO_ROOT=%%i
set DEST_REL=hw/vivado/ip_repo/digilent/vivado-library
set DEST=%REPO_ROOT%\hw\vivado\ip_repo\digilent\vivado-library
set URL=https://github.com/Digilent/vivado-library.git

if exist "%DEST%\.git" (
    echo [setup_ip_repo] vivado-library already present -- updating submodule
    git -C "%REPO_ROOT%" submodule update --init --recursive -- "%DEST_REL%"
    goto :done
)
if exist "%DEST%" (
    echo [setup_ip_repo] vivado-library exists but is not a git submodule
    echo                 ^(probably an unzipped release^). Leaving as-is.
    goto :done
)

echo [setup_ip_repo] adding vivado-library as a submodule under %DEST_REL%
git -C "%REPO_ROOT%" submodule add -f %URL% %DEST_REL%
if errorlevel 1 (
    echo.
    echo Retry manually if network failed:
    echo   git -C %REPO_ROOT% submodule add -f %URL% %DEST_REL%
    exit /b 1
)

:done
echo [setup_ip_repo] OK -- Digilent IP repo at %DEST%
endlocal
