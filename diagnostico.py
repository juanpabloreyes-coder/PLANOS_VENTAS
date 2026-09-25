"""Prueba la Model Properties API (Index API) real de Autodesk contra
GRANJAS JESSY/12_ARQ_NAVE.rvt, con los endpoints correctos (via Postman collection oficial):
POST .../indexes:batchStatus -> GET .../indexes/{id} (poll) -> descargar fields/properties.
OJO: esta API esta construida sobre SVF2, y ya sabemos que SVF2 dio 406 "not supported for
this design" en este modelo -- este test nos dira si de todas formas funciona para propiedades
(sin geometria) o si tambien falla por lo mismo.
Uso:  python diagnostico.py
"""
import json
import time
from plano_sync.__main__ import _cfg, _aps
from plano_sync import collect

cfg = _cfg("config.json")
aps = _aps(cfg)

print("Recorriendo proyecto (puede tardar unos segundos)...")
archivos, pid, av = collect.recorrer_proyecto(aps, cfg)
m = [f for f in archivos if f["name"] == "12_ARQ_NAVE.rvt" and f["proyecto"] == "GRANJAS JESSY"][0]
print("\nModelo:", m["proyecto"], "/", m["name"], "| version_urn:", m["version_urn"])

pid_sin_b = pid[2:] if pid.startswith("b.") else pid
print("project_id (sin 'b.'):", pid_sin_b)

print("\n--- Paso 1: POST indexes:batchStatus ---")
r = aps.req("POST", f"/construction/index/v2/projects/{pid_sin_b}/indexes:batchStatus",
            ok=(200, 201, 202, 400, 401, 403, 404, 422),
            json={"versions": [{"versionUrn": m["version_urn"]}]})
print("status:", r.status_code)
body = r.json()
print(json.dumps(body, indent=2, ensure_ascii=False)[:2000])

if r.status_code not in (200, 201, 202):
    print("\nNo se pudo crear el indice. Nos detenemos aqui.")
    raise SystemExit(0)

index_id = None
try:
    index_id = body["indexes"][0]["indexId"]
except Exception:
    print("\nNo encontre indexId en la respuesta, revisa el JSON de arriba.")
    raise SystemExit(0)

print("\nindexId:", index_id)

print("\n--- Paso 2: poll de estado ---")
for i in range(20):
    r = aps.req("GET", f"/construction/index/v2/projects/{pid_sin_b}/indexes/{index_id}", ok=(200, 202, 400, 404))
    j = r.json()
    estado = j.get("state") or j.get("status")
    print(f"  intento {i}: status={r.status_code} state={estado}")
    if r.status_code == 200 and estado in ("FINISHED", "FAILED"):
        print(json.dumps(j, indent=2, ensure_ascii=False)[:3000])
        break
    time.sleep(10)

print("\nListo.")
