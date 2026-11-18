using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

internal static class ClanWarsLauncher
{
    private const string Title = "Tribes Rivals: Clan Wars (community mod)";

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr parent, string message, string title, uint options);

    [STAThread]
    private static int Main()
    {
        try
        {
            var runtime = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Client Files");
            var python = Path.Combine(runtime, "python", "pythonw.exe");
            var starter = Path.Combine(runtime, "clan_wars_windows.pyw");
            if (!File.Exists(python) || !File.Exists(starter))
                throw new FileNotFoundException("Extract the entire Clan Wars ZIP before launching.");

            Process.Start(new ProcessStartInfo(python, "-B \"" + starter + "\"")
            {
                UseShellExecute = false,
                WorkingDirectory = runtime
            });
            return 0;
        }
        catch (Exception error)
        {
            MessageBox(IntPtr.Zero, error.Message, Title, 0x10);
            return 1;
        }
    }
}
