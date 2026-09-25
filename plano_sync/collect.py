"""Obtiene de ACC (APS) los planos de Forma y las hojas de los modelos Revit del proyecto VENTAS GCP.

Clasificacion por PROYECTO = carpeta de primer nivel dentro de 'Project Files'
(equivale a ResolveRoot de DimProyectoConcurso: sube por la jerarquia hasta la raiz del sistema
y se queda con la carpeta inmediatamente debajo de ella).
"""
import json
import logging
import re
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
        wip, ruta_wip = _buscar_subcarpeta(aps, pid, sub["id"], subcarpeta, f"/{raiz['name']}/{sub['name']}")
        if not wip:
            avisos.append(f"Proyecto '{sub['name']}': no se encontró la carpeta '{subcarpeta}' en ningún nivel; se omitió.")
            continue
        for f in aps.list_files(pid, wip["id"], ruta_wip, recursive=True):
            out.append({**f, "proyecto": sub["name"]})
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
    for m in modelos:
        nombres_vistas = None  # nombres tipo 'NUM - NOMBRE' (via Model Derivative)
        pares_directos = None  # [(numero, nombre), ...] ya separados (via Design Automation o add-in local)

        # 1) Add-in local (SheetSync, ver revit_addin_sync/) -- sin API, sin costo. Si el modelo
        #    todavia no tiene datos ahi (nadie con el add-in instalado lo ha sincronizado), sigue
        #    de largo y usa el metodo de siempre (Model Derivative / Design Automation) mas abajo,
        #    exactamente como funcionaba antes de tener esta opcion.
        if carpeta_local:
            from . import local_sheets
            nombre_modelo = Path(m["name"]).stem
            pares_directos = local_sheets.hojas_locales(carpeta_local, nombre_modelo)
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
    if carpeta_local:
        log.info("%d de %d modelos usaron el add-in local (sin API); el resto uso Model Derivative/Design Automation.",
                  usados_local, len(modelos))
    log.info("%d hojas de Revit (%d descartadas por patron de trabajo)", len(rows), descartadas)
    return rows, avisos
