"""Autodesk Design Automation for Revit: corre el plugin SheetExporter (ver revit_plugin/) sobre
un modelo .rvt en la nube, sin interfaz grafica, para obtener sus hojas (Sheets) SIN que le
afecten los vinculos faltantes -- a diferencia de Model Derivative/SVF2, esto usa la API nativa
de Revit, que no necesita resolver geometria de vinculos externos para leer la lista de hojas.

Flujo (todo automatico una vez configurado):
  1. (una sola vez, manual) alguien compila revit_plugin/ y lo sube como AppBundle + Activity
     con publicar_appbundle_y_activity(). Ver revit_plugin/build_and_deploy.md.
  2. Por cada modelo: extraer_hojas(aps, cfg, version_urn) -> descarga el .rvt, lo sube a un
     bucket OSS propio, dispara un WorkItem contra la Activity, espera a que termine, descarga
     result.json y lo interpreta.

Requiere en config.json una seccion:
  "design_automation": {
    "nickname": "<tu app nickname en APS, tomado del Client ID>",
    "activity": "SheetExporterActivity",
    "engine": "Autodesk.Revit+2025",
    "bucket": "<nombre-de-bucket-oss-propio-minusculas>"
  }
"""
import json
import time
import uuid

from .aps import APSError

DA_BASE = "/da/us-east/v3"


def _act_id(cfg):
    da = cfg["design_automation"]
    return f"{da['nickname']}.{da['activity']}+prod"


def _appbundle_id(cfg):
    da = cfg["design_automation"]
    return f"{da['nickname']}.SheetExporterBundle+prod"


def asegurar_bucket(aps, cfg):
    """Crea (si no existe) el bucket OSS propio donde subimos los .rvt de entrada y
    recibimos los result.json de salida de cada WorkItem."""
    bucket = cfg["design_automation"]["bucket"]
    r = aps.req("GET", f"/oss/v2/buckets/{bucket}/details", ok=(200, 404))
    if r.status_code == 404:
        aps.req("POST", "/oss/v2/buckets", ok=(200, 409),
                 json={"bucketKey": bucket, "policyKey": "transient"})
    return bucket


def _signed_upload_url(aps, bucket, obj_key):
    r = aps.req("GET", f"/oss/v2/buckets/{bucket}/objects/{obj_key}/signeds3upload?minutesExpiration=30")
    return r.json()

def _finalizar_upload(aps, bucket, obj_key, upload_key):
    aps.req("POST", f"/oss/v2/buckets/{bucket}/objects/{obj_key}/signeds3upload", ok=(200, 201),
             json={"uploadKey": upload_key})


def _signed_download_url(aps, bucket, obj_key, minutos=30):
    r = aps.req("GET", f"/oss/v2/buckets/{bucket}/objects/{obj_key}/signeds3download?minutesExpiration={minutos}")
    j = r.json()
    return j.get("url") or j["urls"][0]


def subir_rvt_a_oss(aps, pid, version_urn, cfg):
    """Descarga el .rvt desde ACC (Data Management) y lo vuelve a subir a nuestro bucket OSS
    propio, para poder darle a Design Automation una URL de entrada que si pueda leer
    (Design Automation no puede autenticarse directo contra ACC con nuestro token 2-legged
    de la misma forma; usar nuestro propio bucket transient es el patron recomendado por
    Autodesk para este caso)."""
    import requests
    bucket = asegurar_bucket(aps, cfg)
    obj_key = f"input-{uuid.uuid4().hex}.rvt"

    contenido = aps.download_version(pid, version_urn)

    su = _signed_upload_url(aps, bucket, obj_key)
    put_url = su["urls"][0] if isinstance(su.get("urls"), list) else su["url"]
    r = requests.put(put_url, data=contenido, timeout=600)
    r.raise_for_status()
    _finalizar_upload(aps, bucket, obj_key, su["uploadKey"])

    return bucket, obj_key


def extraer_hojas(aps, pid, version_urn, cfg, wait_seconds=900):
    """Corre el WorkItem completo y devuelve una lista de dicts {numero, nombre, ...}.
    Lanza APSError si el WorkItem falla o se agota el tiempo."""
    bucket, obj_key_in = subir_rvt_a_oss(aps, pid, version_urn, cfg)
    obj_key_out = f"output-{uuid.uuid4().hex}.json"

    url_in = _signed_download_url(aps, bucket, obj_key_in)
    su_out = _signed_upload_url(aps, bucket, obj_key_out)
    url_out_put = su_out["urls"][0] if isinstance(su_out.get("urls"), list) else su_out["url"]

    body = {
        "activityId": _act_id(cfg),
        "arguments": {
            "rvtFile": {"url": url_in, "verb": "get"},
            "result": {"url": url_out_put, "verb": "put"},
        },
    }
    r = aps.req("POST", f"{DA_BASE}/workitems", ok=(200, 201), json=body)
    workitem_id = r.json()["id"]

    t0 = time.time()
    estado = "pending"
    while estado in ("pending", "inprogress"):
        if time.time() - t0 > wait_seconds:
            raise APSError(f"WorkItem {workitem_id} no termino a tiempo (Design Automation).")
        time.sleep(10)
        r = aps.req("GET", f"{DA_BASE}/workitems/{workitem_id}")
        estado = r.json().get("status")

    if estado != "success":
        detalle = r.json()
        raise APSError(f"WorkItem {workitem_id} termino en estado '{estado}': {json.dumps(detalle)[:300]}")

    _finalizar_upload(aps, bucket, obj_key_out, su_out["uploadKey"])
    url_result = _signed_download_url(aps, bucket, obj_key_out)
    import requests
    resp = requests.get(url_result, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise APSError(f"El plugin SheetExporter reporto un error: {data['error']}")
    return data.get("hojas", [])


def publicar_appbundle_y_activity(aps, cfg, ruta_zip_bundle):
    """Sube (o actualiza) el AppBundle compilado (revit_plugin/SheetExporter.bundle empaquetado
    como .zip) y crea/actualiza la Activity correspondiente. Se corre UNA SOLA VEZ (o cuando se
    recompile el plugin), no en cada corrida normal del pipeline. ruta_zip_bundle: ruta local al
    .zip generado a partir de la carpeta SheetExporter.bundle."""
    import requests
    da = cfg["design_automation"]
    nickname = da["nickname"]

    # 1) Asegurar el nickname de la app (una sola vez por cuenta APS)
    aps.req("PATCH", "/da/us-east/v3/forgeapps/me", ok=(200, 409), json={"nickname": nickname})

    # 2) Crear o actualizar el AppBundle
    bundle_id = "SheetExporterBundle"
    r = aps.req("GET", f"{DA_BASE}/appbundles/{nickname}.{bundle_id}+prod", ok=(200, 404))
    if r.status_code == 404:
        r = aps.req("POST", f"{DA_BASE}/appbundles", ok=(200, 201),
                     json={"id": bundle_id, "engine": da["engine"], "description": "SheetExporter"})
    else:
        r = aps.req("POST", f"{DA_BASE}/appbundles/{bundle_id}/versions", ok=(200, 201),
                     json={"engine": da["engine"], "description": "SheetExporter"})
    j = r.json()
    upload = j["uploadParameters"]
    with open(ruta_zip_bundle, "rb") as f:
        files = {"file": f}
        rr = requests.post(upload["endpointURL"], data=upload["formData"], files=files, timeout=300)
        rr.raise_for_status()

    ra = aps.req("GET", f"{DA_BASE}/appbundles/{bundle_id}/aliases/prod", ok=(200, 404))
    if ra.status_code == 404:
        aps.req("POST", f"{DA_BASE}/appbundles/{bundle_id}/aliases", ok=(200, 201),
                 json={"id": "prod", "version": j["version"]})
    else:
        aps.req("PATCH", f"{DA_BASE}/appbundles/{bundle_id}/aliases/prod", ok=(200, 201),
                 json={"version": j["version"]})

    # 3) Crear o actualizar la Activity
    act_id = da["activity"]
    definicion = {
        "id": act_id,
        "commandLine": [f"$(engine.path)\\\\revitcoreconsole.exe /i \"$(args[rvtFile].path)\" /al \"$(appbundles[{bundle_id}].path)\""],
        "parameters": {
            "rvtFile": {"verb": "get", "description": "Modelo Revit de entrada", "required": True, "localName": "input.rvt"},
            "result": {"verb": "put", "description": "JSON con las hojas", "required": True, "localName": "result.json"},
        },
        "engine": da["engine"],
        "appbundles": [f"{nickname}.{bundle_id}+prod"],
        "description": "Exporta la lista de hojas de un modelo Revit",
    }
    r = aps.req("GET", f"{DA_BASE}/activities/{nickname}.{act_id}+prod", ok=(200, 404))
    if r.status_code == 404:
        r = aps.req("POST", f"{DA_BASE}/activities", ok=(200, 201), json=definicion)
    else:
        definicion_sin_id = {k: v for k, v in definicion.items() if k != "id"}
        r = aps.req("POST", f"{DA_BASE}/activities/{act_id}/versions", ok=(200, 201), json=definicion_sin_id)
    version_act = r.json().get("version", 1)
    ra2 = aps.req("GET", f"{DA_BASE}/activities/{act_id}/aliases/prod", ok=(200, 404))
    if ra2.status_code == 404:
        aps.req("POST", f"{DA_BASE}/activities/{act_id}/aliases", ok=(200, 201),
                 json={"id": "prod", "version": version_act})
    else:
        aps.req("PATCH", f"{DA_BASE}/activities/{act_id}/aliases/prod", ok=(200, 201),
                 json={"version": version_act})

    return {"appbundle": f"{nickname}.{bundle_id}+prod", "activity": _act_id(cfg)}
