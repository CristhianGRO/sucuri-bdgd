import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from concurrent.futures import Future
import networkx as nx
import numpy as np
from web_backend.server import Service
from web_backend.result_cache import fingerprint,write_json,publish_cached,find_cached
from web_backend.worker import run_job, save_electrical_graph, load_electrical_graph, save_powerflow_warm_start, load_powerflow_warm_start

class PersistentCacheTests(TestCase):
    def test_completed_worker_reused_after_restart_and_invalidated(self):
        with tempfile.TemporaryDirectory() as tmp, patch('web_backend.server.ProcessPoolExecutor'):
            root=Path(tmp);dataset=root/'bases'/'TEST';dataset.mkdir(parents=True)
            (dataset/'CTMT.csv').write_text('COD_ID,NOME\nF1,Feeder\n')
            service=Service(root/'bases',root/'runtime')
            args={'dataset':'TEST','feeder':'F1','crs':'EPSG:4326'}
            key=fingerprint(dataset,'F1','EPSG:4326');args['_cache_key']=key;job_id='a'*32
            def generate(kind,arguments,data,jobs,cache,job,max_bytes):
                target=Path(jobs)/job
                for name in ('network.geojson','powerflow.zip','report.json'):(target/name).write_text('test')
                return {'dataset':'TEST','feeder':'F1'}
            with patch('web_backend.worker._run_job_impl',side_effect=generate):
                run_job('process',args,root/'bases',service.jobs_root,service.cache_root,job_id,100)
            restarted=Service(root/'bases',root/'runtime');restarted.pool.reset_mock()
            self.assertEqual(restarted.snapshot(job_id)['status'],'completed')
            cached=restarted.submit('process',{'dataset':'TEST','feeder':'F1'})
            self.assertTrue(cached['cached']);self.assertEqual(cached['id'],job_id);restarted.pool.submit.assert_not_called()
            self.assertTrue(restarted.cache_status({'dataset':'TEST','feeder':'F1'})['available'])
            (dataset/'CTMT.csv').write_text('COD_ID,NOME\nF1,Changed source\n')
            self.assertFalse(restarted.cache_status({'dataset':'TEST','feeder':'F1'})['available'])
            self.assertNotEqual(key,fingerprint(dataset,'F1','EPSG:31982'))
            (service.jobs_root/job_id/'powerflow.zip').unlink()
            self.assertIsNone(find_cached(service.jobs_root,key))
    def test_force_bypasses_saved_result_and_inflight_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp, patch('web_backend.server.ProcessPoolExecutor'),patch('web_backend.server.dependency_status',return_value={}):
            root=Path(tmp);dataset=root/'bases'/'TEST';dataset.mkdir(parents=True);(dataset/'CTMT.csv').write_text('COD_ID,NOME\nF1,Feeder\n')
            service=Service(root/'bases',root/'runtime');pending=Future();service.pool.submit.return_value=pending
            args={'dataset':'TEST','feeder':'F1','force':True}
            with patch('web_backend.server.find_cached',return_value={'id':'a'*32}) as saved:
                first=service.submit('process',args);saved.assert_not_called()
            second=service.submit('process',args);self.assertEqual(first['id'],second['id']);self.assertTrue(second['existing']);self.assertEqual(service.pool.submit.call_count,1)
    def test_failed_or_incomplete_jobs_are_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'jobs';job_id='b'*32;key='key'
            write_json(root/job_id/'state.json',{'status':'failed','cache_key':key})
            write_json(root.parent/'cache'/'key.json',{'id':job_id,'artifacts':{}})
            self.assertIsNone(find_cached(root,key))

    def test_powerflow_uses_its_own_persistent_cache_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dataset = root/'bases'/'TEST'; dataset.mkdir(parents=True)
            (dataset/'CTMT.csv').write_text('COD_ID,NOME\nF1,Feeder\n')
            jobs = root/'runtime'/'jobs'; job_id = 'c'*32
            args = {'dataset':'TEST','feeder':'F1','crs':'EPSG:4326','run_powerflow':True}
            args['_cache_key'] = fingerprint(dataset, 'F1', 'EPSG:4326', 'powerflow')
            def generate(kind, arguments, data, job_root, cache, job, max_bytes):
                target = Path(job_root)/job
                for name in ('network.geojson','powerflow.zip','report.json'):
                    (target/name).write_text('test')
                return {'dataset':'TEST','feeder':'F1'}
            with patch('web_backend.worker._run_job_impl', side_effect=generate):
                run_job('process', args, root/'bases', jobs, root/'runtime'/'downloads', job_id, 100)
            self.assertIsNotNone(find_cached(jobs, args['_cache_key']))

    def test_tap_settings_have_distinct_powerflow_cache_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)/'TEST'; dataset.mkdir()
            (dataset/'CTMT.csv').write_text('COD_ID,NOME\nF1,Feeder\n')
            base = fingerprint(dataset, 'F1', 'EPSG:4326', 'powerflow')
            adjusted = fingerprint(dataset, 'F1', 'EPSG:4326', 'powerflow', {'TR_1': .95})
            self.assertNotEqual(base, adjusted)

    def test_last_converged_powerflow_state_is_saved_by_network_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp)/'runtime'/'jobs'; key = 'network-key'
            voltages = {'SE': np.array([1 + 0j, -0.5j, 0.5j])}
            save_powerflow_warm_start(jobs, key, voltages)
            restored = load_powerflow_warm_start(jobs, key)
            self.assertTrue(np.array_equal(restored['SE'], voltages['SE']))
            self.assertIsNone(load_powerflow_warm_start(jobs, 'different-network'))

    def test_electrical_graph_cache_keeps_abc_matrices(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = nx.Graph()
            graph.add_edge('A', 'B', Zabc=np.eye(3, dtype=complex) * (.2 + .1j))
            path = Path(tmp) / 'electrical_graph.pickle'
            save_electrical_graph(path, graph)
            cached = load_electrical_graph(path)
            self.assertEqual(cached.number_of_edges(), 1)
            self.assertAlmostEqual(cached['A']['B']['Zabc'][0, 0].imag, .1)
