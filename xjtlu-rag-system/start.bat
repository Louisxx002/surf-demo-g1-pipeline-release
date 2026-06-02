@echo off
chcp 65001 >nul
title XJTLU RAG 服务启动器

echo ========================================
echo   XJTLU RAG 系统启动器
echo   使用系统 Python (不占用额外空间)
echo ========================================
echo.

REM 检查 Python
echo [1/4] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   错误: 未找到 Python
    pause
    exit /b 1
)
echo   Python 已就绪

REM 检查 .env
echo.
echo [2/4] 检查配置文件...
if not exist ".env" (
    echo   复制配置文件...
    copy .env.example .env >nul
    echo   请编辑 .env 文件
) else (
    echo   配置文件已就绪
)

REM 检查数据库
echo.
echo [3/4] 检查知识库...
if not exist "xjtlu_knowledge.db" (
    echo   警告: 未找到 xjtlu_knowledge.db
) else (
    echo   知识库已就绪
)

REM 启动服务
echo.
echo [4/4] 启动服务...
echo.
echo   服务地址: http://127.0.0.1:8000
echo   API文档:  http://127.0.0.1:8000/docs
echo.
echo   按 Ctrl+C 停止服务
echo.

python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
pause
