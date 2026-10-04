"""Obtiene de ACC (APS) los planos de Forma y las hojas de los modelos Revit del proyecto VENTAS GCP.

Clasificacion por PROYECTO = carpeta de primer nivel dentro de 'Project Files'
(equivale a ResolveRoot de DimProyectoConcurso: sube por la jerarquia hasta la raiz del sistema
y se queda con la carpeta inmediatamente debajo de ella).
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from .aps import APS, split_sheet_view_name, DEFAULT_SHEET_REGEX
from .integrantes import Clasificador, SIN_INTEGRANTE
from .parsing import separar_plano, disciplina_por_ruta, disciplina_por_carpeta_wip, extension_permitida

log = logging.getLogger("plano_sync.collect")
SIN_PROYECTO = "(Raíz de Project Files)"


class Cache:
    def __init__(self, d, nombre):
        self.p = Path(d) / nombre
        self.p.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.d = json.loads(self.p.read_text(encoding="utf-8"))
        except Exception:
            self.d = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v):
        self.d[k] = v

    def save(self):
        self.p.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")


def _raiz(aps, hub, pid, nombres):
    tops = aps.top_folders(hub, pid)
    for t in tops:
        if t["name"].strip().lower() in [n.lower() for n in nombres]:
            return t
    raise ValueError(f"No encontre la carpeta raiz {nombres} entre {[t['name'] for t in tops]}")


def _buscar_subcarpeta(aps, pid, folder_id, nombre, ruta, max_profundidad=6):
    """Busca por nombre (insensible a mayusculas/espacios) una subcarpeta dentro del arbol de
    folder_id, en cualquier nivel (no solo el primero) -- '011_WIP' puede vivir dentro de otra
    carpeta intermedia como '01_D&I'. BFS por niveles; se detiene en la primera coincidencia.
    Devuelve (folder_dict, ruta_texto) o (None, None) si no aparece en max_profundidad niveles."""
    nivel = [(folder_id, ruta)]
    objetivo = nombre.strip().lower()
    for _ in range(max_profundidad):
        siguiente = []
        for fid, r in nivel:
            for c in aps.child_folders(pid, fid):
                if c["name"].strip().lower() == objetivo:
                    return c, f"{r}/{c['name']}"
                siguiente.append((c["id"], f"{r}/{c['name']}"))
        nivel = siguiente
        if not nivel:
            break
    return None, None



def cache_vigente(guardado):
    """Regla de cache de carpetas de ACC (igual en todos los reportes):
    se usa solo si se guardo HOY y la corrida no es completa. Es completa el cierre mensual
    (run_pipeline.bat pone VENTAS_COMPLETO=1) y la primera corrida de cada dia; asi el cierre nunca
    se pierde nada y durante el dia las actualizaciones tardan segundos."""
    import os
    if os.environ.get("VENTAS_COMPLETO") == "1":
        return False
    try:
        return datetime.fromisoformat(str(guardado)).date() == datetime.now().date()
    except Exception:
        return False


def recorrer_proyecto(aps, cfg):
    """Devuelve (archivos, pid, avisos). Cada archivo trae 'proyecto' (carpeta de primer nivel dentro
    de Project Files, p.ej. GAP_SJC, HOWA, TUNGALOY...) y 'ruta'.

    Si cfg['subcarpeta_datos'] esta definida (por defecto '011_WIP'), SOLO se explora esa subcarpeta
    dentro de cada proyecto -- nada mas: ni archivos sueltos en la raiz de Project Files, ni otras
    subcarpetas del proyecto. La subcarpeta se busca en cualquier nivel dentro del proyecto (no tiene
    que ser hija directa; p.ej. GAP_SJC/01_D&I/011_WIP tambien cuenta). Si un proyecto no la tiene en
    ningun nivel, se omite y se avisa. Si subcarpeta_datos es null/"" se vuelve al recorrido recursivo
    completo del proyecto (modo anterior)."""
    a = cfg["aps"]
    hub, pid = aps.hub_id(a["account_id"]), aps.project_id(a["project_id"])
    raiz = _raiz(aps, hub, pid, cfg.get("raiz_nombres", ["Project Files", "Archivos de proyecto", "Plans"]))
    excl = {x.lower() for x in cfg.get("excluir_proyectos", [])}
    incl = {x.lower() for x in cfg.get("incluir_proyectos", [])}
    subcarpeta = cfg.get("subcarpeta_datos", "011_WIP")
    out, avisos = [], []
    # Donde esta la 011_WIP de cada proyecto: buscarla recorre todo el proyecto y es lo que mas tarda.
    # Se reusa durante el dia (cache_vigente); el contenido de cada 011_WIP (los PDFs) siempre se lee fresco.
    ubic_p = Path(cfg.get("cache_dir", "cache")) / "ubicacion_wip.json"
    try:
        ubic = json.loads(ubic_p.read_text(encoding="utf-8"))
        if not cache_vigente(ubic.get("guardado")):
            ubic = {}
    except Exception:
        ubic = {}
    wips_cache = ubic.get("proyectos", {}) if ubic else {}
    nuevas = {}

    if not subcarpeta:
        for f in aps.list_files(pid, raiz["id"], "/" + raiz["name"], recursive=False):
            out.append({**f, "proyecto": SIN_PROYECTO})

    for sub in aps.child_folders(pid, raiz["id"]):
        if sub["name"].upper().startswith("Z_"):
            # Proyectos de plantilla/prueba (Z_PLANTILLA, Z_PROYECTO, etc.) -- nunca se incluyen.
            continue
        if sub["name"].lower() in excl or (incl and sub["name"].lower() not in incl):
            continue
        if not subcarpeta:
            for f in aps.list_files(pid, sub["id"], f"/{raiz['name']}/{sub['name']}", recursive=True):
                out.append({**f, "proyecto": sub["name"]})
            continue
        base = f"/{raiz['name']}/{sub['name']}"
        if sub["id"] in wips_cache:
            wip_id, ruta_wip = wips_cache[sub["id"]] or (None, None)
        else:
            wip, ruta_wip = _buscar_subcarpeta(aps, pid, sub["id"], subcarpeta, base)
            wip_id = wip["id"] if wip else None
        if not wip_id:
            nuevas[sub["id"]] = None
            avisos.append(f"Proyecto '{sub['name']}': no se encontró la carpeta '{subcarpeta}' en ningún nivel; se omitió.")
            continue
        try:
            archivos = list(aps.list_files(pid, wip_id, ruta_wip, recursive=True))
        except Exception:
            if sub["id"] not in wips_cache:
                raise
            # La 011_WIP guardada ya no existe (se movio o borro): se busca de nuevo
            wip, ruta_wip = _buscar_subcarpeta(aps, pid, sub["id"], subcarpeta, base)
            wip_id = wip["id"] if wip else None
            archivos = list(aps.list_files(pid, wip_id, ruta_wip, recursive=True)) if wip_id else []
        nuevas[sub["id"]] = [wip_id, ruta_wip] if wip_id else None
        for f in archivos:
            out.append({**f, "proyecto": sub["name"]})
    if subcarpeta:
        try:
            ubic_p.parent.mkdir(parents=True, exist_ok=True)
            ubic_p.write_text(json.dumps({"guardado": ubic.get("guardado") if ubic else datetime.now().isoformat(timespec="seconds"),
                                          "proyectos": nuevas}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    log.info("Recorridos %d archivos en %d proyectos (subcarpeta=%s)", len(out), len({x['proyecto'] for x in out}), subcarpeta or "(todo el proyecto)")
    return out, pid, avisos


def filas_forma(archivos, cfg, clasif, aps=None, pid=None, cache_dir="cache"):
    """Planos publicados en Forma -- la base del reporte: lo que estamos verificando es si el plano
    (el PDF que alguien publico en Forma) viene respaldado por un modelo Revit, no al reves.

    El integrante y la disciplina de cada plano se toman del PDF mismo, igual que 'quien lo subio':
      - integrante: quien subio la version del PDF en ACC ('Version added by'), buscado en Equipos
        e integrantes - VENTAS.xlsx. Si no esta en la lista, el plano se descarta por completo.
      - disciplina: la primera carpeta despues de 011_WIP en la ruta del PDF (Arquitectura,
        Estructura, Mecanica, Plomeria, Electrica o Especiales). Si no coincide con ninguna, el
        plano se descarta por completo.
    Design Automation/Model Derivative solo se usan despues, en filas_revit, para saber si existe
    la hoja correspondiente en el modelo Revit -- no para decidir integrante/disciplina."""
    reglas_disc = cfg.get("disciplinas")
    reglas_ext = cfg.get("file_rules", {"default": ["pdf"]})
    subcarpeta = cfg.get("subcarpeta_datos", "011_WIP")
    verificar = cfg.get("verificar_origen", False)
    cache = Cache(cache_dir, "origen_pdf.json") if verificar else None
    rows, sin_integrante, sin_disciplina = [], 0, 0
    for f in archivos:
        nombre_lower = f["name"].lower()
        if nombre_lower.endswith(".rvt"):
            continue
        if not nombre_lower.endswith(".dwg"):
            # Los DWG siempre se incluyen (se marcan aparte como "no aplica" en la comparativa,
            # ver compare.comparar) -- la regla de extensiones de file_rules solo aplica a los
            # demas formatos (normalmente PDF).
            disc_ext = disciplina_por_ruta(f["path"], reglas_disc)
            if not extension_permitida(f["name"], f["proyecto"], disc_ext, reglas_ext):
                continue
        integrante, equipo, _ = clasif.asignar(f.get("added_by"))
        if integrante == SIN_INTEGRANTE:
            sin_integrante += 1
            continue
        disciplina = disciplina_por_carpeta_wip(f["path"], subcarpeta)
        if disciplina is None:
            sin_disciplina += 1
            continue
        num, nom = separar_plano(f["name"])
        row = {"proyecto": f["proyecto"], "numero": num, "nombre": nom, "disciplina": disciplina,
               "integrante": integrante, "equipo": equipo,
               "archivo": f["name"], "ruta": f["path"], "actualizado": f["last_modified"],
               "subido_por": f["added_by"], "actualizado_por": f["updated_by"], "origen_pdf": None}
        if verificar and f["name"].lower().endswith(".pdf"):
            row["origen_pdf"] = _origen(aps, pid, f, cache, cfg.get("firmas_pdf"))
        rows.append(row)
    if cache:
        cache.save()
    log.info("%d planos de Forma tras filtro de formato (%d descartados por integrante no listado, "
             "%d descartados por disciplina no detectada en su carpeta)", len(rows), sin_integrante, sin_disciplina)
    return rows


def _origen(aps, pid, f, cache, firmas):
    from .origin import leer_metadata, clasificar
    key = f"{f['version_urn']}"
    hit = cache.get(key)
    if hit:
        return hit["origen"]
    try:
        meta = leer_metadata(aps.download_version(pid, f["version_urn"]))
        origen, ev = clasificar(meta, firmas)
    except Exception as e:                      # no romper toda la corrida por un PDF
        origen, ev = "error", str(e)[:120]
    cache.set(key, {"origen": origen, "evidencia": ev})
    return origen


DEFAULT_HOJA_TRABAJO_PATRONES = [
    r"_TRABAJO$", r"_WIP$", r"_BORRADOR$", r"_DRAFT$", r"_INTERNO$", r"_NO\s*PUBLICAR$",
    r"^WIP[_\s-]", r"^TRABAJO[_\s-]", r"^BORRADOR[_\s-]", r"^X[_\s-]",
]


def es_hoja_de_trabajo(view_name, patrones):
    """True si el nombre CRUDO de la vista (antes de separar numero/nombre) trae una marca de
    hoja de trabajo/borrador, p.ej. '...' + '_TRABAJO'. Los patrones son regex (insensible a mayusculas)."""
    t = (view_name or "").strip()
    return any(re.search(p, t, re.I) for p in patrones)


def _ultima_en_cache(cache, version_urn):
    """Hojas guardadas del mismo modelo: primero las de esta version exacta; si no hay, las de la
    version mas reciente que se haya traducido (Model Derivative o Design Automation).
    -> (clave, hojas) o (None, None)."""
    base = str(version_urn).split("?", 1)[0]
    mejor, mejor_rango = (None, None), None
    for k, v in cache.d.items():
        urn = k[4:] if k.startswith("da::") else k
        if urn.split("?", 1)[0] != base or v is None:
            continue
        try:
            n = int(urn.split("version=", 1)[1].split("&", 1)[0])
        except Exception:
            n = 0
        # Gana: con hojas > sin hojas; luego la version exacta; luego la version mas reciente.
        rango = (bool(v), urn == version_urn, n)
        if mejor_rango is None or rango > mejor_rango:
            mejor, mejor_rango = (k, v), rango
    return mejor


def filas_revit(aps, pid, archivos, cfg, clasif, cache_dir="cache"):
    """Hojas de cada .rvt, asignadas al proyecto (carpeta de primer nivel) donde vive el modelo.
    Excluye .rvt de respaldo (excluir_regex) y hojas marcadas como de trabajo (revit.excluir_hojas_regex,
    aplicado al nombre crudo de la vista antes de separar numero/nombre).

    Los modelos Revit NO se filtran por integrante ni disciplina: 'Version added by' es quien subio
    el PLANO PDF a Forma (eso se filtra en filas_forma), no quien subio el modelo -- el campo
    equivalente del modelo no identifica de forma confiable a un integrante real (puede ser una
    cuenta de sincronizacion, etc.). Los modelos Revit solo sirven aqui para saber que hojas
    existen, para poder decir si un plano de Forma viene respaldado por Revit o no."""
    rc = cfg.get("revit", {})
    excl = re.compile(rc.get("excluir_regex", r"\.\d{4}\.rvt$"), re.I)
    regex = rc.get("sheet_view_regex", DEFAULT_SHEET_REGEX)
    patrones_trabajo = rc.get("excluir_hojas_regex", DEFAULT_HOJA_TRABAJO_PATRONES)
    cache = Cache(cache_dir, "hojas_revit.json")
    rows, vistos, avisos, descartadas = [], set(), [], 0
    modelos = [f for f in archivos if f["name"].lower().endswith(".rvt") and not excl.search(f["name"])]
    log.info("%d modelos Revit encontrados", len(modelos))
    da_cfg = cfg.get("design_automation")
    carpeta_local = rc.get("carpeta_log_local")
    usados_local = 0
    # true (por defecto) = como siempre: si un modelo no tiene hojas del add-in se traduce en Autodesk.
    # false = nunca se traduce (sin gasto de API); ver _ultima_en_cache.
    traducir = rc.get("traducir_sin_addin", True)
    sin_addin_cache, sin_addin_ignorados = [], []

    # El add-in local (SheetSync) no puede saber de forma confiable en que proyecto de ACC vive
    # cada modelo con solo mirar el archivo -- la API de Revit no expone esa jerarquia de carpetas
    # para modelos en la nube, y probamos que tampoco sirve el GUID interno del modelo (no
    # corresponde al identificador que usa la API). Para nombres de modelo que se repiten en mas
    # de un proyecto (p.ej. "12_ARQ_NAVE.rvt" existe tanto en GRANJAS JESSY como en GONVAUTO F2),
    # el add-in le pregunta a la persona una sola vez por modelo (ver revit_addin_sync/SheetSync.cs)
    # y guarda su respuesta -- por eso aqui escribimos "_modelos_duplicados.json" con la lista de
    # proyectos candidatos por nombre, para que el add-in solo ofrezca opciones reales (no texto
    # libre). Aun asi, mas abajo (local_sheets.hojas_locales con requerir_proyecto=True) SIEMPRE
    # se exige que el "proyecto" que trae el .json coincida exactamente con el que ya sabemos por
    # la API -- si alguien se equivoca en el desplegable, ese modelo puntual simplemente no se
    # beneficia del add-in (cae al metodo de siempre), pero nunca se mezclan hojas entre proyectos.
    nombres_por_proyecto = {}
    for m in modelos:
        nombres_por_proyecto.setdefault(Path(m["name"]).stem, set()).add(m["proyecto"])
    nombres_duplicados = {n for n, proys in nombres_por_proyecto.items() if len(proys) > 1}
    if nombres_duplicados:
        log.warning("Nombres de modelo repetidos en mas de un proyecto (el add-in local pedira "
                    "confirmar el proyecto la primera vez que se sincronicen): %s",
                    ", ".join(sorted(nombres_duplicados)))
        candidatos_json = json.dumps(
            {n: sorted(nombres_por_proyecto[n]) for n in nombres_duplicados},
            ensure_ascii=False, indent=2)
        # Se escribe en dos carpetas: la propia de PLANOS_VENTAS (carpeta_log_local, por
        # compatibilidad con instalaciones viejas del add-in) y la compartida con
        # PUBLICACIONES_VENTAS (carpeta_compartida) -- asi RevitSyncLogger tambien la lee y no
        # hace falta un pipeline Python aparte para ese sistema.
        for carpeta_destino in {carpeta_local, rc.get("carpeta_compartida")} - {None}:
            try:
                candidatos_path = Path(carpeta_destino) / "_modelos_duplicados.json"
                candidatos_path.write_text(candidatos_json, encoding="utf-8")
            except Exception as e:
                log.warning("No se pudo escribir _modelos_duplicados.json en %s: %s", carpeta_destino, e)

    for m in modelos:
        nombres_vistas = None  # nombres tipo 'NUM - NOMBRE' (via Model Derivative)
        pares_directos = None  # [(numero, nombre), ...] ya separados (via Design Automation o add-in local)
        nombre_modelo = Path(m["name"]).stem
        requerir_proyecto = nombre_modelo in nombres_duplicados

        # 1) Add-in local (SheetSync, ver revit_addin_sync/) -- sin API, sin costo. Si el modelo
        #    todavia no tiene datos ahi (nadie con el add-in instalado lo ha sincronizado), sigue
        #    de largo: con traducir_sin_addin=true usa Model Derivative / Design Automation; con
        #    false solo usa hojas ya guardadas en el cache. Para nombres duplicados
        #    (requerir_proyecto=True), local_sheets exige ademas que el "proyecto" del .json
        #    coincida exactamente con el de la API.
        if carpeta_local:
            from . import local_sheets
            pares_directos = local_sheets.hojas_locales(carpeta_local, m["proyecto"], nombre_modelo,
                                                          requerir_proyecto, urn=m.get("item_id"))
            if pares_directos:
                usados_local += 1
                for num, nom in pares_directos:
                    if es_hoja_de_trabajo(f"{num} - {nom}", patrones_trabajo):
                        descartadas += 1
                        continue
                    if (m["proyecto"], num, nom) in vistos:
                        continue
                    vistos.add((m["proyecto"], num, nom))
                    rows.append({"proyecto": m["proyecto"], "numero": num, "nombre": nom, "modelo": m["name"],
                                "autor_modelo": m.get("added_by"), "via": "sheetsync_local"})
                continue
            pares_directos = None

        if not traducir:
            # revit.traducir_sin_addin = false: CERO llamadas a Model Derivative / Design Automation.
            # Se usan las hojas que ya esten en el cache (de esta version o de la ultima version
            # traducida de ese mismo modelo). Si el modelo nunca se tradujo, se ignora y se avisa.
            clave, hojas_cache = _ultima_en_cache(cache, m["version_urn"])
            if hojas_cache is None:
                sin_addin_ignorados.append(f"{m['proyecto']} / {m['name']}")
                continue
            sin_addin_cache.append(f"{m['proyecto']} / {m['name']}")
            if not hojas_cache:
                continue           # ya se habia revisado y el modelo no tiene hojas
            if clave.startswith("da::"):
                pares_directos = [(h.get("numero", ""), h.get("nombre", "")) for h in hojas_cache if h.get("numero")]
            else:
                nombres_vistas = hojas_cache
        else:
            try:
                vistas = cache.get(m["version_urn"])
                if vistas is None:
                    vistas = aps.views_2d(m["version_urn"])
                    cache.set(m["version_urn"], vistas)
                nombres_vistas = vistas
            except Exception as e:
                log.warning("Modelo %s: %s (se intenta Design Automation si esta configurado)", m["name"], e)
                if not da_cfg:
                    avisos.append(f"{m['proyecto']} / {m['name']}: {e}")
                    continue
            if not nombres_vistas and da_cfg:
                try:
                    from . import design_automation as da
                    clave_da = f"da::{m['version_urn']}"
                    hojas_da = cache.get(clave_da)
                    if hojas_da is None:
                        hojas_da = da.extraer_hojas(aps, pid, m["version_urn"], cfg)
                        cache.set(clave_da, hojas_da)
                    pares_directos = [(h.get("numero", ""), h.get("nombre", "")) for h in hojas_da if h.get("numero")]
                    if not pares_directos:
                        avisos.append(f"{m['proyecto']} / {m['name']}: Design Automation no encontro hojas.")
                        continue
                except Exception as e2:
                    avisos.append(f"{m['proyecto']} / {m['name']}: Model Derivative fallo y Design Automation tambien: {e2}")
                    log.warning("Modelo %s: Design Automation fallo: %s", m["name"], e2)
                    continue
            elif not nombres_vistas:
                continue

        if pares_directos is not None:
            for num, nom in pares_directos:
                if es_hoja_de_trabajo(f"{num} - {nom}", patrones_trabajo):
                    descartadas += 1
                    continue
                if (m["proyecto"], num, nom) in vistos:
                    continue
                vistos.add((m["proyecto"], num, nom))
                rows.append({"proyecto": m["proyecto"], "numero": num, "nombre": nom, "modelo": m["name"],
                            "autor_modelo": m.get("added_by"), "via": "design_automation"})
            continue

        vistas = nombres_vistas
        for v in vistas:
            if es_hoja_de_trabajo(v, patrones_trabajo):
                descartadas += 1
                continue
            num, nom = split_sheet_view_name(v, regex)
            if (m["proyecto"], num, nom) in vistos:
                continue
            vistos.add((m["proyecto"], num, nom))
            rows.append({"proyecto": m["proyecto"], "numero": num, "nombre": nom, "modelo": m["name"],
                        "autor_modelo": m.get("added_by")})
    cache.save()
    if descartadas:
        avisos.append(f"Se excluyeron {descartadas} hojas marcadas como de trabajo/borrador (revit.excluir_hojas_regex).")
    if carpeta_local and traducir:
        log.info("%d de %d modelos usaron el add-in local (sin API); el resto uso Model Derivative/Design Automation.",
                  usados_local, len(modelos))
    if not traducir:
        log.info("Traducciones desactivadas (revit.traducir_sin_addin=false): %d de %d modelos con el add-in, "
                 "%d con hojas guardadas de una corrida anterior, %d ignorados. Cero llamadas a Model Derivative/Design Automation.",
                 usados_local, len(modelos), len(sin_addin_cache), len(sin_addin_ignorados))
        if sin_addin_cache:
            log.warning("Modelos SIN add-in (hojas de una corrida anterior, pueden no estar al dia): %s",
                        "; ".join(sin_addin_cache))
            avisos.append(f"{len(sin_addin_cache)} modelos aun sin el add-in: se usaron sus hojas de una corrida "
                          f"anterior (pueden no estar al dia).")
        if sin_addin_ignorados:
            log.warning("Modelos SIN add-in y sin hojas guardadas (no se incluyen): %s", "; ".join(sin_addin_ignorados))
            avisos.append(f"{len(sin_addin_ignorados)} modelos nunca sincronizados con el add-in no se incluyeron: "
                          + "; ".join(sin_addin_ignorados))
    log.info("%d hojas de Revit (%d descartadas por patron de trabajo)", len(rows), descartadas)
    return rows, avisos
