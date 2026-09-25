@echo off
REM Corre la pipeline de Planos Forma vs Revit SOLO el ultimo dia de cada mes.
REM Se lanza todos los dias a las 23:59 (ver programar_tarea.bat), pero internamente
REM verifica si "manana" cae en dia 1 -- si no es el ultimo dia del mes, no hace nada.

cd /d "%~dp0"

powershell -NoProfile -Command "if ((Get-Date).AddDays(1).Day -ne 1) { exit 1 }"
if %ERRORLEVEL% NEQ 0 (
    exit /b 0
)

echo ============================================== >> plano_sync.log
echo Corrida automatica (ultimo dia del mes): %date% %time% >> plano_sync.log

python -m plano_sync run --config config.json >> plano_sync.log 2>&1

echo Fin de corrida: %date% %time% >> plano_sync.log
echo ============================================== >> plano_sync.log
