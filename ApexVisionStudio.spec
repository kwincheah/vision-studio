# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Specification File for Apex Industrial Vision Studio.

Build Command:
    pyinstaller ApexVisionStudio.spec --clean --noconfirm

Output:
    dist/ApexVisionStudio/ (Self-contained, standalone folder with ApexVisionStudio.exe)
"""
import sys
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

project_dir = os.path.abspath(os.curdir)

# Collect submodules dynamically for dynamic registry and tools
hidden_imports = [
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',
    'PyQt6.QtQml',
    'PyQt6.QtQuick',
    'PyQt6.QtQuickWidgets',
    'anthropic',
    'keyring',
    'keyring.backends.Windows',
    'mcp',
    'cv2',
    'numpy',
] + collect_submodules('vm_clone')

# Collect data files and model weights
datas = [
    ('vm_clone/samples/*.png', 'vm_clone/samples'),
    ('plugins', 'plugins'),
    ('vm_clone/assets', 'vm_clone/assets'),            # application icon
    ('qml', 'qml'),                                    # the Qt Quick interface (main.py starts it)
    ('vm_clone/flowgen/reference', 'vm_clone/flowgen/reference'),   # AI Gen reference the assistant reads
    ('vm_clone/flowgen/recipes', 'vm_clone/flowgen/recipes'),
]

# Include YOLO weights if present
if os.path.exists(os.path.join(project_dir, 'yolo11n.pt')):
    datas.append(('yolo11n.pt', '.'))

# Include projects template folder if present
if os.path.exists(os.path.join(project_dir, 'projects')):
    datas.append(('projects', 'projects'))

a = Analysis(
    ['main.py'],
    pathex=[project_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'unittest',
        'IPython',
        'jupyter',
        'pytest',
        'torch',
        'torchvision',
        'torchaudio',
        'numba',
        'llvmlite',
        'pandas',
        'transformers',
        'boto3',
        'botocore',
        'polars',
        'pyarrow',
        'soundfile',
        'datasets',
        'sklearn',
        'scikit-learn',
        'psycopg',
        'psycopg2',
        'psycopg_binary',
        'redis',
        'uvicorn',
        'starlette',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ApexVisionStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # Windowed GUI application (no command console)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='vm_clone/assets/app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ApexVisionStudio',
)
