// Interis.exe – starts the portable Interis (runtime\pythonw.exe -m interis.desktop).
//
// Deliberately tiny: no dependencies, compiled with the C# compiler that ships with
// Windows (.NET Framework 4.8), so the exe contains nothing but these lines.
// It finds the runtime relative to its own location, so the folder can live anywhere
// (other drive, USB stick).

using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Interis")]
[assembly: System.Reflection.AssemblyProduct("Interis")]
[assembly: System.Reflection.AssemblyDescription("Interviews transkribieren und vergleichen – lokal und offline")]

static class Launcher
{
    [STAThread]
    static int Main()
    {
        string home = Path.GetDirectoryName(Application.ExecutablePath);
        string pythonw = Path.Combine(home, "runtime", "pythonw.exe");
        if (!File.Exists(pythonw))
        {
            MessageBox.Show("Die Laufzeitumgebung fehlt:\n" + pythonw +
                            "\n\nBitte den kompletten Interis-Ordner kopieren.",
                            "Interis", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var psi = new ProcessStartInfo(pythonw, "-I -m interis.desktop")
        {
            UseShellExecute = false,
            WorkingDirectory = home,
        };
        // -I (isolated): ignores PYTHON* variables and the user site directory, so nothing
        // outside this folder can inject code into Interis.
        psi.EnvironmentVariables["INTERIS_HOME"] = home;
        Process.Start(psi);
        return 0;
    }
}
