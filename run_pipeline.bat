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
if not exist Automation mkdir Automation
set PYTHONIOENCODING=utf-8
REM La salida de la tarea va a Automation\plano_tarea.log: plano_sync.log lo abre Python (FileHandler)
REM y Windows no deja que dos procesos lo tengan abierto para escribir a la vez.
set "LOG=Automation\plano_tarea.log"
echo ============================================== >> "%LOG%"
echo Corrida mensual %OBJETIVO%: %date% %time% >> "%LOG%"

python -m plano_sync run --config config.json >> "%LOG%" 2>&1

if %ERRORLEVEL% EQU 0 (
    > "%MARCADOR%" echo %OBJETIVO%
    echo Reporte mensual %OBJETIVO% generado. >> "%LOG%"
) else (
    echo ERROR: no se genero el reporte %OBJETIVO%. Se reintentara en la siguiente corrida. >> "%LOG%"
)

echo Fin de corrida: %date% %time% >> "%LOG%"
echo ============================================== >> "%LOG%"
