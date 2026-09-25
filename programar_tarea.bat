@echo off
REM Registra la tarea programada de Windows: corre TODOS los dias a las 23:59,
REM pero run_pipeline.bat internamente solo ejecuta la pipeline si ese dia es
REM el ultimo dia del mes (evita problemas de sintaxis /d LASTDAY con Windows
REM en espanol). Se corre UNA SOLA VEZ (o cuando quieras cambiar el horario).

set CARPETA=%~dp0
set TAREA=PlanoSync_VENTAS_Mensual

schtasks /create /tn "%TAREA%" /tr "\"%CARPETA%run_pipeline.bat\"" /sc DAILY /st 23:59 /f

if %ERRORLEVEL%==0 (
    echo.
    echo Tarea "%TAREA%" creada correctamente.
    echo Corre todos los dias a las 23:59, pero SOLO ejecuta la pipeline
    echo cuando ese dia es el ultimo dia del mes ^(el resto de los dias no hace nada^).
    echo Puedes verla en el Programador de tareas de Windows ^(busca "Task Scheduler"^).
) else (
    echo.
    echo Hubo un error creando la tarea. Copia el mensaje de arriba y lo revisamos juntos.
)
echo.
pause
