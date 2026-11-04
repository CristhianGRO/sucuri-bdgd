import http.client
import json
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
from web_backend.access import Access, PAGES_ORIGIN
from web_backend.server import Handler

class BrowserAccess(unittest.TestCase):
    def setUp(self):
        self.access=Access();service=Mock();service.datasets.return_value=[]
        self.server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,service=service,access=self.access))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method,path,headers=None,body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        conn.request(method,path,body,headers or {});res=conn.getresponse()
        result=res.status,dict(res.getheaders()),res.read();conn.close();return result
    def test_pairing_required_and_authenticated_download_origin(self):
        headers={'Origin':PAGES_ORIGIN,'Content-Type':'application/json'}
        self.assertEqual(self.request('GET','/api/datasets',headers)[0],401)
        code=self.access.code
        status,response,body=self.request('POST','/api/pair',headers,json.dumps({'code':code}))
        self.assertEqual(status,200);self.assertEqual(response['Access-Control-Allow-Origin'],PAGES_ORIGIN)
        headers['Authorization']='Bearer '+json.loads(body)['token']
        self.assertEqual(self.request('GET','/api/datasets',headers)[0],200)
        self.assertEqual(self.request('POST','/api/pair',headers,json.dumps({'code':code}))[0],400)
        headers['Origin']='https://untrusted.example'
        status,response,_=self.request('GET','/api/datasets',headers)
        self.assertEqual(status,403);self.assertNotIn('Access-Control-Allow-Origin',response)
    def test_preflight_and_local_access(self):
        status,headers,_=self.request('OPTIONS','/api/pair',{'Origin':PAGES_ORIGIN})
        self.assertEqual(status,204);self.assertIn('Authorization',headers['Access-Control-Allow-Headers'])
        self.assertEqual(self.request('GET','/api/datasets')[0],200)
        self.assertEqual(self.request('GET','/api/datasets',{'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('GET','/api/datasets',{'Sec-Fetch-Site':'cross-site'})[0],403)
    def test_windowed_app_without_console(self):
        with patch('sys.stderr',None):
            self.assertEqual(self.request('GET','/api/datasets')[0],200)

    def test_attempt_limit_and_renewal(self):
        for _ in range(5):
            with self.assertRaises(ValueError):self.access.pair('invalid')
        with self.assertRaises(ValueError):self.access.pair(self.access.code)
        self.assertEqual(self.access.pair(self.access.renew()),self.access.token)
        previous=self.access.token
        self.assertFalse(Access().authorized('Bearer '+previous))
