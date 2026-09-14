@echo off

:: 检查 PATH 中是否存在 lazbuild.exe
where lazbuild.exe >nul 2>&1
if errorlevel 1 (
    echo 在系统环境参数里面,设置一个Lazarus的路径就可以编译了
    echo 错误：未找到 lazbuild.exe，请确保 Lazarus 已安装，并将 lazbuild.exe 所在目录添加到 PATH 环境变量中。
    pause
    exit /b
)

lazbuild.exe -B .\llm_tools\llm_tool.lpi
lazbuild.exe -B .\pascal_c_to_mcp\code_decl_to_mcp.lpi

echo 所有项目编译完成。
timeout /t 5 /nobreak >nul
