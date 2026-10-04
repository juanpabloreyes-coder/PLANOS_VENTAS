"""Diagnostico puntual: imprime el item_id (que trae el GUID de linaje de Autodesk) de cada
archivo llamado '12_ARQ_NAVE.rvt' que encuentre, junto con el proyecto (carpeta) donde vive.

Uso (desde la carpeta PLANOS_VENTAS, con las variables de entorno APS_CLIENT_ID / APS_CLIENT_SECRET
ya configuradas, igual que para correr el pipeline normal):
    python verificar_guid.py

Esto NO modifica nada ni genera el reporte -- solo imprime para poder comparar a mano contra el
GUID que capture el add-in la proxima vez que alguien sincronice ese mismo modelo.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plano_sync.aps import APS
from plano_sync import collect

cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
a = cfg.get("aps", {})
cid = os.environ.get("APS_CLIENT_ID") or a.get("client_id")
sec = os.environ.get("APS_CLIENT_SECRET") or a.get("client_secret")
if not cid or not sec:
    sys.exit("Falta APS_CLIENT_ID / APS_CLIENT_SECRET (variables de entorno).")

aps = APS(cid, sec)
archivos, pid, avisos = collect.recorrer_proyecto(aps, cfg)
for w in avisos:
    print("AVISO:", w)

objetivo = "12_arq_nave.rvt"
encontrados = [f for f in archivos if f["name"].lower() == objetivo]
if not encontrados:
    print(f"No encontre ningun archivo llamado {objetivo!r}. Nombres .rvt disponibles (primeros 30):")
    for f in [x for x in archivos if x["name"].lower().endswith(".rvt")][:30]:
        print("  -", f["proyecto"], "/", f["name"])
    sys.exit(1)

print(f"\nEncontrados {len(encontrados)} archivo(s) llamados {objetivo!r}:\n")
for f in encontrados:
    print(f"Proyecto : {f['proyecto']}")
    print(f"Ruta     : {f['path']}")
    print(f"item_id  : {f['item_id']}")
    print(f"version  : {f['version_urn']}  (version #{f.get('version_number')})")
    print()
