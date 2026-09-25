"""Comparativa Forma vs Revit por NUMERO y NOMBRE de plano, dentro de cada proyecto.

Estados: exacta (numero+nombre) / solo numero / solo nombre / sin coincidencia.
Si el proyecto no tiene ningun modelo Revit con hojas, sus planos quedan como
'Sin modelo Revit' (no se cuentan como 'sin coincidencia': no hay contra que comparar).
"""
from collections import defaultdict
from .parsing import normalizar_numero, normalizar_nombre

ESTADOS = ["Coincide número y nombre", "Coincide solo número", "Coincide solo nombre", "Sin coincidencia"]
SIN_MODELO = "Sin modelo Revit"


def comparar(forma_rows, revit_rows):
    """forma_rows: dict(proyecto, numero, nombre, archivo, integrante, equipo, disciplina, ...) --
       integrante/equipo/disciplina ya vienen calculados del PDF mismo (ver collect.filas_forma):
       lo que se esta verificando es si el plano publicado en Forma viene respaldado por un modelo
       Revit, no al reves. Los modelos Revit (revit_rows) solo se usan para saber si existe la hoja
       correspondiente -- nunca sobreescriben integrante/equipo/disciplina del plano.
       -> (comparativa, revit_sin_publicar)"""
    revit = sorted(revit_rows, key=lambda r: (r["proyecto"], r["numero"] or "", r["nombre"] or ""))
    con_revit = {r["proyecto"] for r in revit}
    por_num, por_nom, por_par = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in revit:
        r["_n"], r["_m"] = normalizar_numero(r["numero"]), normalizar_nombre(r["nombre"])
        por_num[(r["proyecto"], r["_n"])].append(r)
        por_nom[(r["proyecto"], r["_m"])].append(r)
        por_par[(r["proyecto"], r["_n"], r["_m"])].append(r)

    out, vistos = [], set()
    for f in sorted(forma_rows, key=lambda r: (r["proyecto"], r["numero"] or "", r["archivo"])):
        p, n, m = f["proyecto"], normalizar_numero(f["numero"]), normalizar_nombre(f["nombre"])
        es_dwg = f["archivo"].lower().endswith(".dwg")
        base = {**f, "formato": "DWG" if es_dwg else "PDF"}
        if es_dwg:
            # Los DWG cuentan en la estadistica como cualquier plano de Forma, pero nunca se
            # buscan contra las hojas de Revit: quedan directamente como "Sin coincidencia"
            # (entran en el conteo de comparables, no en un cubo aparte) sin intentar matchear.
            out.append({**base, "numero_revit": None, "nombre_revit": None, "estado": ESTADOS[3],
                        "viene_de_revit": False, "exacta": False, "coincidencias": 0, "modelo_revit": None})
            continue
        if p not in con_revit:
            out.append({**base, "numero_revit": None, "nombre_revit": None, "estado": SIN_MODELO,
                        "viene_de_revit": False, "exacta": False, "coincidencias": 0, "modelo_revit": None})
            continue
        num = por_num.get((p, n), []) if n else []
        nom = por_nom.get((p, m), []) if m else []
        exa = por_par.get((p, n, m), []) if (n and m) else []
        cand = exa[0] if exa else num[0] if num else nom[0] if nom else None
        estado = ESTADOS[0] if exa else ESTADOS[1] if num else ESTADOS[2] if nom else ESTADOS[3]
        for r in num:
            vistos.add(id(r))
        out.append({**base, "numero_revit": cand["numero"] if cand else None,
                    "nombre_revit": cand["nombre"] if cand else None, "estado": estado,
                    "viene_de_revit": bool(num), "exacta": bool(exa), "coincidencias": len(num),
                    "modelo_revit": cand.get("modelo") if cand else None})
    faltantes = [{"proyecto": r["proyecto"], "numero": r["numero"], "nombre": r["nombre"]}
                 for r in revit if id(r) not in vistos]
    return out, faltantes


def resumen(comp, faltantes):
    dwg = sum(1 for r in comp if r.get("formato") == "DWG")
    comparables = [r for r in comp if r["estado"] != SIN_MODELO]
    n = len(comparables)
    c = {e: sum(1 for r in comp if r["estado"] == e) for e in ESTADOS}
    return {"total_forma": len(comp), "comparables": n,
            "sin_modelo_revit": sum(1 for r in comp if r["estado"] == SIN_MODELO), "dwg_no_aplica": dwg,
            "exactas": c[ESTADOS[0]], "solo_numero": c[ESTADOS[1]], "solo_nombre": c[ESTADOS[2]],
            "sin_coincidencia": c[ESTADOS[3]], "pct_exactas": (c[ESTADOS[0]] / n) if n else 0,
            "revit_sin_publicar": len(faltantes)}
