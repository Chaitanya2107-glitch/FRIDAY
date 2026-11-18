using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

internal static class FridayLauncher
{
    private static bool IsInstallation(string root)
    {
        return File.Exists(Path.Combine(root, @"venv\Scripts\pythonw.exe"))
            && File.Exists(Path.Combine(root, @"interfaces\taskbar\launch.py"))
            && File.Exists(Path.Combine(root, @"island\src-tauri\target\release\friday-island.exe"));
    }

    private static string FindRoot()
    {
        for (var folder = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory);
             folder != null; folder = folder.Parent)
        {
            if (IsInstallation(folder.FullName)) return folder.FullName;
        }
        // shortcut: a copied launcher remembers this installation; rebuild if that installation moves.
        using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("FridayRoot"))
        using (var reader = new StreamReader(stream))
        {
            var root = reader.ReadToEnd().Trim();
            if (IsInstallation(root)) return root;
        }
        throw new FileNotFoundException("FRIDAY's project, Python environment or Island executable is missing. Keep the project installed, or rebuild this launcher after moving it.");
    }

    [STAThread]
    private static int Main()
    {
        try
        {
            var root = FindRoot();
            using (var process = Process.Start(new ProcessStartInfo
            {
                FileName = Path.Combine(root, @"venv\Scripts\pythonw.exe"),
                Arguments = "-B \"" + Path.Combine(root, @"interfaces\taskbar\launch.py") + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            })) { }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show("FRIDAY could not start.\n\n" + error.Message,
                            "FRIDAY", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
