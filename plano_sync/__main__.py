"""Uso (desde la carpeta PLANOS_VENTAS):
  python -m plano_sync run   --config config.json     # corrida completa (esto se programa)
  python -m plano_sync demo  --out demo               # datos sinteticos, sin APS
  python -m plano_sync probe --config config.json     # ver vistas 2D crudas de un modelo (validar nombres de hoja)
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import collect, compare, report
from .aps import APS
from .integrantes import cargar_equipos, Clasificador


def _cfg(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _aps(cfg):
    a = cfg.get("aps", {})
    cid = os.environ.get("APS_CLIENT_ID") or a.get("client_id")
    sec = os.environ.get("APS_CLIENT_SECRET") or a.get("client_secret")
    if not cid or not sec:
        sys.exit("Falta APS_CLIENT_ID / APS_CLIENT_SECRET (variables de entorno).")
    return APS(cid, sec)


def _clasif(cfg):
    ruta = cfg.get("equipos_xlsx")
    if not ruta or not Path(ruta).exists():
        logging.warning("No se encontro equipos_xlsx (%s): los planos quedaran 'Sin integrante asignado'", ruta)
        return Clasificador([]), ["No se pudo leer el archivo de equipos e integrantes."]
    return Clasificador(cargar_equipos(ruta, cfg.get("equipos_hoja", "Integrantes"))), []


def _salida(cfg, comp, falt, avisos, titulo, out):
    res = compare.resumen(comp, falt)
    d = report.escribir_todo(out, comp, falt, res, avisos, titulo, cfg.get("subtitulo", "Forma vs Revit"))
    print(res, "->", Path(d).resolve())
    return res


def cmd_run(a):
    cfg = _cfg(a.config)
    aps, avisos = _aps(cfg), []
    clasif, av0 = _clasif(cfg)
    avisos += av0
    cache_dir = cfg.get("cache_dir", "cache")
    archivos, pid, av_rec = collect.recorrer_proyecto(aps, cfg)
    avisos += av_rec
    forma = collect.filas_forma(archivos, cfg, clasif, aps, pid, cache_dir)
    revit, av1 = collect.filas_revit(aps, pid, archivos, cfg, clasif, cache_dir)
    avisos += av1
    if not forma:
        sys.exit("Sin planos en Forma: no se genera nada (se conserva la ultima version).")
    comp, falt = compare.comparar(forma, revit)
    res = _salida(cfg, comp, falt, avisos, cfg.get("title", "Planos Forma vs Revit · VENTAS GCP"), cfg.get("output_dir", "reporte"))
    logging.info("Listo: %s", res)


def cmd_demo(a):
    from .demo import generar
    cfg = _cfg(a.config) if a.config and Path(a.config).exists() else {}
    clasif, _ = _clasif(cfg)
    forma, revit = generar(clasif)
    comp, falt = compare.comparar(forma, revit)
    _salida(cfg, comp, falt, ["Datos de demostración (sintéticos): no corresponden a planos reales."],
            "Planos Forma vs Revit · DEMO", a.out)


def cmd_probe(a):
    cfg = _cfg(a.config)
    from .aps import split_sheet_view_name, DEFAULT_SHEET_REGEX
    aps = _aps(cfg)
    archivos, pid, av_rec = collect.recorrer_proyecto(aps, cfg)
    for w in av_rec:
        print("AVISO:", w)
    modelos = [f for f in archivos if f["name"].lower().endswith(".rvt")][: a.n]
    for m in modelos:
        print("\n==", m["proyecto"], "/", m["name"])
        try:
            for v in aps.views_2d(m["version_urn"])[:15]:
                print("  ", repr(v), "->", split_sheet_view_name(v, cfg.get("revit", {}).get("sheet_view_regex", DEFAULT_SHEET_REGEX)))
        except Exception as e:
            print("   ERROR:", e)


def cmd_publicar_plugin(a):
    cfg = _cfg(a.config)
    if "design_automation" not in cfg:
        sys.exit("Falta la seccion 'design_automation' en config.json (ver revit_plugin/build_and_deploy.md).")
    aps = _aps(cfg)
    from . import design_automation as da
    res = da.publicar_appbundle_y_activity(aps, cfg, a.zip)
    print("Publicado:", res)


def main():
    ap = argparse.ArgumentParser(prog="plano_sync")
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--config", default="config.json"); r.set_defaults(f=cmd_run)
    d = sp.add_parser("demo"); d.add_argument("--out", default="demo"); d.add_argument("--config", default="config.json"); d.set_defaults(f=cmd_demo)
    p = sp.add_parser("probe"); p.add_argument("--config", default="config.json"); p.add_argument("-n", type=int, default=3); p.set_defaults(f=cmd_probe)
    pp = sp.add_parser("publicar_plugin"); pp.add_argument("--config", default="config.json"); pp.add_argument("--zip", required=True); pp.set_defaults(f=cmd_publicar_plugin)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("plano_sync.log", encoding="utf-8")])
    a.f(a)


if __name__ == "__main__":
    main()
