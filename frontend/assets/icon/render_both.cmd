@echo off
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background "%~dp0ATC-tower.blend" --python "%~dp0render_both.py"
if errorlevel 1 (
 echo Rendering failed. See messages above.
) else (
 echo Both renders saved beside this launcher.
)
pause
