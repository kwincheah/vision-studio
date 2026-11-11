# -*- mode: python ; coding: utf-8 -*-
# The optional converter: the one program that carries PyTorch, so the main application stays small.
#   pyinstaller ApexModelConverter.spec   ->   dist\ApexModelConverter\ApexModelConverter.exe
# Put that folder next to ApexVisionStudio.exe (or in %LOCALAPPDATA%\Apex Industrial Vision Studio\converter) and .pt models convert on load.
from PyInstaller.utils.hooks import collect_all

datas, binaries, hidden = [], [], []
for pkg in ("ultralytics", "torch", "torchvision", "onnx"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis(['apex_vision/model_converter.py'], pathex=[], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['tkinter', 'matplotlib', 'PyQt6', 'PySide6'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ApexModelConverter', console=True)
coll = COLLECT(exe, a.binaries, a.datas, name='ApexModelConverter')
