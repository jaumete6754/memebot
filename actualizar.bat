@echo off
REM ===================================================================
REM  Memebot - actualizacion en un clic (Windows)
REM
REM  Que hace:
REM    1. Busca el memebot*.zip mas reciente de tu carpeta Descargas
REM    2. Descomprime encima del proyecto
REM    3. Ejecuta los tests  <-- si fallan, NO sube nada
REM    4. Sube los cambios a GitHub
REM
REM  Uso: descarga el zip del chat y haz doble clic aqui.
REM ===================================================================

setlocal
cd /d "%~dp0"

echo.
echo   MEMEBOT - actualizacion
echo   ======================
echo.

REM --- 1 y 2: traer el zip mas reciente de Descargas -----------------
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$z = Get-ChildItem \"$env:USERPROFILE\Downloads\memebot*.zip\" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1;" ^
  "if ($z) {" ^
  "  Write-Host ('   Zip encontrado: ' + $z.Name);" ^
  "  Expand-Archive -Path $z.FullName -DestinationPath '.' -Force;" ^
  "  Write-Host '   Archivos actualizados.'" ^
  "} else {" ^
  "  Write-Host '   No hay ningun memebot*.zip en Descargas.';" ^
  "  Write-Host '   Se subiran solo los cambios que ya haya en la carpeta.'" ^
  "}"

if errorlevel 1 (
    echo.
    echo   ERROR al descomprimir. Revisa que el zip no este corrupto.
    pause
    exit /b 1
)

REM --- 3: los tests son la puerta. No pasan, no se sube. -------------
echo.
echo   Comprobando el codigo...
py -m unittest test_reglas >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ******************************************************
    echo   *  LOS TESTS FALLAN. No se sube nada a GitHub.       *
    echo   *                                                    *
    echo   *  Ejecuta para ver el detalle:                      *
    echo   *      py -m unittest test_reglas -v                 *
    echo   ******************************************************
    echo.
    pause
    exit /b 1
)
echo   Tests OK

REM --- 4: a GitHub ---------------------------------------------------
echo.
echo   Subiendo a GitHub...
git add -A

git diff --cached --quiet
if not errorlevel 1 (
    echo   No hay cambios que subir. Ya estaba todo al dia.
    echo.
    pause
    exit /b 0
)

git commit -m "Actualizacion automatica %date% %time%"
if errorlevel 1 (
    echo   ERROR al hacer commit.
    pause
    exit /b 1
)

git push
if errorlevel 1 (
    echo.
    echo   ERROR al subir. Lo mas probable: falta autenticarse.
    echo   La primera vez, Git abre una ventana para iniciar sesion
    echo   en GitHub. Vuelve a ejecutar este archivo despues.
    pause
    exit /b 1
)

echo.
echo   ======================================================
echo    Listo. Ahora en el movil, dentro de Termux:
echo.
echo        cd memebot
echo        git pull
echo.
echo   ======================================================
echo.
pause
