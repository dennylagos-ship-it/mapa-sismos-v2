@echo off
rem Construye MapaSismos2.exe y el instalador. Requiere: pip install pyinstaller  +  Inno Setup 6
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --name MapaSismos2 --icon "%~dp0instalador\icono.ico" --add-data "%~dp0web;web" --version-file "%~dp0instalador\version_info.txt" --distpath dist --workpath build --specpath build servidor.py || exit /b 1
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" instalador\MapaSismos2.iss || exit /b 1
echo Listo: dist\MapaSismos2_Setup_*.exe
