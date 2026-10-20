@echo off
setlocal EnableDelayedExpansion
rem ============================================================================
rem  Apex Vision Studio - widget UI -> QML conversion helper
rem  Double-click for the menu, or pass a command:
rem     convert_qml run | design | icons | verify | widget | shots | dialog Name "Title" [Menu]
rem ============================================================================
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul || (echo Python was not found on PATH. & pause & exit /b 1)

if not "%~1"=="" goto :dispatch

:menu
cls
echo.
echo   Apex Vision Studio  -  QML conversion
echo   ------------------------------------------------------------
echo    1  Run the application (main.py - the QML UI)
echo    2  Open the project in Qt Design Studio  (qml\ApexVision.qmlproject)
echo    3  Create a new QML dialog  (file + registration + menu entry)
echo    4  Verify everything  (QML loads with no warnings, tests pass)
echo    5  Regenerate the SVG icons
echo    6  Take screenshots of every screen  (docs\screenshots\qml)
echo    7  Run the classic widget UI (main.py --widgets)
echo    8  Show the conversion guide
echo    0  Exit
echo.
set "CHOICE="
set /p "CHOICE=  Choose: "
if "%CHOICE%"=="1" call :run    & goto :again
if "%CHOICE%"=="2" call :design & goto :again
if "%CHOICE%"=="3" call :dialog_prompt & goto :again
if "%CHOICE%"=="4" call :verify & goto :again
if "%CHOICE%"=="5" call :icons  & goto :again
if "%CHOICE%"=="6" call :shots  & goto :again
if "%CHOICE%"=="7" call :widget & goto :again
if "%CHOICE%"=="8" call :guide  & goto :again
if "%CHOICE%"=="0" exit /b 0
goto :menu

:again
echo.
pause
goto :menu

:dispatch
set "CMD=%~1"
if /i "%CMD%"=="run"    call :run    & exit /b !errorlevel!
if /i "%CMD%"=="design" call :design & exit /b !errorlevel!
if /i "%CMD%"=="icons"  call :icons  & exit /b !errorlevel!
if /i "%CMD%"=="verify" call :verify & exit /b !errorlevel!
if /i "%CMD%"=="widget" call :widget & exit /b !errorlevel!
if /i "%CMD%"=="shots"  call :shots  & exit /b !errorlevel!
if /i "%CMD%"=="guide"  call :guide  & exit /b !errorlevel!
if /i "%CMD%"=="dialog" (
    if "%~2"=="" (echo usage: convert_qml dialog Name "Title" [Menu] & exit /b 2)
    if "%~4"=="" ( %PY% qml\tools\new_dialog.py "%~2" "%~3" ) else ( %PY% qml\tools\new_dialog.py "%~2" "%~3" --menu "%~4" )
    exit /b !errorlevel!
)
echo Unknown command "%CMD%".
exit /b 2

:run
echo Starting the QML UI ...
%PY% qml_main.py
exit /b %errorlevel%

:widget
echo Starting the widget UI ...
%PY% main.py --widgets
exit /b %errorlevel%

:design
rem Qt Design Studio registers itself for .qmlproject files; otherwise search the usual places.
set "DS="
for %%P in ("%ProgramFiles%\Qt\Qt Design Studio*" "%ProgramFiles(x86)%\Qt\Qt Design Studio*" "C:\Qt\Qt Design Studio*" "C:\Qt\Tools\QtDesignStudio*") do (
    for %%E in ("%%~P\bin\qtdesignstudio.exe" "%%~P\qtdesignstudio.exe") do if exist %%E set "DS=%%~E"
)
if defined DS (
    echo Opening with !DS!
    start "" "!DS!" "%CD%\qml\ApexVision.qmlproject"
) else (
    echo Qt Design Studio not found in the usual folders - using the .qmlproject file association.
    start "" "%CD%\qml\ApexVision.qmlproject"
    echo If nothing opened: install Qt Design Studio from https://www.qt.io/product/ui-design-tools
    echo then use  File ^> Open Project  and pick  qml\ApexVision.qmlproject
)
exit /b 0

:dialog_prompt
echo.
set "DNAME=" & set "DTITLE=" & set "DMENU="
set /p "DNAME=  Name (CamelCase, e.g. SettingsHub): "
if "%DNAME%"=="" exit /b 0
set /p "DTITLE=  Window title (e.g. Settings Hub): "
if "%DTITLE%"=="" set "DTITLE=%DNAME%"
set /p "DMENU=  Add to menu (File/Settings/Tools/System/Inspection/View/Help, blank = none): "
if "%DMENU%"=="" ( %PY% qml\tools\new_dialog.py "%DNAME%" "%DTITLE%" ) else ( %PY% qml\tools\new_dialog.py "%DNAME%" "%DTITLE%" --menu "%DMENU%" )
exit /b %errorlevel%

:icons
%PY% qml\tools\make_icons.py
exit /b %errorlevel%

:verify
echo [1/2] QML load, backend and registration tests ...
%PY% -m pytest tests\test_qml_ui.py -q -p no:cacheprovider
if errorlevel 1 (echo. & echo VERIFY FAILED - see above. & exit /b 1)
echo [2/2] Whole test suite ...
%PY% -m pytest tests -q -p no:cacheprovider
if errorlevel 1 (echo. & echo VERIFY FAILED - see above. & exit /b 1)
echo.
echo All good.
exit /b 0

:shots
%PY% qml\tools\screenshots.py
exit /b %errorlevel%

:guide
if exist docs\QML_CONVERSION.md (type docs\QML_CONVERSION.md | more) else echo docs\QML_CONVERSION.md not found.
exit /b 0
