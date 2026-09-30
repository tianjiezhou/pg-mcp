param([string]$OutPath = "", [switch]$Release)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
}
"@

$proc = Get-Process | Where-Object { $_.MainWindowTitle -eq 'pg-mcp-verify' } | Select-Object -First 1
if (-not $proc -or $proc.MainWindowHandle -eq 0) { Write-Host 'ERROR: pg-mcp-verify window not found'; exit 1 }
$hwnd = $proc.MainWindowHandle

if ($Release) {
    [Win32]::SetWindowPos($hwnd, [IntPtr](-2), 0, 0, 1300, 760, 0x0040) | Out-Null
    [Win32]::ShowWindow($hwnd, 6) | Out-Null
    Write-Host 'released topmost and minimized'
    exit 0
}

# Restore, then force the console topmost and screen-sized so the
# capture can only contain the verification console (no desktop apps).
[Win32]::ShowWindow($hwnd, 9) | Out-Null
for ($i = 0; $i -lt 8; $i++) {
    [Win32]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 1920, 1040, 0x0040) | Out-Null
    [Win32]::SetForegroundWindow($hwnd) | Out-Null
    Start-Sleep -Milliseconds 600
}

$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
Write-Host ("saved " + $OutPath + " " + $bounds.Width + "x" + $bounds.Height + " (window stays topmost until -Release)")
