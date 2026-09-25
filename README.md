# PLANOS_VENTAS — Planos Forma vs Revit · VENTAS GCP

Compara por **número y nombre** los planos publicados en Forma (proyecto ACC «VENTAS GCP») contra las **hojas de los modelos Revit** del mismo proyecto.
No usa Speckle ni Power BI: lee todo por las APIs de Autodesk y genera un HTML autónomo con el estilo del reporte «Planos Forma vs Revit» del portal.

```
ACC Data Management API ─► archivos de Forma (PDF) + modelos .rvt + quién subió cada versión ─┐
ACC Model Derivative API ─► hojas de cada .rvt                                                ├─► comparar ─► reporte/index.html
Equipos e integrantes - VENTAS.xlsx ─► equipo / integrante                                   ─┘             reporte/comparativa.xlsx
```

## Reglas aplicadas (las mismas del flujo anterior)
- **Formato:** solo PDF (`file_rules` en `config.json`; cámbialo para incluir DWG).
- **Número y nombre** se extraen del nombre del archivo (`A-101 - Planta baja.pdf`) con la misma lógica de `fxSepararPlano`.
- **Disciplina** por la ruta (códigos `01101_`… o palabras clave).
- **Comparación** dentro de cada proyecto, normalizando mayúsculas/acentos/puntuación: Exacta · Solo número · Solo nombre · Sin coincidencia.
- Un proyecto **sin ningún modelo Revit** no se marca «sin coincidencia»: sus planos quedan como **Sin modelo Revit** y no cuentan en los porcentajes.

## Clasificaciones nuevas
- **Proyecto** = carpeta de primer nivel dentro de `Project Files` (equivale a `ResolveRoot` de *DimProyectoConcurso*). Los modelos `.rvt` se comparan solo con los planos de su mismo proyecto.
- **Alcance de exploración** = dentro de cada carpeta de proyecto, **solo** se recorre la subcarpeta `011_WIP` (config `subcarpeta_datos`); no se toca ningún otro nivel ni archivos sueltos en la raíz del proyecto. Un proyecto que no tenga esa subcarpeta se omite por completo y queda registrado como aviso en el reporte.
- **Integrante / Equipo** = responsable del **modelo Revit** que hizo match con el plano, **no** quien subió el PDF a Forma. Se toma el campo `Version added by` del `.rvt` (config `integrante_campo_revit`, valor `added_by`; alternativa `updated_by` = `Updated by`) y se cruza con la hoja `Integrantes` de *Equipos e integrantes - VENTAS.xlsx* (misma normalización que *EquiposIntegrantesVENTAS*; además unifica ñ/n y prueba coincidencia parcial cuando el nombre en ACC trae palabras de más). Sin modelo Revit que haga match, o sin coincidencia del autor del modelo en la lista, el plano queda como «Sin integrante asignado» (no se fuerza ninguna coincidencia).

## Puesta en marcha (una vez)
1. Python 3.10+ y `pip install -r requirements.txt`.
2. En https://aps.autodesk.com/myapps crea una app y habilita *Data Management* y *Model Derivative*. Guarda `Client ID` y `Client Secret`.
3. En ACC → *Account Admin → Custom Integrations* agrega el `Client ID` y actívala en el proyecto VENTAS GCP. Sin esto la API responde 403.
4. Credenciales (no van en el JSON): `setx APS_CLIENT_ID "..."` y `setx APS_CLIENT_SECRET "..."` (abre una terminal nueva después).
5. Revisa `config.json` (ver «Supuestos a validar»).

## Uso
```
python tests\test_parsing.py                 # pruebas de la lógica
python -m plano_sync demo --out demo         # reporte con datos SINTÉTICOS (ya incluido en demo\)
python -m plano_sync probe -n 3              # imprime hojas crudas de 3 modelos: valida el formato de nombre de hoja
ejecutar.bat                                 # corrida real -> reporte\index.html
programar_tarea.bat                          # actualización automática diaria 06:00
```
Para publicarlo en el portal, copia `reporte\index.html` donde publican los demás reportes.

## Supuestos a validar (no pude probarlos contra tu cuenta de ACC)
1. **IDs de cuenta y proyecto** en `config.json` los tomé de la consulta `DimProyectoConcurso` de ISSUES_VENTAS (`Account` y `Project` de *Project Extracts*). Confirma que el GUID de proyecto corresponde a «VENTAS GCP».
2. **Nombre de las hojas Revit:** se leen las vistas 2D del modelo traducido y se separan con `sheet_view_regex` (`NÚMERO - NOMBRE`). Corre `probe` y ajusta la regex si sale distinto.
3. **Traducción de modelos:** si un `.rvt` nunca se tradujo, la primera corrida la lanza y espera hasta 10 min; si no termina, queda como aviso y se reintenta en la siguiente. Los resultados se guardan en `cache\`.
4. **Autor del modelo (integrante):** se toma de `Version added by` (`createUserName` de la versión más reciente del `.rvt`; cámbialo a `updated_by` en `integrante_campo_revit` si prefieres `Updated by`). Se calcula **una vez por modelo** y se propaga a todas las hojas/planos que hagan match con ese modelo — nunca se usa quién subió el PDF a Forma. Verifica en una corrida que los nombres coincidan con los de la lista de integrantes (la tabla «Clasificación por integrante» muestra cuántos quedaron sin asignar).
5. `.rvt` de respaldo (`*.0001.rvt`) se excluyen (`revit.excluir_regex`).
6. **Carpeta `011_WIP`:** solo se exploran los archivos (Revit y Forma) dentro de esa subcarpeta de cada proyecto (`subcarpeta_datos` en `config.json`). Si algún proyecto guarda sus archivos en otro nombre de subcarpeta, ajusta ese valor o corre `probe` para confirmar la estructura real.
7. **Hojas de trabajo/borrador:** antes de comparar, se descarta cualquier vista cuyo nombre CRUDO (el que trae el modelo, antes de separar número y nombre) coincida con `revit.excluir_hojas_regex` en `config.json`. Por defecto excluye sufijos/prefijos como `_TRABAJO`, `_WIP`, `_BORRADOR`, `_DRAFT`, `_INTERNO`, `_NO PUBLICAR`, o vistas que empiecen con `WIP -`, `TRABAJO -`, `BORRADOR -`, `X -`. Corre `probe` para ver los nombres reales y ajusta la lista si tu equipo usa otra convención; el reporte avisa cuántas hojas se excluyeron por esta regla.

## Alcance: qué demuestra y qué no
El reporte compara **nombres**: dice si existe una hoja en Revit con ese número/nombre. **No prueba** que el PDF se generó en Revit (un PDF de CAD con el mismo nombre saldría como coincidencia). Existe una verificación opcional por metadatos del PDF (`"verificar_origen": true`, módulo `origin.py`), pero es solo un indicio y hay que calibrar sus firmas con PDF de origen conocido.
