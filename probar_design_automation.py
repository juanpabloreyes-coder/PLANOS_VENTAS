"""Prueba manual y desechable: corre extraer_hojas() (Design Automation) contra un modelo
real, para validar que el AppBundle/Activity publicados funcionan de punta a punta.

Uso:
  python probar_design_automation.py "GRANJAS JESSY" "12_ARQ_NAVE.rvt"

(nombre de proyecto tal como aparece en ACC, y nombre exacto del archivo .rvt -- basta con que
el nombre dado este contenido en el nombre real, no hace falta que sea identico).
"""
import sys

from plano_sync.__main__ import _cfg, _aps
from plano_sync import collect, design_automation as da


def main():
    if len(sys.argv) != 3:
        sys.exit('Uso: python probar_design_automation.py "<proyecto>" "<nombre_o_parte_del_archivo.rvt>"')
    proyecto_buscado, nombre_buscado = sys.argv[1].lower(), sys.argv[2].lower()

    cfg = _cfg("config.json")
    aps = _aps(cfg)

    print("Recorriendo ACC (puede tardar un poco)...")
    archivos, pid, avisos = collect.recorrer_proyecto(aps, cfg)
    for w in avisos:
        print("AVISO:", w)

    candidatos = [
        f for f in archivos
        if f["name"].lower().endswith(".rvt")
        and proyecto_buscado in f["proyecto"].lower()
        and nombre_buscado in f["name"].lower()
    ]
    if not candidatos:
        sys.exit(f"No encontre ningun .rvt que coincida con proyecto={proyecto_buscado!r} nombre={nombre_buscado!r}")

    m = candidatos[0]
    print(f"\nUsando: {m['proyecto']} / {m['name']}")
    print("Lanzando WorkItem de Design Automation (puede tardar varios minutos, el motor de Revit"
          " tiene que arrancar en la nube)...")

    hojas = da.extraer_hojas(aps, pid, m["version_urn"], cfg)

    print(f"\n{len(hojas)} hoja(s) encontradas:")
    for h in hojas[:30]:
        print(" ", h)


if __name__ == "__main__":
    main()
