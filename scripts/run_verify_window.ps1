$host.UI.RawUI.WindowTitle = 'pg-mcp-verify'
try {
    $buf = $host.UI.RawUI.BufferSize
    $buf.Width = 250
    $buf.Height = 9999
    $host.UI.RawUI.BufferSize = $buf
    $win = $host.UI.RawUI.WindowSize
    $win.Width = 240
    $win.Height = 56
    $host.UI.RawUI.WindowSize = $win
} catch { }
chcp 936 | Out-Null
$env:PYTHONIOENCODING = 'gbk'
$env:PGMCP_CONSOLE_GATE = '1'
Set-Location 'D:\zhoutianjie\Desktop\pg-mcp'
Write-Host '>>> Running MCP feature verification (window stays open, gated per stage)...' -ForegroundColor Cyan
uv run python scripts\verify_mcp_features.py
Start-Sleep -Seconds 5
