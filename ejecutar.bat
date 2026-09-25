@echo off
REM Actualiza el reporte de planos VENTAS GCP. Requiere APS_CLIENT_ID y APS_CLIENT_SECRET definidas.
cd /d "%~dp0"
python -m plano_sync run --config config.json
