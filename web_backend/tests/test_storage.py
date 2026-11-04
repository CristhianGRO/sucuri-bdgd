import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch
from web_backend.server import Service

class StorageTests(TestCase):
    def test_new_storage_takes_priority_and_legacy_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp, patch('web_backend.server.ProcessPoolExecutor'):
            root=Path(tmp).resolve();new=root/'new';old=root/'old'
            for base,feed in [(new/'SHARED','NEW'),(old/'SHARED','OLD'),(old/'LEGACY','L1')]:
                base.mkdir(parents=True);(base/'CTMT.csv').write_text('COD_ID,NOME\n'+feed+',name\n')
            service=Service(new,root/'runtime',legacy_data=old)
            self.assertEqual({d['id'] for d in service.datasets()},{'SHARED','LEGACY'})
            self.assertEqual(service.feeders('SHARED')[0]['id'],'NEW')
            self.assertEqual(service.dataset_path('LEGACY').parent,old)
            with self.assertRaises(ValueError): service.dataset_path('../escape')
            with patch('web_backend.server.dependency_status',return_value={}):
                service.pool.submit.return_value=Mock()
                service.submit('process',{'dataset':'LEGACY','feeder':'L1','crs':'EPSG:4326'})
            arguments=service.pool.submit.call_args.args
            self.assertEqual(arguments[3],str(old))
            self.assertEqual(arguments[4],str(root/'runtime'/'jobs'))
