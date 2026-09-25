"""Verificacion del ORIGEN de un PDF (Revit vs otro software) a partir de sus metadatos.

Un PDF guarda en su interior que programa lo creo (/Creator, /Producer, XMP CreatorTool).
- Exportado/publicado desde Revit  -> normalmente contiene "Revit".
- Trazado desde AutoCAD u otro CAD -> contiene "AutoCAD", "MicroStation", etc.
- Impreso con una impresora PDF    -> Bluebeam / Adobe PDF / Microsoft Print to PDF: el origen NO es verificable.
LIMITE: es evidencia fuerte pero no infalible (alguien puede reimprimir un PDF o editar metadatos).
Las firmas se calibran con `python -m plano_sync pdfinfo *.pdf` sobre PDFs cuyo origen ya conoces.
"""
import io
import warnings

FIRMAS_DEFAULT = {
    "revit": ["revit"],
    "cad": ["autocad", "microstation", "bricscad", "draftsight", "zwcad", "intellicad", "progecad",
            "civil 3d", "archicad", "sketchup", "vectorworks", "allplan", "tekla"],
    "impresora": ["bluebeam", "adobe pdf", "acrobat", "pdf-xchange", "print to pdf", "pdf24", "cutepdf",
                  "novapdf", "pdfcreator", "ghostscript", "foxit", "dopdf", "bullzip", "pdfsharp", "ilovepdf"],
}

V_OK = "Verificado Revit"
V_REVIT_SIN_HOJA = "Revit, pero sin hoja equivalente en el modelo"
V_SOSPECHOSO = "Sospechoso: generado fuera de Revit"
V_NO_VERIF = "Coincide con hoja Revit; origen del PDF no verificable"
V_NADA = "No verificable"
V_ERROR = "No se pudo leer el PDF"
V_DWG = "DWG: origen no verificado"


def leer_metadata(data):
    """bytes de un PDF -> dict con creator/producer/creator_tool/fechas/paginas."""
    from pypdf import PdfReader
    warnings.filterwarnings("ignore")
    r = PdfReader(io.BytesIO(data), strict=False)
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            pass
    m = r.metadata or {}
    g = lambda k: (str(m.get(k)) if m.get(k) is not None else None)
    tool = None
    try:
        x = r.xmp_metadata
        tool = x.xmp_creator_tool if x else None
    except Exception:
        pass
    return {"creator": g("/Creator"), "producer": g("/Producer"), "creator_tool": tool,
            "creation_date": g("/CreationDate"), "mod_date": g("/ModDate"), "paginas": len(r.pages)}


def clasificar(meta, firmas=None):
    """-> (origen, evidencia). origen: revit | cad | impresora | desconocido | conflicto"""
    f = {**FIRMAS_DEFAULT, **(firmas or {})}
    ev = " | ".join(x for x in (meta.get("creator"), meta.get("producer"), meta.get("creator_tool")) if x)
    t = ev.lower()
    es = lambda k: any(s.lower() in t for s in f[k])
    rv, cad = es("revit"), es("cad")
    if rv and cad:
        return "conflicto", ev
    if rv:
        return "revit", ev
    if cad:
        return "cad", ev
    if es("impresora"):
        return "impresora", ev
    return "desconocido", ev


def veredicto(origen, exacta, viene_de_revit, es_pdf=True):
    if not es_pdf:
        return V_DWG
    if origen == "error":
        return V_ERROR
    if origen in ("cad", "conflicto"):
        return V_SOSPECHOSO
    if origen == "revit":
        return V_OK if exacta else V_REVIT_SIN_HOJA
    if exacta:
        return V_NO_VERIF
    return V_NADA
