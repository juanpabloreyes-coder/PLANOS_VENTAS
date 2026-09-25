"""Datos SINTETICOS (no reales) para probar el pipeline y el dashboard sin credenciales de APS."""
import random
from .parsing import separar_plano

PROYECTOS = ["GAP_SJC", "GAP_SJC_NORTE", "HOWA", "GOHSYU", "TUNGALOY", "BMW_ADECUACION"]
_NOMBRES = ["PLANTA DE CIMENTACION", "PLANTA DE COLUMNAS", "CORTES GENERALES", "FACHADA NORTE", "DETALLES CONSTRUCTIVOS",
            "INSTALACION ELECTRICA", "INSTALACION HIDRAULICA", "LOSA DE ENTREPISO", "CUADRO DE CARGAS", "PLANTA DE CONJUNTO"]
_DISC = [("Arquitectura", "01101_ARQUITECTURA", "A"), ("Estructura", "01102_ESTRUCTURA", "E"),
         ("Electrica", "01105_ELECTRICA", "IE"), ("Plomeria", "01104_PLOMERIA", "IH")]


def generar(clasif, seed=7):
    """clasif: instancia de Clasificador (equipos e integrantes). El integrante y la disciplina de
    cada plano salen del PDF mismo (quien lo subio -- Version added by -- y su carpeta), no del
    modelo Revit: lo que se verifica es si el PDF viene respaldado por un modelo Revit."""
    rnd = random.Random(seed)
    autores = [e["integrante"] for e in clasif.equipos] + ["Usuario Externo"]
    forma, revit = [], []
    for p in PROYECTOS:
        sin_modelo = p in ("BMW_ADECUACION",)               # un proyecto sin modelo Revit
        for disc, carpeta, pref in _DISC:
            autor_modelo = rnd.choice(autores)
            integrante, equipo, _ = clasif.asignar(autor_modelo)
            for i in range(1, 9):
                num, nom = f"{pref}-{100 + i}", rnd.choice(_NOMBRES)
                if not sin_modelo:
                    revit.append({"proyecto": p, "numero": num, "nombre": nom, "modelo": f"{p}_{pref}.rvt",
                                  "integrante": integrante, "equipo": equipo, "autor_modelo": autor_modelo})
                r = rnd.random()
                if r < 0.10:
                    continue
                nom_f = nom if r < 0.70 else (nom + " REV" if r < 0.80 else "OTRO NOMBRE")
                num_f = num if r < 0.90 else f"{pref}-{900 + i}"
                archivo = f"{num_f} - {nom_f}.pdf"
                n, m = separar_plano(archivo)
                autor_pdf = rnd.choice(autores)
                integrante_pdf, equipo_pdf, _ = clasif.asignar(autor_pdf)
                forma.append({"proyecto": p, "numero": n, "nombre": m, "disciplina": disc, "archivo": archivo,
                              "integrante": integrante_pdf, "equipo": equipo_pdf,
                              "ruta": f"/Project Files/{p}/011_WIP/{carpeta}", "actualizado": "2026-09-10T10:00:00Z",
                              "subido_por": autor_pdf, "actualizado_por": None, "origen_pdf": None})
    return forma, revit
