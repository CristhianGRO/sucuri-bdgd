# Build with: python -m PyInstaller sucuri-local.spec
from PyInstaller.utils.hooks import collect_all, copy_metadata
from pathlib import Path

datas=[('web','web'),('core','core'),('app/controller.py','app'),('app/utils.py','app'),('web_backend/worker.py','web_backend'),('web_backend/result_cache.py','web_backend')]
binaries=[]
hiddenimports=[]
for package in ('fiona','pyproj','shapely'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hiddenimports+=h
for package in ('pandas','numpy','networkx','scipy','pyproj','fiona','shapely'):
    datas+=copy_metadata(package)
a=Analysis(['sucuri_local.py'],pathex=[],binaries=binaries,datas=datas,hiddenimports=hiddenimports,hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['matplotlib','IPython','pytest','geopandas'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='SUCURI Local',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='SUCURI Local')
