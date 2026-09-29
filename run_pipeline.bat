@echo off
setlocal
REM Corre la pipeline de Planos Forma vs Revit una vez por mes.
REM La tarea corre todos los dias a las 23:59 y, si la PC estaba apagada, en cuanto se enciende.
REM periodo_pendiente.ps1 decide si hay un mes sin generar:
REM   - el ultimo dia del mes genera el mes actual;
REM   - si ese dia no corrio, lo genera el siguiente dia que corra la tarea.
REM Para generarlo en cualquier otro momento: ejecutar.bat

cd /d "%~dp0"
set "MARCADOR=%~dp0cache\ultima_corrida_mensual.txt"
set "OBJETIVO="

for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0periodo_pendiente.ps1" -Marcador "%MARCADOR%"`) do set "OBJETIVO=%%T"

if not defined OBJETIVO exit /b 0

if not exist cache mkdir cache
echo ============================================== >> plano_sync.log
echo Corrida mensual %OBJETIVO%: %date% %time% >> plano_sync.log

python -m plano_sync run --config config.json >> plano_sync.log 2>&1

if %ERRORLEVEL% EQU 0 (
    > "%MARCADOR%" echo %OBJETIVO%
    echo Reporte mensual %OBJETIVO% generado. >> plano_sync.log
) else (
    echo ERROR: no se genero el reporte %OBJETIVO%. Se reintentara en la siguiente corrida. >> plano_sync.log
)

echo Fin de corrida: %date% %time% >> plano_sync.log
echo ============================================== >> plano_sync.log
