pyinstaller --onefile `
    --collect-all fastmcp `
    --collect-all pydantic `
    --collect-all tzdata `
    --hidden-import language_middleware `
    --paths . `
    --add-data "lingofuse;lingofuse" `
    mcp_server.py

pyinstaller --onefile `
    --name mcp_proxy `
    --clean `
    --noconfirm `
    mcp_proxy.py
