import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import web_backend
import fiona
from web_backend.worker import import_aneel
from web.tools.export_geojson import export

class GDBImportTest(unittest.TestCase):
    def test_download_extract_convert_and_preserve_lines(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);gdb=root/'sample.gdb'
            for layer, geometry in [('CTMT','Point'),('PONNOT','Point'),('SSDMT','LineString')]:
                with fiona.open(str(gdb),'w',driver='OpenFileGDB',layer=layer,crs='EPSG:4326',schema={'geometry':geometry,'properties':{'COD_ID':'str','CTMT':'str','PAC_INI':'str'}}) as dst:
                    coords=[-51.,-30.] if geometry=='Point' else [[-51.,-30.],[-51.01,-30.01],[-51.02,-30.02]]
                    dst.write({'geometry':{'type':geometry,'coordinates':coords},'properties':{'COD_ID':'F1' if layer=='CTMT' else 'N1','CTMT':'F1','PAC_INI':'N1'}})
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as z:
                for path in gdb.rglob('*'):
                    if path.is_file():z.write(path,path.relative_to(root))
            archive=buffer.getvalue();item_id='a'*32;data=root/'data';data.mkdir()
            with patch('web_backend.worker.remote_json',return_value={'owner':'aneel_aneel','type':'File Geodatabase','access':'public','title':'Test','size':len(archive)}),patch('web_backend.worker.urllib.request.urlopen',return_value=io.BytesIO(archive)):
                result=import_aneel(item_id,data,root/'cache',lambda _:None,10*1024**2)
            dataset=data/result['dataset'];self.assertTrue((dataset/'CTMT.csv').exists())
            source=json.loads((dataset/'source.json').read_text(encoding='utf-8'))
            self.assertEqual(len(source['sha256']),64)
            output=root/'map.geojson';export(source['gdb'],output,['SSDMT'],{'F1'})
            geo=json.loads(output.read_text(encoding='utf-8'))
            geometry=geo['features'][0]['geometry']
            coords=geometry['coordinates'][0] if geometry['type']=='MultiLineString' else geometry['coordinates']
            self.assertEqual(len(coords),3)
            self.assertEqual(geo['features'][0]['properties']['CTMT'],'F1')

if __name__=='__main__':unittest.main()
