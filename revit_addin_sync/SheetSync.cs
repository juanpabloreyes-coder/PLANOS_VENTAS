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
// PROYECTO DE MODELOS CON NOMBRE REPETIDO (p.ej. "12_ARQ_NAVE.rvt" existe tanto en GRANJAS JESSY
// como en GONVAUTO F2): Revit no expone de forma confiable en que proyecto de ACC vive un modelo
// en la nube con solo mirar el archivo (ni la ruta visible ni el GUID interno del modelo sirven --
// ya se probaron y descartaron). Para esos casos, plano_sync (Python) escribe en la carpeta
// compartida un archivo "_modelos_duplicados.json" con los proyectos candidatos por nombre de
// modelo; cuando alguien sincroniza uno de esos modelos por primera vez, este add-in le pregunta
// (una sola vez POR MODELO, no por sincronizacion) a cual proyecto pertenece, y guarda la
// respuesta en "_confirmaciones_proyecto.json" (tambien compartido, ligada al GUID del modelo) --
// asi que en cuanto UNA persona confirma, todos los demas se benefician sin que les vuelva a
// preguntar. Python, del lado suyo, siempre revalida que el proyecto que dice el .json coincida
// con el que ya sabe por la API antes de confiar en el -- un error humano en el desplegable como
// mucho hace que ese modelo puntual no use el atajo del add-in esa vez, nunca mezcla datos.
//
// IDENTIDAD POR URN (desde 2026-09-29): si el modelo esta en la nube, el .json se nombra
// "urn_<id de linaje>.json" e incluye model_urn / project_id / hub_id de ACC. PLANOS busca cada
// modelo de VENTAS por su URN, asi que modelos de otros proyectos de ACC con el mismo nombre ya no
// pueden mezclarse, y la pregunta de "a que proyecto pertenece" ya no aparece para esos modelos.
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
using System.Text.Json;
using WinForm = System.Windows.Forms.Form;
using WinLabel = System.Windows.Forms.Label;
using WinComboBox = System.Windows.Forms.ComboBox;
using WinComboBoxStyle = System.Windows.Forms.ComboBoxStyle;
using WinButton = System.Windows.Forms.Button;
using WinFormStartPosition = System.Windows.Forms.FormStartPosition;
using WinFormBorderStyle = System.Windows.Forms.FormBorderStyle;
using WinDialogResult = System.Windows.Forms.DialogResult;
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

            var carpetaCompartida = ResolverCarpetaCompartida() ?? carpeta;
            var modelo = Path.GetFileNameWithoutExtension(doc.Title ?? "modelo");
            var modelGuid = ObtenerModelGuid(doc);

            // Identidad del modelo en ACC (mismo metodo que RevitSyncLogger): URN del archivo y
            // proyecto/hub de ACC. Con el URN, el archivo se nombra "urn_<id>.json": es unico, asi
            // que un modelo de OTRO proyecto de ACC con el mismo nombre nunca pisa uno de VENTAS,
            // y ya no hace falta preguntar a que proyecto pertenece.
            var modelUrn = TryGetString(doc, "GetCloudModelUrn");
            var projectId = TryGetString(doc, "GetProjectId");
            var hubId = TryGetString(doc, "GetHubId");
            var idLinaje = IdLinaje(modelUrn);

            string proyecto, nombreArchivo;
            if (idLinaje != null)
            {
                proyecto = null;
                nombreArchivo = "urn_" + Sanitizar(idLinaje) + ".json";
            }
            else
            {
                // Sin URN (modelo no en la nube o API no disponible): comportamiento anterior.
                proyecto = ResolverProyecto(carpetaCompartida, modelo, modelGuid);
                nombreArchivo = (proyecto != null ? Sanitizar(proyecto) + "__" : "") + Sanitizar(modelo) + ".json";
            }
            var ruta = Path.Combine(carpeta, nombreArchivo);

            var sb = new StringBuilder();
            sb.Append("{");
            sb.Append("\"modelo\":").Append(JsonString(modelo)).Append(",");
            sb.Append("\"proyecto\":").Append(JsonString(proyecto)).Append(",");
            sb.Append("\"model_guid\":").Append(JsonString(modelGuid)).Append(",");
            sb.Append("\"model_urn\":").Append(JsonString(modelUrn)).Append(",");
            sb.Append("\"project_id\":").Append(JsonString(projectId)).Append(",");
            sb.Append("\"hub_id\":").Append(JsonString(hubId)).Append(",");
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

        // GUID del modelo en la nube (identidad del archivo, estable aunque se renombre). Se usa
        // como llave para recordar la respuesta del desplegable sin volver a preguntar cada vez.
        // Devuelve null si el modelo no es un modelo en la nube (worksharing local o no soportado).
        private string ObtenerModelGuid(Document doc)
        {
            try
            {
                if (!doc.IsWorkshared) return null;
                var centralPath = doc.GetWorksharingCentralModelPath();
                if (centralPath == null) return null;
                if (!centralPath.CloudPath) return null;
                return centralPath.GetModelGUID().ToString();
            }
            catch
            {
                return null;
            }
        }

        // Decide el "proyecto" a escribir en el .json de este modelo:
        //   - Si el nombre del modelo no esta en "_modelos_duplicados.json" (no es ambiguo), no
        //     hace falta proyecto -- devuelve null como siempre (Python no lo necesita).
        //   - Si esta duplicado y ya hay una respuesta confirmada para este model_guid en
        //     "_confirmaciones_proyecto.json", la usa sin preguntar.
        //   - Si esta duplicado y no hay confirmacion (o no se pudo determinar el model_guid, en
        //     cuyo caso no podriamos recordar la respuesta de forma confiable), pregunta con un
        //     desplegable limitado a los proyectos candidatos reales. Si la persona cancela, se
        //     guarda sin proyecto (Python simplemente no usara el add-in para ese modelo esa vez).
        private string ResolverProyecto(string carpeta, string nombreModelo, string modelGuid)
        {
            try
            {
                var candidatos = LeerCandidatos(carpeta, nombreModelo);
                if (candidatos == null || candidatos.Count == 0) return null; // nombre no ambiguo

                if (modelGuid != null)
                {
                    var confirmaciones = LeerConfirmaciones(carpeta);
                    if (confirmaciones.TryGetValue(modelGuid, out var yaConfirmado) &&
                        candidatos.Contains(yaConfirmado))
                    {
                        return yaConfirmado;
                    }
                }

                var elegido = PreguntarProyecto(nombreModelo, candidatos);
                if (elegido != null && modelGuid != null)
                {
                    GuardarConfirmacion(carpeta, modelGuid, elegido);
                }
                return elegido;
            }
            catch
            {
                return null;
            }
        }

        // Lee "_modelos_duplicados.json" -- {"NOMBRE_MODELO": ["Proyecto A", "Proyecto B"], ...} --
        // que escribe plano_sync (collect.py) en cada corrida. Devuelve null si el modelo no
        // aparece ahi (no es ambiguo) o el archivo no existe todavia.
        private List<string> LeerCandidatos(string carpeta, string nombreModelo)
        {
            var ruta = Path.Combine(carpeta, "_modelos_duplicados.json");
            if (!File.Exists(ruta)) return null;
            using var doc = JsonDocument.Parse(File.ReadAllText(ruta));
            if (!doc.RootElement.TryGetProperty(nombreModelo, out var arr)) return null;
            return arr.EnumerateArray().Select(x => x.GetString()).Where(s => s != null).ToList();
        }

        // Lee "_confirmaciones_proyecto.json" -- {"model_guid": "Proyecto", ...} -- que este mismo
        // add-in va llenando conforme la gente confirma. Compartido entre todos (vive en la misma
        // carpeta que los .json de hojas), asi que una sola confirmacion sirve para todos.
        private Dictionary<string, string> LeerConfirmaciones(string carpeta)
        {
            var ruta = Path.Combine(carpeta, "_confirmaciones_proyecto.json");
            if (!File.Exists(ruta)) return new Dictionary<string, string>();
            try
            {
                return JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(ruta))
                       ?? new Dictionary<string, string>();
            }
            catch
            {
                return new Dictionary<string, string>();
            }
        }

        private void GuardarConfirmacion(string carpeta, string modelGuid, string proyecto)
        {
            var ruta = Path.Combine(carpeta, "_confirmaciones_proyecto.json");
            // Reintenta un par de veces por si otra persona esta escribiendo el mismo archivo al
            // mismo tiempo (poco probable, pero la carpeta es compartida).
            for (int intento = 0; intento < 3; intento++)
            {
                try
                {
                    var actual = LeerConfirmaciones(carpeta);
                    actual[modelGuid] = proyecto;
                    var tmp = ruta + ".tmp";
                    File.WriteAllText(tmp, JsonSerializer.Serialize(actual), new UTF8Encoding(false));
                    File.Copy(tmp, ruta, overwrite: true);
                    File.Delete(tmp);
                    return;
                }
                catch
                {
                    System.Threading.Thread.Sleep(300);
                }
            }
        }

        // Ventana simple: nombre del modelo + lista de proyectos candidatos (nunca texto libre,
        // para minimizar errores de dedo). Devuelve null si la persona cierra/cancela.
        private string PreguntarProyecto(string nombreModelo, List<string> candidatos)
        {
            using var form = new WinForm
            {
                Text = "SheetSync -- confirmar proyecto",
                Width = 420,
                Height = 200,
                StartPosition = WinFormStartPosition.CenterScreen,
                FormBorderStyle = WinFormBorderStyle.FixedDialog,
                MaximizeBox = false,
                MinimizeBox = false,
                TopMost = true,
            };

            var label = new WinLabel
            {
                Text = $"El modelo \"{nombreModelo}\" existe en mas de un proyecto.\n" +
                       "¿A cual proyecto pertenece ESTE archivo?\n" +
                       "(Solo se pregunta una vez por modelo.)",
                Left = 15,
                Top = 15,
                Width = 380,
                Height = 60,
            };

            var combo = new WinComboBox
            {
                Left = 15,
                Top = 80,
                Width = 380,
                DropDownStyle = WinComboBoxStyle.DropDownList,
            };
            combo.Items.AddRange(candidatos.Cast<object>().ToArray());
            combo.SelectedIndex = 0;

            var btnOk = new WinButton { Text = "Aceptar", Left = 220, Top = 120, Width = 80, DialogResult = WinDialogResult.OK };
            var btnCancel = new WinButton { Text = "Cancelar", Left = 310, Top = 120, Width = 85, DialogResult = WinDialogResult.Cancel };

            form.Controls.Add(label);
            form.Controls.Add(combo);
            form.Controls.Add(btnOk);
            form.Controls.Add(btnCancel);
            form.AcceptButton = btnOk;
            form.CancelButton = btnCancel;

            var resultado = form.ShowDialog();
            if (resultado != WinDialogResult.OK) return null;
            return combo.SelectedItem as string;
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

        // Carpeta COMPARTIDA entre SheetSync (PLANOS_VENTAS) y RevitSyncLogger (PUBLICACIONES_VENTAS)
        // para "_modelos_duplicados.json" y "_confirmaciones_proyecto.json" -- asi una respuesta dada
        // en cualquiera de los dos add-ins sirve para ambos, en vez de preguntar dos veces por el
        // mismo modelo. Se lee de "carpeta-compartida-config.txt" (mismo mecanismo que
        // sheetsync-config.txt), escrito por Instalador\instalar.bat. Si no existe (instalador viejo,
        // sin actualizar), se usa la carpeta de logs propia como respaldo -- igual que se comportaba
        // antes de este cambio.
        private string ResolverCarpetaCompartida()
        {
            try
            {
                var addinDir = Path.GetDirectoryName(typeof(App).Assembly.Location);
                var cfgPath = Path.Combine(addinDir ?? "", "carpeta-compartida-config.txt");
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

        // Mismo metodo que RevitSyncLogger: llama por reflexion a Document.GetCloudModelUrn(),
        // GetProjectId() y GetHubId() (existen en modelos en la nube). "" si no aplica.
        private static string TryGetString(Document document, string methodName)
        {
            try
            {
                return document.GetType().GetMethod(methodName,
                           System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public)
                    ?.Invoke(document, null)?.ToString() ?? "";
            }
            catch
            {
                return "";
            }
        }

        // "urn:adsk.wipprod:dm.lineage:ABC?x" -> "ABC". null si no es un URN de linaje.
        private static string IdLinaje(string urn)
        {
            if (string.IsNullOrEmpty(urn)) return null;
            var i = urn.IndexOf("dm.lineage:", StringComparison.OrdinalIgnoreCase);
            if (i < 0) return null;
            var id = urn.Substring(i + "dm.lineage:".Length);
            var q = id.IndexOf('?');
            if (q >= 0) id = id.Substring(0, q);
            return id.Length > 0 ? id : null;
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
