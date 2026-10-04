@echo off
title Quitar SheetSync (PLANOS_VENTAS)

set "ADDIN_DIR=%AppData%\Autodesk\Revit\Addins\2025"

echo.
echo  Quitando SheetSync...
echo.

del /F /Q "%ADDIN_DIR%\SheetSync.dll" 2>nul
del /F /Q "%ADDIN_DIR%\SheetSync.addin" 2>nul
del /F /Q "%ADDIN_DIR%\sheetsync-config.txt" 2>nul
del /F /Q "%ADDIN_DIR%\SheetSync.pdb" 2>nul

echo  Listo, SheetSync ya no se cargara la proxima vez que abras Revit.
echo.
pause
