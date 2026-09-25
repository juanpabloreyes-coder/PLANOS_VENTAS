// SheetSync.cs
// Add-in de Revit (corre DENTRO de Revit, en la maquina de cada integrante -- no en la nube).
// Objetivo: cada vez que alguien hace "Sync to Central" con exito, escribe un .json local con la
// lista de hojas (ViewSheet) del modelo en ese momento. El pipeline Python (plano_sync) lee ese
// .json en vez de llamar a Model Derivative/Design Automation -- mismo resultado, sin consumir
// Cloud Credits de APS, y ademas ve el estado real de sincronizacion (no solo lo publicado).
//
// Si un modelo todavia no tiene .json (porque nadie con el add-in instalado lo ha sincronizado
// desde que se instalo), plano_sync sigue usando el metodo anterior (Model Derivative / Design
// Automation) automaticamente -- no hay que cambiar nada mas para que el pipeline siga funcionando
// igual que ahora mientras se instala el add-in en cada equipo.
//
// Requiere (para compilar, en una maquina CON Visual Studio y Revit instalado):
//   - Referencias: RevitAPI.dll, RevitAPIUI.dll (de la instalacion local de Revit)
//   - Target framework: el que pida la version de Revit (Revit 2025 = .NET 8; anteriores = .NET 4.8)
//
// Ver INSTALL.md en esta misma carpeta para compilar e instalar en cada equipo.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;

namespace SheetSync
{
    public class App : IExternalApplication
    {
        public Result OnStartup(UIControlledApplication application)
        {
            application.ControlledApplication.DocumentSynchronizingWithCentral += OnBeforeSync;
            application.ControlledApplication.DocumentSynchronizedWithCentral += OnAfterSync;
            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            application.ControlledApplication.DocumentSynchronizingWithCentral -= OnBeforeSync;
            application.ControlledApplication.DocumentSynchronizedWithCentral -= OnAfterSync;
            return Result.Succeeded;
        }

        // Solo lo usamos para saber que un sync arranco (diagnostico); el trabajo real pasa en
        // DocumentSynchronizedWithCentral, que solo dispara si el sync termino con exito.
        private void OnBeforeSync(object sender, DocumentSynchronizingWithCentralEventArgs e) { }

        private void OnAfterSync(object sender, DocumentSynchronizedWithCentralEventArgs e)
        {
            try
            {
                if (e.Status != RevitAPIEventStatus.Succeeded) return;

                var doc = e.Document;
                if (doc == null || doc.IsFamilyDocument) return;

                ExportarHojas(doc);
            }
            catch
            {
                // Nunca interrumpir el flujo normal de Revit por un fallo de este add-in.
            }
        }

        private void ExportarHojas(Document doc)
        {
            var carpeta = ResolverCarpetaLog(doc);
            if (carpeta == null) return; // config.txt no encontrado o carpeta no accesible -- no hace nada

            var hojas = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(vs => !vs.IsTemplate)
                .OrderBy(vs => vs.SheetNumber, StringComparer.OrdinalIgnoreCase)
                .Select(vs => new { numero = vs.SheetNumber ?? "", nombre = vs.Name ?? "" })
                .ToList();

            var modelo = Path.GetFileNameWithoutExtension(doc.Title ?? "modelo");
            var nombreArchivo = Sanitizar(modelo) + ".json";
            var ruta = Path.Combine(carpeta, nombreArchivo);

            var sb = new StringBuilder();
            sb.Append("{");
            sb.Append("\"modelo\":").Append(JsonString(modelo)).Append(",");
            sb.Append("\"sincronizado_en\":").Append(JsonString(DateTime.Now.ToString("o"))).Append(",");
            sb.Append("\"usuario\":").Append(JsonString(Environment.UserName)).Append(",");
            sb.Append("\"maquina\":").Append(JsonString(Environment.MachineName)).Append(",");
            sb.Append("\"hojas\":[");
            for (int i = 0; i < hojas.Count; i++)
            {
                sb.Append("{\"numero\":").Append(JsonString(hojas[i].numero))
                  .Append(",\"nombre\":").Append(JsonString(hojas[i].nombre)).Append("}");
                if (i < hojas.Count - 1) sb.Append(",");
            }
            sb.Append("]}");

            // Escritura atomica (a un .tmp y luego reemplazo) para que plano_sync nunca lea un
            // archivo a medio escribir si corre justo en ese instante.
            var tmp = ruta + ".tmp";
            File.WriteAllText(tmp, sb.ToString(), new UTF8Encoding(false));
            File.Copy(tmp, ruta, overwrite: true);
            File.Delete(tmp);
        }

        // La carpeta de destino se lee de un archivo "sheetsync-config.txt" (una sola linea con la
        // ruta) que debe vivir junto al .addin, dentro de %AppData%\Autodesk\Revit\Addins\<version>\.
        // Asi cada usuario la configura una vez al instalar, sin tocar el codigo.
        private string ResolverCarpetaLog(Document doc)
        {
            try
            {
                var addinDir = Path.GetDirectoryName(typeof(App).Assembly.Location);
                var cfgPath = Path.Combine(addinDir ?? "", "sheetsync-config.txt");
                if (!File.Exists(cfgPath)) return null;

                var carpeta = File.ReadAllText(cfgPath).Trim();
                if (string.IsNullOrEmpty(carpeta)) return null;

                if (!Directory.Exists(carpeta))
                    Directory.CreateDirectory(carpeta);

                return carpeta;
            }
            catch
            {
                return null;
            }
        }

        private static string Sanitizar(string s)
        {
            foreach (var c in Path.GetInvalidFileNameChars())
                s = s.Replace(c, '_');
            return s;
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
