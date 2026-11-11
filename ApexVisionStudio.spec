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
    'rapidocr_onnxruntime',          # OCR Recognition (its models are added below)
] + collect_submodules('apex_vision') + collect_submodules('serial')    # serial: the Serial Send module (pyserial)

# Collect data files and model weights
datas = [
    ('apex_vision/samples/*.png', 'apex_vision/samples'),
    ('apex_vision/samples/models', 'apex_vision/samples/models'),     # small demo models for the deep-learning modules
    ('plugins/sample_sobel_edge_plugin', 'plugins/sample_sobel_edge_plugin'),   # only the published sample plugin; private plugins stay out
    ('apex_vision/assets', 'apex_vision/assets'),            # application icon
    ('qml', 'qml'),                                    # the Qt Quick interface (main.py starts it)
    ('apex_vision/flowgen/reference', 'apex_vision/flowgen/reference'),   # AI Gen reference the assistant reads
    ('apex_vision/flowgen/recipes', 'apex_vision/flowgen/recipes'),
]

# OCR Recognition: the RapidOCR models and settings (without them the engine cannot start)
datas += collect_data_files('rapidocr_onnxruntime')

# Include YOLO weights if present (the .onnx runs in the packaged app, which has no PyTorch)
if os.path.exists(os.path.join(project_dir, 'yolo11n.onnx')):
    datas.append(('yolo11n.onnx', '.'))
if os.path.exists(os.path.join(project_dir, 'yolo11n.pt')):
    datas.append(('yolo11n.pt', '.'))

# Ship the demo projects only (files ending in _Demo.apex), never whatever else happens to be in the folder
for _name in sorted(os.listdir(os.path.join(project_dir, 'projects'))) if os.path.isdir(os.path.join(project_dir, 'projects')) else []:
    if _name.endswith('_Demo.apex'):
        datas.append((os.path.join('projects', _name), 'projects'))

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
    icon='apex_vision/assets/app_icon.ico',
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
