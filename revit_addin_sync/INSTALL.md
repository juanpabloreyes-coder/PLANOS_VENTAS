# SheetSync — add-in local (sin costo de API)

Sustituye, para los modelos donde este instalado, el metodo de Model Derivative/Design
Automation por uno que no consume Cloud Credits: cada vez que alguien hace **Sync to Central**
con exito, este add-in escribe localmente un `.json` con las hojas del modelo en ese momento,
dentro de una carpeta que vive en el mismo repositorio de ACC Docs (`PLANOS_VENTAS\RevitSheetLog\`)
y por lo tanto se sincroniza sola a todos los equipos via Desktop Connector, igual que ya pasa
con `RevitSyncLog` en `PUBLICACIONES_VENTAS`.

El pipeline (`python -m plano_sync run`) revisa primero esta carpeta; si un modelo no tiene
`.json` ahi (porque nadie con el add-in instalado lo ha sincronizado todavia), sigue usando el
metodo actual (Model Derivative / Design Automation) automaticamente -- el reporte no cambia,
solo deja de costar en los modelos que ya tengan el add-in.

## 1. Compilar (una sola vez, en una maquina con Visual Studio + Revit)

Igual que `revit_plugin/SheetExporter` (ver ese `build_and_deploy.md` si quieres mas detalle del
proceso general): abre `SheetSync.csproj`, ajusta el `HintPath` de `RevitAPI`/`RevitAPIUI` si tu
Revit esta en otra ruta, compila en **Release**. Debe generarse
`bin\Release\net8.0-windows\SheetSync.dll`.

## 2. Instalar en CADA equipo que sincroniza modelos

En cada maquina de cada integrante que trabaje con los modelos Revit del proyecto:

1. Copia `SheetSync.dll` y `SheetSync.addin` a:
   ```
   %AppData%\Autodesk\Revit\Addins\2025\
   ```
   (crea la carpeta `2025` si no existe; ajusta el numero si usan otra version de Revit).

2. En esa misma carpeta, crea un archivo de texto `sheetsync-config.txt` con **una sola linea**:
   la ruta a la carpeta `RevitSheetLog` dentro de `PLANOS_VENTAS` en ACC Docs, por ejemplo:
   ```
   C:\Users\<usuario>\DC\ACCDocs\GCPEASA\GCP_TRANSFORMACIÓN_DIGITAL\Project Files\01_IMPLEMENTACIÓN_BIM\0112_SQDCM\011211_VENTAS\PLANOS_VENTAS\RevitSheetLog
   ```
   (la ruta cambia solo el nombre de usuario de Windows en cada equipo; el resto es igual).

3. Reinicia Revit. No hace falta hacer nada mas -- el add-in trabaja solo, en silencio, cada vez
   que alguien sincroniza con exito. Si algo falla (carpeta no accesible, etc.) simplemente no
   escribe nada y Revit sigue funcionando normal; nunca interrumpe el sync.

## 3. Del lado del pipeline (Python)

En `config.json`, agrega (junto a `design_automation`, si ya lo tienes):

```json
"revit": {
  "...": "...(tus claves existentes de revit se mantienen igual)",
  "carpeta_log_local": "RevitSheetLog"
}
```

Es una ruta relativa a la carpeta del proyecto (`PLANOS_VENTAS/RevitSheetLog`) -- el mismo
`run_pipeline.bat` ya corre con `cd /d` a esa carpeta, asi que no hace falta ruta absoluta. Si la
dejas sin configurar, el pipeline sigue exactamente como esta ahora (sin usar el add-in).

## Notas

- La primera vez que alguien sincroniza un modelo *despues* de instalar el add-in en su equipo,
  aparece el `.json` de ese modelo y el pipeline empieza a usarlo automaticamente en la siguiente
  corrida -- no hay que reiniciar ni tocar nada del lado de Python.
- Si un modelo nunca se sincroniza desde una maquina con el add-in instalado, el pipeline sigue
  usando Model Derivative/Design Automation para ese modelo especificamente, como hasta ahora.
- Instalar esto en todos los equipos del equipo de Revit es lo que eventualmente deja el pipeline
  sin ningun costo de APS -- no es necesario hacerlo de golpe, se puede ir instalando poco a poco.
