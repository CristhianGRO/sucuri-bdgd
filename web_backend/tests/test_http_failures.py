import http.client
import json
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from unittest.mock import Mock
import pandas as pd
from web_backend.server import Handler
from core.legacy_logic import LegacyTopology

class FailureResponses(unittest.TestCase):
    def test_submit_errors_return_json_instead_of_dropping_connection(self):
        for error,status in [(ModuleNotFoundError('pyproj ausente'),503),(RuntimeError('pool indisponível'),500)]:
            with self.subTest(status=status):
                service=Mock();service.submit.side_effect=error
                server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,service=service))
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                    conn.request('POST','/api/jobs',json.dumps({'kind':'process','args':{}}),{'Content-Type':'application/json'})
                    response=conn.getresponse()
                    self.assertEqual(response.status,status)
                    self.assertIn(str(error),json.loads(response.read())['error'])
                    conn.close()
                finally:
                    server.shutdown();server.server_close();thread.join()
    def test_feeder_without_switches_can_form_network(self):
        lines=pd.DataFrame([{'COD_ID':'line','PAC_1':'A','PAC_2':'B','FAS_CON':'ABC','COMP':'10'}])
        graph=LegacyTopology.create_MV_network('A',lines,pd.DataFrame(),pd.DataFrame())
        self.assertEqual(set(graph.nodes),{'A','B'})
        self.assertEqual(graph.number_of_edges(),1)

if __name__=='__main__':unittest.main()
