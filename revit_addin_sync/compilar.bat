@echo off
REM Compila SheetSync.dll (Release) y la copia a la carpeta Instalador.
cd /d "%~dp0"
dotnet build SheetSync.csproj -c Release
if errorlevel 1 (
  echo.
  echo ERROR: no compilo. No se copio nada.
  pause
  exit /b 1
)
copy /Y "bin\Release\net8.0-windows\SheetSync.dll" "Instalador\SheetSync.dll"
echo.
echo Listo: Instalador\SheetSync.dll actualizado.
pause
