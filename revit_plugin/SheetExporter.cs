// SheetExporter.cs
// Plugin de Revit que corre DENTRO de Autodesk Design Automation (nube, sin interfaz grafica).
// Objetivo: abrir un .rvt, listar sus HOJAS (ViewSheet) reales -- Sheet Number, Sheet Name --
// SIN que le afecten los vinculos faltantes (a diferencia del Model Derivative / SVF2, esto usa
// la API nativa de Revit, que no necesita resolver geometria de vinculos externos para leer la
// lista de hojas del modelo host).
//
// Requiere (para compilar, en una maquina CON Visual Studio y Revit instalado):
//   - Referencias: RevitAPI.dll, RevitAPIUI.dll (de la instalacion local de Revit, ej.
//     C:\Program Files\Autodesk\Revit 2025\)
//   - Paquete NuGet: DesignAutomationBridge (o Autodesk.Forge.DesignAutomation.Revit segun la
//     version del SDK) -- trae el tipo DesignAutomationData / DesignAutomationReadyEventArgs.
//   - Target framework: el que pida la version de Revit (Revit 2025 = .NET 8 / .NET Core;
//     versiones anteriores usan .NET Framework 4.8).
//
// Ver build_and_deploy.md en esta misma carpeta para el resto del proceso (empaquetar como
// AppBundle, subirlo a APS, crear la Activity, y como el pipeline Python lo dispara).

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.ExtensibleStorage;
using DesignAutomationFramework;

namespace SheetExporter
{
    public class App : IExternalDBApplication
    {
        public ExternalDBApplicationResult OnStartup(ControlledApplication application)
        {
            DesignAutomationBridge.DesignAutomationReadyEvent += HandleDesignAutomationReadyEvent;
            return ExternalDBApplicationResult.Succeeded;
        }

        public ExternalDBApplicationResult OnShutdown(ControlledApplication application)
        {
            return ExternalDBApplicationResult.Succeeded;
        }

        private void HandleDesignAutomationReadyEvent(object sender, DesignAutomationReadyEventArgs e)
        {
            // e.Succeeded controla si Design Automation considera el WorkItem exitoso al terminar.
            e.Succeeded = true;
            try
            {
                ExportSheets(e.DesignAutomationData.RevitDoc);
            }
            catch (Exception ex)
            {
                // Nunca lanzar: si algo falla, escribimos el error al JSON de salida en vez de
                // tronar el WorkItem sin explicacion. Asi el pipeline Python siempre recibe un
                // archivo interpretable.
                e.Succeeded = false;
                WriteError(ex);
            }
        }

        private void ExportSheets(Document doc)
        {
            if (doc == null)
                throw new InvalidOperationException("Design Automation no entrego un documento abierto (RevitDoc es null).");

            // Coleccion SIN NINGUN filtro todavia -- diagnostico: cuantas ViewSheet hay en total
            // en el documento (incluye templates y placeholders de coordinacion multidisciplina),
            // para poder comparar contra lo que realmente se exporta mas abajo.
            var todasLasHojas = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();

            var hojas = new List<Dictionary<string, string>>();
            var sheets = todasLasHojas
                .Where(vs => !vs.IsTemplate)
                .OrderBy(vs => vs.SheetNumber, StringComparer.OrdinalIgnoreCase);

            foreach (var vs in sheets)
            {
                bool esPlaceholder = false;
                try { esPlaceholder = vs.IsPlaceholder; } catch { /* propiedad no existe en esta version de la API */ }

                hojas.Add(new Dictionary<string, string>
                {
                    { "numero", vs.SheetNumber ?? "" },
                    { "nombre", vs.Name ?? "" },
                    { "revision_actual", GetParamAsString(vs, BuiltInParameter.SHEET_CURRENT_REVISION) },
                    { "fecha_emision", GetParamAsString(vs, BuiltInParameter.SHEET_ISSUE_DATE) },
                    { "placeholder", esPlaceholder ? "true" : "false" },
                });
            }

            // Diagnostico de worksets: si el documento es workshared y hay worksets cerrados al
            // abrirlo en el entorno headless de Design Automation, sus elementos (hojas incluidas)
            // pueden no cargarse y por lo tanto no aparecer nunca en el FilteredElementCollector.
            var worksets = new List<Dictionary<string, string>>();
            bool workshared = false;
            try
            {
                workshared = doc.IsWorkshared;
                if (workshared)
                {
                    foreach (Workset ws in new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
                    {
                        worksets.Add(new Dictionary<string, string>
                        {
                            { "nombre", ws.Name ?? "" },
                            { "abierto", ws.IsOpen ? "true" : "false" },
                        });
                    }
                }
            }
            catch (Exception exWs)
            {
                worksets.Add(new Dictionary<string, string> { { "error", exWs.Message } });
            }

            var titulo = doc.Title ?? "";
            var pathName = doc.PathName ?? "";

            var json = BuildJson(titulo, pathName, hojas, todasLasHojas.Count, workshared, worksets);
            File.WriteAllText("result.json", json, new UTF8Encoding(false));
        }

        private static string GetParamAsString(Element el, BuiltInParameter bip)
        {
            try
            {
                var p = el.get_Parameter(bip);
                if (p == null) return "";
                return p.StorageType == StorageType.String ? (p.AsString() ?? "") : (p.AsValueString() ?? "");
            }
            catch
            {
                return "";
            }
        }

        private void WriteError(Exception ex)
        {
            var sb = new StringBuilder();
            sb.Append("{\"error\": ").Append(JsonString(ex.Message)).Append(", \"hojas\": []}");
            File.WriteAllText("result.json", sb.ToString(), new UTF8Encoding(false));
        }

        // Serializador JSON minimo, sin dependencias externas (Design Automation para Revit no
        // siempre trae Newtonsoft.Json disponible por defecto en el AppBundle).
        private static string BuildJson(string titulo, string pathName, List<Dictionary<string, string>> hojas,
            int totalViewSheetsEnDoc, bool workshared, List<Dictionary<string, string>> worksets)
        {
            var sb = new StringBuilder();
            sb.Append("{");
            sb.Append("\"modelo\": ").Append(JsonString(titulo)).Append(",");
            sb.Append("\"ruta\": ").Append(JsonString(pathName)).Append(",");
            sb.Append("\"diagnostico\": {");
            sb.Append("\"total_viewsheets_en_doc\": ").Append(totalViewSheetsEnDoc).Append(",");
            sb.Append("\"workshared\": ").Append(workshared ? "true" : "false").Append(",");
            sb.Append("\"worksets\": [");
            for (int i = 0; i < worksets.Count; i++)
            {
                var w = worksets[i];
                sb.Append("{");
                bool first = true;
                foreach (var kv in w)
                {
                    if (!first) sb.Append(",");
                    sb.Append(JsonString(kv.Key)).Append(": ").Append(JsonString(kv.Value));
                    first = false;
                }
                sb.Append("}");
                if (i < worksets.Count - 1) sb.Append(",");
            }
            sb.Append("]},");
            sb.Append("\"hojas\": [");
            for (int i = 0; i < hojas.Count; i++)
            {
                var h = hojas[i];
                sb.Append("{");
                sb.Append("\"numero\": ").Append(JsonString(h["numero"])).Append(",");
                sb.Append("\"nombre\": ").Append(JsonString(h["nombre"])).Append(",");
                sb.Append("\"revision_actual\": ").Append(JsonString(h["revision_actual"])).Append(",");
                sb.Append("\"fecha_emision\": ").Append(JsonString(h["fecha_emision"])).Append(",");
                sb.Append("\"placeholder\": ").Append(h["placeholder"]);
                sb.Append("}");
                if (i < hojas.Count - 1) sb.Append(",");
            }
            sb.Append("]}");
            return sb.ToString();
        }

        private static string JsonString(string s)
        {
            if (s == null) return "null";
            var sb = new StringBuilder("\"");
            foreach (var c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append("\"");
            return sb.ToString();
        }
    }
}
