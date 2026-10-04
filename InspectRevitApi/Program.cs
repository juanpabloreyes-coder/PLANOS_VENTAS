using System;
using System.Linq;
using System.Reflection;

var dll = @"C:\Program Files\Autodesk\Revit 2025\RevitAPI.dll";
var asm = Assembly.LoadFrom(dll);

Console.WriteLine("== Tipos que contienen 'Cloud' o 'ModelPath' ==");
foreach (var t in asm.GetTypes()
             .Where(t => t.Name.Contains("Cloud") || t.Name.Contains("ModelPath"))
             .OrderBy(t => t.FullName))
{
    Console.WriteLine(t.FullName);
}

Console.WriteLine();
Console.WriteLine("== Miembros publicos de cada uno (metodos/propiedades) ==");
foreach (var t in asm.GetTypes()
             .Where(t => t.Name.Contains("Cloud") || t.Name.Contains("ModelPath"))
             .OrderBy(t => t.FullName))
{
    Console.WriteLine($"\n-- {t.FullName} --");
    foreach (var m in t.GetMembers(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
    {
        Console.WriteLine("   " + m);
    }
}
