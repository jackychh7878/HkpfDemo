# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Get the path to the Azure Speech SDK DLL
azure_speech_path = os.path.join(sys.prefix, 'Lib', 'site-packages', 'azure', 'cognitiveservices', 'speech')
dll_path = os.path.join(azure_speech_path, 'Microsoft.CognitiveServices.Speech.core.dll')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[(dll_path, 'azure/cognitiveservices/speech')],
    datas=collect_data_files('azure.cognitiveservices.speech'),
    hiddenimports=collect_submodules('azure.cognitiveservices.speech'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
) 