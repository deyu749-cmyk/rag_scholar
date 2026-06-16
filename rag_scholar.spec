# rag_scholar.spec
# 运行方式：pyinstaller rag_scholar.spec

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['launch.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('.env', '.'),
    ],
    hiddenimports=[
        'chromadb',
        'chromadb.api',
        'chromadb.api.client',
        'chromadb.db.impl',
        'chromadb.db.impl.sqlite',
        'chromadb.segment',
        'chromadb.segment.impl',
        'chromadb.segment.impl.manager',
        'chromadb.segment.impl.manager.local',
        'chromadb.segment.impl.vector',
        'chromadb.segment.impl.vector.local_persistent_hnsw',
        'chromadb.segment.impl.metadata',
        'chromadb.segment.impl.metadata.sqlite',
        'chromadb.telemetry',
        'chromadb.telemetry.product',
        'chromadb.telemetry.product.posthog',
        'openai',
        'flask',
        'flask_cors',
        'fitz',
        'docx',
        'dotenv',
        'pydantic',
        'hnswlib',
        'tokenizers',
        'pypika',
        'overrides',
        'importlib_resources',
        'posthog',
        'backoff',
        'typing_extensions',
        'numpy',
        'chromadb.api.rust',
        'chromadb.api.fastapi',
        'chromadb.server',
        'chromadb.server.fastapi',
        'chromadb.auth',
        'chromadb.auth.providers',
        'numpy',
        'numpy.core',
        'numpy.core._methods',
        'numpy.lib',
        'numpy.lib.stride_tricks',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'torch',
        'tensorflow',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='文献语义检索系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='文献语义检索系统',
)