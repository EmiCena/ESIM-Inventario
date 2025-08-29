@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem PROJ = carpeta del proyecto (dos niveles arriba de este .bat: ...\esi-inventario\scripts\tasksKATEX_INLINE_CLOSE
set "PROJ=%~dp0..\.."
for %%i in ("%PROJ%") do set "PROJ=%%~fi"

set "PY=%PROJ%\.venv\Scripts\python.exe"

rem Cambiamos a la carpeta del proyecto (para que lea .env)
pushd "%PROJ%" || (
  echo [ERROR] No se puede entrar a "%PROJ%".
  exit /b 1
)

rem Validaciones
if not exist "%PY%" (
  echo [ERROR] No se encontro Python del venv en: "%PY%"
  popd & exit /b 2
)
if not exist "manage.py" (
  echo [ERROR] No se encontro manage.py en: "%CD%"
  popd & exit /b 3
)

if not exist "logs" mkdir "logs"

rem Ejecutamos el manage con los argumentos que pases al .bat
echo ==== %date% %time% ==== %* >> "logs\tasks.log"
"%PY%" manage.py %* >> "logs\tasks.log" 2>&1
set "ERR=%ERRORLEVEL%"
echo ---- ExitCode %ERR% ---- >> "logs\tasks.log"

popd
exit /b %ERR%