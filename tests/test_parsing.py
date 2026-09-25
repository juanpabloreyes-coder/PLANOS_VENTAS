import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from plano_sync.parsing import separar_plano, normalizar_numero, normalizar_nombre, disciplina_por_ruta, extension_permitida
from plano_sync.compare import comparar

CASOS = {
    "A-101 - Planta baja.pdf": ("A-101", "Planta baja"),
    "A101_Planta baja.pdf": ("A101", "Planta baja"),
    "IE-01 Cuadro de cargas.pdf": ("IE-01", "Cuadro de cargas"),
    "IE-01-A Cuadro de cargas.pdf": ("IE-01-A", "Cuadro de cargas"),
    "E-02-1.5 Detalle.pdf": ("E-02-1.5", "Detalle"),
    "01-100-01 Planta.dwg": ("01-100-01", "Planta"),
    "SOLO NOMBRE.pdf": ("SOLO", "NOMBRE"),
}

def test_separar():
    for k, v in CASOS.items():
        assert separar_plano(k) == v, (k, separar_plano(k), v)

def test_normalizar():
    assert normalizar_numero("a-101.") == "A101"
    assert normalizar_nombre("Planta_Baja (Nivel 1)") == "PLANTA BAJA NIVEL 1"
    assert normalizar_nombre("Cimentación") == normalizar_nombre("CIMENTACION")

def test_disciplina_y_ext():
    assert disciplina_por_ruta("/x/01102_ESTRUCTURA/a") == "Estructura"
    assert disciplina_por_ruta("/x/Mecánica") == "Mecanica"
    assert disciplina_por_ruta("/x/zzz") == "Sin clasificar"
    r = {"default": ["pdf"], "DMG": {"default": ["dwg"]}, "S5": {"default": ["pdf"], "Mecanica": ["dwg"]}}
    assert extension_permitida("a.PDF", "X", "Estructura", r)
    assert not extension_permitida("a.pdf", "DMG", "Estructura", r)
    assert extension_permitida("a.dwg", "S5", "Mecanica", r)
    assert not extension_permitida("a.dwg", "S5", "Estructura", r)

def test_comparar():
    rv = [{"proyecto": "P", "numero": "A-1", "nombre": "Planta"}, {"proyecto": "P", "numero": "A-2", "nombre": "Corte"},
          {"proyecto": "P", "numero": "A-9", "nombre": "Sobrante"}]
    fm = [dict(proyecto="P", numero="A1", nombre="PLANTA", archivo="a.pdf", disciplina="X", ruta="", actualizado=None, estado_revision=None),
          dict(proyecto="P", numero="A-2", nombre="Otro", archivo="b.pdf", disciplina="X", ruta="", actualizado=None, estado_revision=None),
          dict(proyecto="P", numero="Z-9", nombre="Corte", archivo="c.pdf", disciplina="X", ruta="", actualizado=None, estado_revision=None),
          dict(proyecto="P", numero="Q-1", nombre="Nada", archivo="d.pdf", disciplina="X", ruta="", actualizado=None, estado_revision=None)]
    c, falt = comparar(fm, rv)
    e = {x["archivo"]: x["estado"] for x in c}
    assert e == {"a.pdf": "Coincide número y nombre", "b.pdf": "Coincide solo número", "c.pdf": "Coincide solo nombre", "d.pdf": "Sin coincidencia"}
    assert [f["numero"] for f in falt] == ["A-9"]

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)

def test_integrantes():
    from plano_sync.integrantes import Clasificador, normalizar
    eq = [{"equipo": "Diseño A", "integrante": "Josseline Márquez", "key": normalizar("Josseline Márquez"), "tokens": set(normalizar("Josseline Márquez").split())},
          {"equipo": "Electrico", "integrante": "Juan Daniel Luevano Vargas", "key": normalizar("Juan Daniel Luevano Vargas"), "tokens": set(normalizar("Juan Daniel Luevano Vargas").split())},
          {"equipo": "Diseño C", "integrante": "Juan Eduardo Castañon Torres", "key": normalizar("Juan Eduardo Castañon Torres"), "tokens": set(normalizar("Juan Eduardo Castañon Torres").split())}]
    c = Clasificador(eq)
    assert c.asignar("JOSSELINE MARQUEZ")[:3] == ("Josseline Márquez", "Diseño A", "exacta")
    assert c.asignar("Juan Eduardo Castanon Torres")[1] == "Diseño C"          # ñ vs n
    assert c.asignar("Juan Daniel Luevano Vargas Ruiz")[2] == "parcial"         # nombre ACC con palabra extra
    assert c.asignar("Alguien Externo")[0] == "Sin integrante asignado"
    assert c.asignar(None)[0] == "Sin integrante asignado"

if __name__ == "__main__":
    test_integrantes(); print("ok test_integrantes")

def test_hoja_de_trabajo():
    from plano_sync.collect import es_hoja_de_trabajo, DEFAULT_HOJA_TRABAJO_PATRONES
    p = DEFAULT_HOJA_TRABAJO_PATRONES
    assert es_hoja_de_trabajo("A-101 - Planta baja_TRABAJO", p)
    assert es_hoja_de_trabajo("A-101 - Planta baja_WIP", p)
    assert es_hoja_de_trabajo("WIP - A-101 - Planta baja", p)
    assert es_hoja_de_trabajo("X - A-101 - Planta baja", p)
    assert not es_hoja_de_trabajo("A-101 - Planta baja", p)
    assert not es_hoja_de_trabajo("EX-101 - Planta baja", p)   # no debe disparar por "X" dentro de otra palabra

if __name__ == "__main__":
    test_hoja_de_trabajo(); print("ok test_hoja_de_trabajo")

def test_comparar_integrante_viene_del_modelo_revit():
    """El integrante/equipo de una fila de la comparativa debe venir de quien trabajo el MODELO
    Revit que hizo match (fila 'rv'), nunca de quien subio el PDF a Forma (campo 'subido_por')."""
    rv = [{"proyecto": "P", "numero": "A-1", "nombre": "Planta", "modelo": "P_A.rvt",
           "integrante": "Ana Diseñadora", "equipo": "Diseño A"},
          {"proyecto": "P", "numero": "A-9", "nombre": "Sin equipo en modelo", "modelo": "P_X.rvt",
           "integrante": "Sin integrante asignado", "equipo": "Sin equipo"}]
    fm = [dict(proyecto="P", numero="A-1", nombre="Planta", archivo="a.pdf", disciplina="X", ruta="",
               actualizado=None, subido_por="Otro Que Subio El PDF"),
          dict(proyecto="P", numero="A-9", nombre="Sin equipo en modelo", archivo="b.pdf", disciplina="X",
               ruta="", actualizado=None, subido_por="Cualquiera"),
          dict(proyecto="P", numero="Z-9", nombre="No existe en Revit", archivo="c.pdf", disciplina="X",
               ruta="", actualizado=None, subido_por="Cualquiera")]
    c, _ = comparar(fm, rv)
    d = {x["archivo"]: x for x in c}
    assert d["a.pdf"]["integrante"] == "Ana Diseñadora" and d["a.pdf"]["equipo"] == "Diseño A"
    assert d["a.pdf"]["modelo_revit"] == "P_A.rvt"
    assert d["b.pdf"]["integrante"] == "Sin integrante asignado"          # autor del modelo no esta en la lista
    assert d["c.pdf"]["integrante"] == "Sin integrante asignado"          # sin match en Revit -> sin integrante
    assert d["c.pdf"]["modelo_revit"] is None

if __name__ == "__main__":
    test_comparar_integrante_viene_del_modelo_revit(); print("ok test_comparar_integrante_viene_del_modelo_revit")
