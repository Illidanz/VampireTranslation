pipenv run pyinstaller --clean --icon=icon.ico --add-binary "ndstool.exe;." --add-binary "armips.exe;." --add-binary "xdelta.exe;." --add-data "bin_patch.asm;." --distpath . -F --exclude-module="numpy" --hidden-import="pkg_resources.py2_warn" tool.py
