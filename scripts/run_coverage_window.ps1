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
Set-Location 'D:\zhoutianjie\Desktop\pg-mcp'
Write-Host '>>> Running test suite with coverage report...' -ForegroundColor Cyan
uv run pytest tests/unit 'tests/e2e/test_mcp.py::TestMCPServer::test_lifespan_initialization' 'tests/e2e/test_mcp.py::TestMCPServer::test_query_tool_invalid_return_type' 'tests/e2e/test_mcp.py::TestMCPServer::test_query_tool_empty_question' 'tests/e2e/test_mcp.py::TestMCPServerErrors::test_query_before_initialization' 'tests/e2e/test_mcp.py::TestMCPServerErrors::test_malformed_question_handling' --cov=src --cov-report=term -q
New-Item -Force -Path 'D:\zhoutianjie\Desktop\pg-mcp\verify_screenshots\_stage_cov.done' | Out-Null
Start-Sleep -Seconds 900
