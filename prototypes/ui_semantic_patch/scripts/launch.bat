@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: launch.bat - UI 异常场景生成一键启动脚本 (Windows)
::
:: 用法:
::   launch.bat                     交互式选择模式
::   launch.bat single              单图模式（使用下方默认配置）
::   launch.bat batch               批量模式（dry-run 预览）
::   launch.bat batch --run         批量模式（实际执行）
::   launch.bat list                列出所有异常类别

:: ============================================================
:: 路径配置
:: ============================================================
set "SCRIPT_DIR=%~dp0"
:: 去掉末尾反斜杠
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "DATA_DIR=%SCRIPT_DIR%\..\data"
set "GT_DIR=%DATA_DIR%\Agent执行遇到的典型异常UI类型\analysis\gt_templates"
set "ORIG_DIR=%DATA_DIR%\原图"

:: 项目根目录（scripts -> ui_semantic_patch -> prototypes -> App_Test_Agent）
for %%i in ("%SCRIPT_DIR%\..\..\..") do set "PROJECT_ROOT=%%~fi"

:: ============================================================
:: 默认参数（按需修改）
:: ============================================================

:: --- 单图模式默认值 ---
set "SCREENSHOT=%ORIG_DIR%\app首页类-开屏广告弹窗\携程旅行01.jpg"
set "INSTRUCTION=生成优惠券广告弹窗"
set "ANOMALY_MODE=dialog"
set "GT_CATEGORY=弹窗覆盖原UI"
set "GT_SAMPLE=弹出广告.jpg"
set "OUTPUT_DIR=%SCRIPT_DIR%\output\生成优惠券广告弹窗"

:: --- 批量模式默认值 ---
set "BATCH_INPUT_DIR=%ORIG_DIR%\app首页类-开屏广告弹窗"
set "BATCH_GT_CATEGORY=弹窗覆盖原UI"
set "BATCH_OUTPUT_DIR=%SCRIPT_DIR%\batch_output"
set "BATCH_PATTERN=*.jpg"

:: ============================================================
:: 加载 .env
:: ============================================================
if exist "%PROJECT_ROOT%\.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%PROJECT_ROOT%\.env") do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" (
            if not "%%a"=="" if not "%%b"=="" set "%%a=%%b"
        )
    )
)

:: ============================================================
:: 主入口
:: ============================================================
if "%~1"=="" goto :interactive
if /i "%~1"=="single" goto :run_single
if /i "%~1"=="batch" goto :run_batch
if /i "%~1"=="list" goto :run_list
goto :usage

:: ============================================================
:: 环境检查
:: ============================================================
:check_env
echo ============================================================
echo 环境检查
echo ============================================================

if exist "%PROJECT_ROOT%\.env" (
    echo   [OK] 已加载 .env: %PROJECT_ROOT%\.env
) else (
    echo   [WARN] 未找到 .env 文件: %PROJECT_ROOT%\.env
    echo          请复制 .env.example 并填入 API Key
)

if defined VLM_API_KEY (
    echo   [OK] VLM_API_KEY 已设置 (%VLM_API_KEY:~0,8%...^)
) else (
    echo   [ERROR] VLM_API_KEY 未设置，请在 .env 中配置
    exit /b 1
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "delims=" %%v in ('python --version 2^>^&1') do echo   [OK] %%v
) else (
    echo   [ERROR] Python 未找到
    exit /b 1
)

if exist "%ORIG_DIR%" (
    echo   [OK] 原图目录: %ORIG_DIR%
) else (
    echo   [ERROR] 原图目录不存在: %ORIG_DIR%
    exit /b 1
)

if exist "%GT_DIR%" (
    echo   [OK] GT模板目录: %GT_DIR%
) else (
    echo   [ERROR] GT模板目录不存在: %GT_DIR%
    exit /b 1
)

echo.
goto :eof

:: ============================================================
:: 单图模式
:: ============================================================
:run_single
call :check_env
if %errorlevel% neq 0 exit /b 1

echo ============================================================
echo 单图异常生成
echo ============================================================
echo   截图:       %SCREENSHOT%
echo   指令:       %INSTRUCTION%
echo   异常模式:   %ANOMALY_MODE%
if defined GT_CATEGORY (
    echo   GT类别:     %GT_CATEGORY%
) else (
    echo   GT类别:     （未指定，使用普通模式）
)
if defined GT_SAMPLE (
    echo   GT样本:     %GT_SAMPLE%
)
echo   输出目录:   %OUTPUT_DIR%
echo ============================================================
echo.

if not exist "%SCREENSHOT%" (
    echo [ERROR] 截图文件不存在: %SCREENSHOT%
    exit /b 1
)

:: 构建命令
set "CMD=python "%SCRIPT_DIR%\run_pipeline.py""
set "CMD=%CMD% --screenshot "%SCREENSHOT%""
set "CMD=%CMD% --instruction "%INSTRUCTION%""
set "CMD=%CMD% --anomaly-mode %ANOMALY_MODE%"
set "CMD=%CMD% --output "%OUTPUT_DIR%""

if defined GT_CATEGORY if defined GT_SAMPLE (
    set "CMD=%CMD% --gt-category "%GT_CATEGORY%""
    set "CMD=%CMD% --gt-sample "%GT_SAMPLE%""
    set "CMD=%CMD% --gt-dir "%GT_DIR%""
)

echo [CMD] %CMD%
echo.
%CMD%
goto :eof

:: ============================================================
:: 批量模式
:: ============================================================
:run_batch
call :check_env
if %errorlevel% neq 0 exit /b 1

:: 收集额外参数（跳过第一个参数 "batch"）
set "EXTRA_ARGS="
set "skip=1"
for %%a in (%*) do (
    if !skip!==0 set "EXTRA_ARGS=!EXTRA_ARGS! %%a"
    set "skip=0"
)

echo ============================================================
echo 批量异常生成
echo ============================================================
echo   原图目录:   %BATCH_INPUT_DIR%
echo   GT类别:     %BATCH_GT_CATEGORY%
echo   文件匹配:   %BATCH_PATTERN%
echo   输出目录:   %BATCH_OUTPUT_DIR%
echo   额外参数:   %EXTRA_ARGS%
echo ============================================================
echo.

set "CMD=python "%SCRIPT_DIR%\batch_pipeline.py""
set "CMD=%CMD% --input-dir "%BATCH_INPUT_DIR%""
set "CMD=%CMD% --gt-category "%BATCH_GT_CATEGORY%""
set "CMD=%CMD% --pattern "%BATCH_PATTERN%""
set "CMD=%CMD% --output "%BATCH_OUTPUT_DIR%""
set "CMD=%CMD% %EXTRA_ARGS%"

echo [CMD] %CMD%
echo.
%CMD%
goto :eof

:: ============================================================
:: 列出类别
:: ============================================================
:run_list
call :check_env
if %errorlevel% neq 0 exit /b 1
python "%SCRIPT_DIR%\batch_pipeline.py" --list-categories --gt-dir "%GT_DIR%"
goto :eof

:: ============================================================
:: 交互式菜单
:: ============================================================
:interactive
call :check_env
if %errorlevel% neq 0 exit /b 1

echo.
echo ============================================================
echo   UI 异常场景生成 - 一键启动
echo ============================================================
echo.
echo   可用原图:
echo     [1] app首页类-开屏广告弹窗/  (携程旅行01, 携程旅行02)
echo     [2] 个人主页类-控件点击弹窗/  (抖音原图01, 抖音原图02)
echo     [3] 影视剧集类-内容歧义、重复/ (腾讯视频)
echo.
echo   可用异常类别:
echo     [A] 弹窗覆盖原UI       (7个样本, dialog 模式)
echo     [B] 内容歧义、重复      (1个样本, content_duplicate 模式)
echo     [C] loading_timeout    (1个样本, area_loading 模式)
echo.
echo   请选择运行模式:
echo     1) 单图 - 弹窗广告 (携程旅行01 x 弹出广告)
echo     2) 单图 - 关闭按钮干扰 (抖音原图01 x 关闭按钮干扰)
echo     3) 单图 - 内容重复 (腾讯视频 x 部分信息重复)
echo     4) 单图 - 加载超时 (腾讯视频)
echo     5) 批量 - 预览计划 (dry-run)
echo     6) 批量 - 实际执行
echo     7) 列出所有异常类别
echo     q) 退出
echo.
set /p "choice=  请输入选项 [1-7/q]: "

if "%choice%"=="1" (
    set "SCREENSHOT=%ORIG_DIR%\app首页类-开屏广告弹窗\携程旅行01.jpg"
    set "INSTRUCTION=生成优惠券广告弹窗"
    set "ANOMALY_MODE=dialog"
    set "GT_CATEGORY=弹窗覆盖原UI"
    set "GT_SAMPLE=弹出广告.jpg"
    set "OUTPUT_DIR=%SCRIPT_DIR%\output\demo_dialog"
    goto :run_single
)
if "%choice%"=="2" (
    set "SCREENSHOT=%ORIG_DIR%\个人主页类-控件点击弹窗\抖音原图01.jpg"
    set "INSTRUCTION=生成权限请求弹窗"
    set "ANOMALY_MODE=dialog"
    set "GT_CATEGORY=弹窗覆盖原UI"
    set "GT_SAMPLE=关闭按钮干扰.jpg"
    set "OUTPUT_DIR=%SCRIPT_DIR%\output\demo_close_button"
    goto :run_single
)
if "%choice%"=="3" (
    set "SCREENSHOT=%ORIG_DIR%\影视剧集类-内容歧义、重复\腾讯视频.jpg"
    set "INSTRUCTION=模拟底部信息重复显示"
    set "ANOMALY_MODE=content_duplicate"
    set "GT_CATEGORY=内容歧义、重复"
    set "GT_SAMPLE=部分信息重复.jpg"
    set "OUTPUT_DIR=%SCRIPT_DIR%\output\demo_duplicate"
    goto :run_single
)
if "%choice%"=="4" (
    set "SCREENSHOT=%ORIG_DIR%\影视剧集类-内容歧义、重复\腾讯视频.jpg"
    set "INSTRUCTION=模拟列表加载超时"
    set "ANOMALY_MODE=area_loading"
    set "GT_CATEGORY="
    set "GT_SAMPLE="
    set "OUTPUT_DIR=%SCRIPT_DIR%\output\demo_loading"
    goto :run_single
)
if "%choice%"=="5" goto :run_batch_dryrun
if "%choice%"=="6" goto :run_batch_exec
if "%choice%"=="7" goto :run_list
if /i "%choice%"=="q" (
    echo 退出
    exit /b 0
)
echo [ERROR] 无效选项: %choice%
exit /b 1

:run_batch_dryrun
set "EXTRA_ARGS="
goto :run_batch_from_menu

:run_batch_exec
set "EXTRA_ARGS=--run"
goto :run_batch_from_menu

:run_batch_from_menu
echo ============================================================
echo 批量异常生成
echo ============================================================
echo   原图目录:   %BATCH_INPUT_DIR%
echo   GT类别:     %BATCH_GT_CATEGORY%
echo   输出目录:   %BATCH_OUTPUT_DIR%
echo ============================================================
echo.
set "CMD=python "%SCRIPT_DIR%\batch_pipeline.py""
set "CMD=%CMD% --input-dir "%BATCH_INPUT_DIR%""
set "CMD=%CMD% --gt-category "%BATCH_GT_CATEGORY%""
set "CMD=%CMD% --pattern "%BATCH_PATTERN%""
set "CMD=%CMD% --output "%BATCH_OUTPUT_DIR%""
set "CMD=%CMD% %EXTRA_ARGS%"
echo [CMD] %CMD%
echo.
%CMD%
goto :eof

:: ============================================================
:: 用法提示
:: ============================================================
:usage
echo 用法: launch.bat [single^|batch^|list]
echo.
echo   single          单图模式（使用脚本内默认配置）
echo   batch           批量模式（默认 dry-run）
echo   batch --run     批量模式（实际执行）
echo   list            列出所有异常类别
echo   （无参数）       交互式菜单
exit /b 1
