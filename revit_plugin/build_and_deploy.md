# SheetExporter — compilar y desplegar (una sola vez)

Esto resuelve el problema de los modelos con vínculos faltantes: en vez de traducir el modelo
en la nube (Model Derivative), corre el motor real de Revit sin interfaz gráfica (Design
Automation) y lee las hojas directamente con la API de Revit — eso no necesita resolver
vínculos externos, así que no le afecta.

Una vez hecho este proceso, el pipeline en Python lo usa automáticamente para cualquier modelo
que la traducción normal no pueda resolver. No hay que repetirlo salvo que cambies el código del
plugin.

## Qué necesitas

- Una máquina con **Visual Studio 2022** (Community es suficiente) y **Revit 2025** instalado
  (para tener `RevitAPI.dll` / `RevitAPIUI.dll` disponibles). No tiene que ser tu máquina
  principal de trabajo.
- El mismo `APS_CLIENT_ID` / `APS_CLIENT_SECRET` que ya configuraste (los mismos de siempre).

## 1. Compilar el plugin

1. Abre `SheetExporter.csproj` con Visual Studio (`Archivo → Abrir → Proyecto/Solución`).
2. Si tu Revit está en otra ruta, ajusta el `HintPath` de `RevitAPI`/`RevitAPIUI` dentro del
   `.csproj`.
3. Si Visual Studio marca en rojo el paquete `Autodesk.Forge.DesignAutomation.Revit`: abre el
   Administrador de paquetes NuGet, busca "Design Automation" y toma el paquete que aparezca
   para Revit (el nombre exacto varía un poco entre versiones de Visual Studio/NuGet); actualiza
   el `.csproj` con el nombre correcto si difiere.
4. Compila en modo **Release** (`Compilar → Compilar solución`, o `dotnet build -c Release`).
5. Debe generarse `bin\Release\net8.0-windows\SheetExporter.dll`.

## 2. Armar el AppBundle (el .zip que se sube a Autodesk)

1. Copia `SheetExporter.dll`, `DesignAutomationBridge.dll` (queda junto al .dll al compilar) y
   `SheetExporter.addin` dentro de `SheetExporter.bundle\Contents\` (los tres juntos, ahí sí,
   como en una instalación normal de "ApplicationPlugin" de Revit).
2. La carpeta `SheetExporter.bundle\` debe quedar así:
   ```
   SheetExporter.bundle\
     PackageContents.xml
     Contents\
       SheetExporter.dll
       DesignAutomationBridge.dll
       SheetExporter.addin
   ```
3. En `PackageContents.xml`, el `ComponentEntry` debe apuntar al **`.addin`**, no al `.dll`:
   ```xml
   <ComponentEntry ... ModuleName="./Contents/SheetExporter.addin" ... />
   ```
   Esto es lo que de verdad hace que `revitcoreconsole.exe` (el motor headless de Design
   Automation) encuentre y cargue el plugin. Un `ModuleName` apuntando al `.dll` en vez del
   `.addin` produce errores confusos como `System.IO.FileNotFoundException: Could not find
   .addin in AppBundle` o `System.IO.DirectoryNotFoundException: Could not find *.bundle in
   AppBundle`, sin importar en qué carpeta muevas el `.addin` — el problema nunca fue la
   ubicación del archivo, sino esta referencia.
4. Comprime la carpeta `SheetExporter.bundle` **completa** en un `.zip`, de modo que el `.zip`
   contenga la carpeta `SheetExporter.bundle\` en su raíz (no solo su contenido suelto). Esta
   es la convención oficial de Autodesk para AppBundles:
   ```
   SheetExporter.bundle.zip
     SheetExporter.bundle\
       PackageContents.xml
       Contents\
         SheetExporter.dll
         DesignAutomationBridge.dll
         SheetExporter.addin
   ```

## 3. Publicarlo en Autodesk (Design Automation)

Desde tu máquina con Python configurado (la misma de siempre, con `APS_CLIENT_ID`/
`APS_CLIENT_SECRET` ya guardados), agrega esto a `config.json`:

```json
"design_automation": {
  "nickname": "planosventas",
  "activity": "SheetExporterActivity",
  "engine": "Autodesk.Revit+2025",
  "bucket": "planosventas-da-bucket"
}
```

(`nickname` y `bucket` los puedes cambiar por el texto que quieras, en minúsculas y sin
espacios — son solo identificadores tuyos dentro de Autodesk.)

Luego corre:
```
python -m plano_sync publicar_plugin --zip "ruta\al\SheetExporter.bundle.zip"
```

Esto sube el AppBundle y crea la Activity en Autodesk (una sola vez). Si todo sale bien, no
necesitas volver a correrlo — el pipeline normal (`python -m plano_sync run`) ya puede usarlo
automáticamente para los modelos que lo necesiten.

## Notas

- Este proceso puede fallar la primera vez por detalles finos de la API de Design Automation
  (nombres exactos de parámetros, versión del engine disponible, etc.) — es normal, es una API
  que no habíamos usado antes y no la hemos podido probar en vivo desde aquí. Si algo falla,
  copia el error completo y lo ajustamos juntos.
- El motor de Revit en la nube que usa Design Automation tiene un costo por minuto de Autodesk
  (fuera de tu suscripción normal de Revit) — revisa el pricing de APS Design Automation si vas
  a correrlo sobre muchos modelos seguido.
