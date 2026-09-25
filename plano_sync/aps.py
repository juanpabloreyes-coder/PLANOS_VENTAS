"""Cliente minimo de Autodesk Platform Services (APS) para ACC/Forma.

- Data Management API : carpetas, archivos, autor de la version, descarga.
- Model Derivative API: hojas (sheets) de un modelo Revit ya traducido.
Autenticacion 2-legged (client credentials). La app debe estar agregada como
"Custom Integration" en Account Admin de ACC (ver README).
"""
import base64
import logging
import re
import time
from urllib.parse import quote

import requests

BASE = "https://developer.api.autodesk.com"
log = logging.getLogger("plano_sync.aps")


class APSError(RuntimeError):
    pass


class APS:
    def __init__(self, client_id, client_secret,
                 scope="data:read data:write viewables:read account:read "
                       "code:all bucket:create bucket:read bucket:delete"):
        self.cid, self.secret, self.scope = client_id, client_secret, scope
        self._tok, self._exp = None, 0
        self.s = requests.Session()

    # -- auth / http -------------------------------------------------
    def token(self):
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        r = requests.post(f"{BASE}/authentication/v2/token", auth=(self.cid, self.secret),
                          data={"grant_type": "client_credentials", "scope": self.scope}, timeout=60)
        if r.status_code != 200:
            raise APSError(f"Auth APS fallo ({r.status_code}): {r.text[:300]}")
        j = r.json()
        self._tok, self._exp = j["access_token"], time.time() + int(j.get("expires_in", 3000))
        return self._tok

    def req(self, method, url, ok=(200,), retries=5, **kw):
        if url.startswith("/"):
            url = BASE + url
        extra = kw.pop("headers", {})
        for i in range(retries):
            h = {"Authorization": f"Bearer {self.token()}", **extra}
            r = self.s.request(method, url, headers=h, timeout=120, **kw)
            if r.status_code in ok:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(2 ** i * 2, 60))
                continue
            raise APSError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
        raise APSError(f"{method} {url}: demasiados reintentos")

    # -- Data Management ---------------------------------------------
    @staticmethod
    def hub_id(account_id):
        return account_id if account_id.startswith("b.") else "b." + account_id

    @staticmethod
    def project_id(pid):
        return pid if pid.startswith("b.") else "b." + pid

    def top_folders(self, hub, pid):
        j = self.req("GET", f"/project/v1/hubs/{quote(hub, safe='')}/projects/{quote(pid, safe='')}/topFolders").json()
        return [{"id": d["id"], "name": d["attributes"].get("displayName") or d["attributes"].get("name", "")}
                for d in j.get("data", [])]

    def child_folders(self, pid, folder_id):
        """Subcarpetas directas de una carpeta -> [{id, name}]"""
        out, url = [], f"/data/v1/projects/{pid}/folders/{quote(folder_id, safe='')}/contents?filter[type]=folders&page[limit]=200"
        while url:
            j = self.req("GET", url).json()
            for d in j.get("data", []):
                if d["type"] == "folders":
                    a = d["attributes"]
                    out.append({"id": d["id"], "name": a.get("displayName") or a.get("name", "")})
            url = (j.get("links", {}).get("next") or {}).get("href")
        return out

    def list_files(self, pid, folder_id, path="", recursive=True):
        """Genera un dict por archivo bajo la carpeta:
        name, path, last_modified, item_id, version_urn, version_number,
        added_by (quien subio la version = 'Version added by'), updated_by ('Updated by')."""
        url = f"/data/v1/projects/{pid}/folders/{quote(folder_id, safe='')}/contents?page[limit]=200"
        while url:
            j = self.req("GET", url).json()
            inc = {i["id"]: i for i in j.get("included", [])}
            for d in j.get("data", []):
                a = d.get("attributes", {})
                nm = a.get("displayName") or a.get("name", "")
                if d["type"] == "folders":
                    if recursive:
                        yield from self.list_files(pid, d["id"], f"{path}/{nm}", True)
                elif d["type"] == "items":
                    tip_id = ((d.get("relationships", {}).get("tip") or {}).get("data") or {}).get("id")
                    v = inc.get(tip_id, {}).get("attributes", {}) if tip_id else {}
                    yield {"name": nm, "path": path,
                           "last_modified": v.get("lastModifiedTime") or a.get("lastModifiedTime"),
                           "item_id": d["id"], "version_urn": tip_id,
                           "version_number": v.get("versionNumber"),
                           "added_by": v.get("createUserName") or a.get("createUserName"),
                           "updated_by": a.get("lastModifiedUserName") or v.get("lastModifiedUserName")}
            url = (j.get("links", {}).get("next") or {}).get("href")

    def tip_version_urn(self, pid, item_id):
        j = self.req("GET", f"/data/v1/projects/{pid}/items/{quote(item_id, safe='')}/tip").json()
        return j["data"]["id"]

    def download_version(self, pid, version_urn):
        """Descarga los bytes de una version (para leer metadatos de un PDF)."""
        v = self.req("GET", f"/data/v1/projects/{pid}/versions/{quote(version_urn, safe='')}").json()
        sid = v["data"]["relationships"]["storage"]["data"]["id"]
        m = re.match(r"urn:adsk\.objects:os\.object:([^/]+)/(.+)$", sid)
        if not m:
            raise APSError(f"Storage inesperado: {sid}")
        bucket, obj = m.groups()
        s = self.req("GET", f"/oss/v2/buckets/{bucket}/objects/{quote(obj, safe='')}/signeds3download?minutesExpiration=10").json()
        url = s.get("url") or s["urls"][0]
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        return r.content

    # -- Model Derivative --------------------------------------------
    @staticmethod
    def b64(urn):
        return base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")

    def ensure_translated(self, urn_b64, forzar_2d=False):
        """forzar_2d=True lanza (o relanza, con x-ads-force) una traduccion pidiendo
        explicitamente vistas 2D -- necesario porque muchos modelos ya llegan con un
        manifest 'success' generado automaticamente al abrirlos en el visor de ACC, pero
        ESE derivado suele ser solo 3D (outputType 'svf', sin ninguna vista role='2d').
        Ver ese caso no es un 404 de manifest, asi que sin este flag nunca se relanzaria."""
        r = self.req("GET", f"/modelderivative/v2/designdata/{urn_b64}/manifest", ok=(200, 404))
        if r.status_code == 404 or forzar_2d:
            # SVF2 no soporta vistas 2D para muchos disenos de Revit (la API responde 406
            # "SVF2 is not supported for this design"). Las hojas/planos SIEMPRE se piden en
            # formato SVF clasico; SVF2 solo se pide ademas para 3D si aun no existe.
            formatos = [{"type": "svf", "views": ["2d"]}]
            if r.status_code == 404:
                formatos.append({"type": "svf2", "views": ["3d"]})
            log.info("  ...lanzando traduccion (formatos: %s)%s", formatos,
                     " [forzada: el derivado existente no tenia 2D]" if forzar_2d and r.status_code != 404 else "")
            headers = {"x-ads-force": "true"} if r.status_code == 200 else {}
            self.req("POST", "/modelderivative/v2/designdata/job", ok=(200, 201), headers=headers,
                     json={"input": {"urn": urn_b64}, "output": {"formats": formatos}})
            return "pending"
        return r.json().get("status", "unknown")

    def _esperar_traduccion(self, u, wait_seconds, forzar_2d=False):
        status = self.ensure_translated(u, forzar_2d=forzar_2d)
        t0 = time.time()
        while status in ("pending", "inprogress"):
            if time.time() - t0 > wait_seconds:
                raise APSError("Traduccion aun en proceso; se reintentara en la siguiente corrida")
            log.info("  ...traduciendo modelo en la nube (%ds transcurridos, limite %ds)", int(time.time() - t0), wait_seconds)
            time.sleep(20)
            status = self.ensure_translated(u)
        if status != "success":
            raise APSError(f"Traduccion del modelo en estado '{status}'")

    def _metadata(self, u, wait_seconds):
        t1 = time.time()
        while True:
            r = self.req("GET", f"/modelderivative/v2/designdata/{u}/metadata", ok=(200, 202))
            if r.status_code == 200:
                return r.json()["data"]["metadata"]
            if time.time() - t1 > wait_seconds:
                raise APSError("El listado de vistas (metadata) no quedo listo a tiempo; se reintentara en la siguiente corrida")
            log.info("  ...esperando listado de vistas (%ds transcurridos, limite %ds)", int(time.time() - t1), wait_seconds)
            time.sleep(10)

    def views_2d(self, version_urn, wait_seconds=600, solo_hojas=True):
        """Nombres de las HOJAS (Sheets) del modelo -- NO vistas sueltas (plantas, cortes,
        detalles que no esten colocados en una hoja). El metadata trae todos los viewables
        2D (role == '2d'), que incluyen tanto hojas como vistas; para quedarnos solo con
        hojas reales se verifica que el viewable tenga propiedades propias de una Sheet
        ('Sheet Number' / 'Sheet Name'), que las vistas sueltas no tienen.
        Si el modelo ya estaba traducido pero SIN vistas 2D (derivado solo 3D, comun cuando
        alguien lo abrio antes en el visor de ACC), se relanza la traduccion pidiendo 2D.
        solo_hojas=False restaura el comportamiento anterior (todos los viewables 2D)."""
        u = self.b64(version_urn)
        self._esperar_traduccion(u, wait_seconds)
        viewables = [v for v in self._metadata(u, wait_seconds) if v.get("role") == "2d"]
        if not viewables:
            log.info("  ...el modelo no tenia vistas 2D traducidas; relanzando traduccion forzando 2D")
            self._esperar_traduccion(u, wait_seconds, forzar_2d=True)
            viewables = [v for v in self._metadata(u, wait_seconds) if v.get("role") == "2d"]
        if not solo_hojas:
            return [v["name"] for v in viewables]
        return [v["name"] for v in viewables if self._es_hoja(u, v["guid"])]

    def _es_hoja(self, urn_b64, guid):
        """True si el viewable 2D es una Sheet real (trae 'Sheet Number'/'Sheet Name' en sus
        propiedades). En la respuesta del Model Derivative, 'properties' viene agrupado por
        CATEGORIA (p.ej. 'Identity Data'), y 'Sheet Number'/'Sheet Name' son claves DENTRO de
        esa categoria, no de primer nivel -- por eso se revisan los dos niveles.
        Si el endpoint falla o no se puede determinar, se asume que SI es hoja (mejor incluir
        de mas que perder un plano real por un error de API)."""
        try:
            r = self.req("GET", f"/modelderivative/v2/designdata/{urn_b64}/metadata/{quote(guid, safe='')}/properties",
                         ok=(200, 202))
            if r.status_code != 200:
                return True
            props = r.json().get("data", {}).get("collection", [])
            objetivo = {"sheet number", "sheet name"}
            for obj in props:
                categorias = obj.get("properties", {})
                if not isinstance(categorias, dict):
                    continue
                for cat_val in categorias.values():
                    if isinstance(cat_val, dict) and objetivo & {k.strip().lower() for k in cat_val.keys()}:
                        return True
                # por si alguna traduccion trae las propiedades sin agrupar por categoria
                if objetivo & {k.strip().lower() for k in categorias.keys()}:
                    return True
            return False
        except APSError:
            return True


DEFAULT_SHEET_REGEX = r"^\s*(?P<num>.+?)\s+-\s+(?P<name>.+?)\s*$"


def split_sheet_view_name(view_name, regex=DEFAULT_SHEET_REGEX):
    """'A-101 - Planta baja' -> ('A-101', 'Planta baja'). Sin patron: (nombre, '')."""
    m = re.match(regex, view_name)
    return (m.group("num").strip(), m.group("name").strip()) if m else (view_name.strip(), "")
