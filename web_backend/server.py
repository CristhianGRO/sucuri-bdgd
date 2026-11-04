"""Local-only SUCURI service. Run: python -m web_backend.server"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import importlib
import sys
from functools import lru_cache
import json
from pathlib import Path
import threading
import urllib.parse
import uuid
import re
from .access import Access, PAGES_ORIGIN
from .settings import storage_path
from .result_cache import fingerprint, find_cached, write_json
from .worker import ROOT, catalog, run_job, safe_child


@lru_cache(maxsize=1)
def dependency_status():
    problems = {}
    for name in ('pandas', 'numpy', 'networkx', 'scipy', 'pyproj', 'fiona', 'shapely'):
        try:
            importlib.import_module(name)
            if name == 'scipy':
                importlib.import_module('scipy.optimize')
        except Exception as exc:
            problems[name] = str(exc)
    return problems


class Service:
    def __init__(self, data, runtime, workers=1, max_gb=4, legacy_data=None):
        self.data = Path(data).resolve()
        self.runtime = Path(runtime).resolve()
        self.read_roots = [self.data]
        if legacy_data is not None and Path(legacy_data).resolve() != self.data:
            self.read_roots.append(Path(legacy_data).resolve())
        self.jobs_root = self.runtime / 'jobs'
        self.cache_root = self.runtime / 'downloads'
        self.data.mkdir(parents=True,exist_ok=True)
        self.jobs_root.mkdir(parents=True,exist_ok=True)
        self.pool = ProcessPoolExecutor(max_workers=workers)
        self.jobs = {}
        self.lock = threading.Lock()
        self.max_bytes = int(max_gb * 1024**3)

    def dataset_path(self, dataset):
        for root in self.read_roots:
            path = safe_child(root, dataset)
            if (path / 'CTMT.csv').is_file():
                return path
        raise FileNotFoundError('Base não encontrada: ' + str(dataset))

    def datasets(self):
        items = {}
        for root in self.read_roots:
            if not root.is_dir():
                continue
            for path in sorted(root.iterdir()):
                if path.name.startswith('.') or path.name in items or not path.is_dir() or not (path/'CTMT.csv').is_file():
                    continue
                meta=path/'source.json'
                title=json.loads(meta.read_text(encoding='utf-8')).get('title',path.name) if meta.exists() else path.name
                items[path.name]={'id':path.name,'title':title}
        return list(items.values())

    def feeders(self, dataset):
        path=self.dataset_path(dataset)/'CTMT.csv'
        with path.open(encoding='utf-8-sig',newline='') as f:
            return [{'id':r['COD_ID'],'name':r.get('NOME','')} for r in csv.DictReader(f)]

    def process_arguments(self, args):
        if not isinstance(args,dict):
            raise ValueError('Parâmetros inválidos')
        dataset = args.get('dataset')
        feeder = str(args.get('feeder',''))
        if feeder not in {f['id'] for f in self.feeders(dataset)}:
            raise ValueError('Alimentador não pertence à base selecionada')
        from pyproj import CRS
        crs = CRS.from_user_input(args.get('crs','EPSG:4326')).to_string()
        return {'dataset':dataset,'feeder':feeder,'crs':crs}

    def cache_status(self, args):
        args = self.process_arguments(args)
        key = fingerprint(self.dataset_path(args['dataset']),args['feeder'],args['crs'])
        saved = find_cached(self.jobs_root,key)
        return {'available':bool(saved),'id':saved['id'] if saved else None,'completed_at':saved.get('completed_at') if saved else None}

    def submit(self, kind, args):
        if kind not in ('process','import') or not isinstance(args,dict):
            raise ValueError('Tipo ou parâmetros de tarefa inválidos')
        force = args.get('force',False)
        if not isinstance(force,bool):
            raise ValueError('force deve ser booleano')
        if kind == 'process':
            args = self.process_arguments(args)
            input_root = self.dataset_path(args['dataset']).parent
            key = fingerprint(self.dataset_path(args['dataset']),args['feeder'],args['crs'])
            args['_cache_key'] = key
        else:
            args = {'item_id':args['item_id']}
            input_root = self.data
        with self.lock:
            for job_id, job in self.jobs.items():
                if job['kind']==kind and job['args']==args and not job['future'].done():
                    return {'id':job_id,'cached':False,'existing':True}
            if kind=='process' and not force:
                saved = find_cached(self.jobs_root,key)
                if saved:
                    return {'id':saved['id'],'cached':True}
            problems = dependency_status()
            required = ('pandas','numpy','networkx','scipy','pyproj') if kind=='process' else ('fiona','shapely')
            missing = [name for name in required if name in problems]
            if missing:
                raise ModuleNotFoundError('Dependências indisponíveis neste Python: '+', '.join(missing)+'. Use o ambiente configurado.')
            if sum(not j['future'].done() for j in self.jobs.values())>=8:
                raise ValueError('Fila cheia. Aguarde a conclusão das tarefas.')
            job_id=uuid.uuid4().hex
            write_json(self.jobs_root/job_id/'state.json',{'id':job_id,'kind':kind,'args':args,'status':'queued'})
            future=self.pool.submit(run_job,kind,args,str(input_root),str(self.jobs_root),str(self.cache_root),job_id,self.max_bytes)
            self.jobs[job_id]={'future':future,'kind':kind,'args':args}
        return {'id':job_id,'cached':False}

    def snapshot(self, job_id):
        if not re.fullmatch(r'[a-f0-9]{32}',job_id):
            raise ValueError('Identificador de tarefa inválido')
        job=self.jobs.get(job_id)
        log=self.jobs_root/job_id/'log.txt'
        if log.exists():
            with log.open('rb') as stream:
                stream.seek(max(0,log.stat().st_size-16000))
                content=stream.read().decode('utf-8',errors='replace')
        else:
            content=''
        if job is None:
            state=json.loads((self.jobs_root/job_id/'state.json').read_text(encoding='utf-8'))
            if state.get('status') in ('queued','running'):
                state.update(status='failed',error='Tarefa interrompida pela reinicialização do serviço. Execute novamente.')
            return {**state,'log':content}
        future=job['future']
        state={'id':job_id,'kind':job['kind'],'status':'running' if future.running() else 'queued','log':content}
        if future.done():
            try:
                state.update(status='completed',result=future.result())
            except Exception as exc:
                state.update(status='failed',error=str(exc))
        return state


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,service,access=None,**kwargs):
        self.access=access
        self.service=service
        super().__init__(*args,directory=str(ROOT/'web'),**kwargs)

    def log_message(self, format, *args):
        # PyInstaller's windowed app has no stderr; request logging must not break HTTP.
        if sys.stderr is not None:
            super().log_message(format, *args)

    def end_headers(self):
        if self.headers.get('Origin') == PAGES_ORIGIN and self.access is not None:
            self.send_header('Access-Control-Allow-Origin',PAGES_ORIGIN)
            self.send_header('Vary','Origin')
        super().end_headers()

    def allowed(self, pairing=False):
        if not self.local_host():
            self.reply({'error':'Host não autorizado'},403)
            return False
        origin=self.headers.get('Origin')
        if origin == 'http://' + self.headers.get('Host',''):
            return True
        if not origin and self.headers.get('Sec-Fetch-Site') not in ('cross-site','same-site'):
            return True
        if origin != PAGES_ORIGIN or self.access is None:
            self.reply({'error':'Origem não autorizada'},403)
            return False
        if pairing or self.access.authorized(self.headers.get('Authorization')):
            return True
        self.reply({'error':'Conecte usando o código exibido no SUCURI Local.'},401)
        return False

    def do_OPTIONS(self):
        if not self.local_host() or self.access is None or self.headers.get('Origin') != PAGES_ORIGIN:
            return self.reply({'error':'Origem não autorizada'},403)
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Private-Network','true')
        self.send_header('Content-Length','0')
        self.end_headers()

    def reply(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(body)

    def local_host(self):
        return self.headers.get('Host','').split(':')[0] in ('127.0.0.1','localhost')

    def do_GET(self):
        if not self.allowed():
            return
        url=urllib.parse.urlsplit(self.path)
        query=urllib.parse.parse_qs(url.query)
        value=lambda k,default='':query.get(k,[default])[0]
        try:
            if url.path=='/api/health':
                return self.reply({'ok':True,'import_available':not any(k in dependency_status() for k in ('fiona','shapely')),'process_available':not any(k in dependency_status() for k in ('pandas','numpy','networkx','scipy','pyproj')),'dependency_errors':dependency_status(),'python':sys.executable,'storage':{'bases':str(self.service.data),'downloads':str(self.service.cache_root),'jobs':str(self.service.jobs_root),'read_roots':[str(p) for p in self.service.read_roots]}})
            if url.path=='/api/datasets':
                return self.reply(self.service.datasets())
            if url.path=='/api/feeders':
                return self.reply(self.service.feeders(value('dataset')))
            if url.path=='/api/cache':
                return self.reply(self.service.cache_status({'dataset':value('dataset'),'feeder':value('feeder'),'crs':value('crs','EPSG:4326')}))
            if url.path=='/api/catalog':
                return self.reply(catalog(value('q'),max(1,int(value('start','1')))))
            parts=url.path.strip('/').split('/')
            if len(parts)>=3 and parts[:2]==['api','jobs']:
                job_id=parts[2]
                state=self.service.snapshot(job_id)
                if len(parts)==3:
                    return self.reply(state)
                if len(parts)!=4 or parts[3] not in ('network.geojson','powerflow.zip','report.json') or state['status']!='completed':
                    raise ValueError('Resultado não disponível')
                path=self.service.jobs_root/job_id/parts[3]
                self.send_response(200)
                self.send_header('Content-Type','application/zip' if path.suffix=='.zip' else 'application/json')
                self.send_header('Content-Length',str(path.stat().st_size))
                self.send_header('Content-Disposition',f'attachment; filename="{path.name}"')
                self.end_headers()
                with path.open('rb') as f:
                    import shutil
                    shutil.copyfileobj(f,self.wfile)
                return
            if url.path.startswith('/api/'):
                return self.reply({'error':'Endpoint inexistente'},404)
            return super().do_GET()
        except (ValueError,KeyError,FileNotFoundError) as exc:
            return self.reply({'error':str(exc)},400)
        except Exception as exc:
            return self.reply({'error':str(exc)},502)

    def do_POST(self):
        if not self.allowed(pairing=self.path=='/api/pair'):
            return
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            return self.reply({'error':'Content-Type application/json obrigatório'},415)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8192:
                raise ValueError('Tamanho de requisição inválido')
            body=json.loads(self.rfile.read(size))
            if self.path=='/api/pair' and self.access is not None:
                return self.reply({'token':self.access.pair(body.get('code'))})
            if self.path!='/api/jobs':
                return self.reply({'error':'Endpoint inexistente'},404)
            return self.reply(self.service.submit(body['kind'],body['args']),202)
        except (ValueError,KeyError,TypeError,FileNotFoundError) as exc:
            return self.reply({'error':str(exc)},400)
        except (ImportError, OSError) as exc:
            self.log_error('Falha ao iniciar tarefa: %s', exc)
            return self.reply({'error':str(exc)},503)
        except Exception as exc:
            self.log_error('Falha inesperada ao iniciar tarefa: %s', exc)
            return self.reply({'error':'Não foi possível iniciar a tarefa: ' + str(exc)},500)



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8081)
    storage_root = storage_path()
    parser.add_argument('--data',default=str(storage_root/'bases'))
    parser.add_argument('--runtime',default=str(storage_root/'runtime'))
    parser.add_argument('--legacy-data',default=str(ROOT/'Dados_BDGD'))
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--max-download-gb',type=float,default=4)
    args=parser.parse_args()
    if not 1<=args.workers<=4 or not 0<args.max_download_gb<=20:
        parser.error('Use 1–4 workers e limite de download de 0–20 GB')
    if not storage_root.parent.is_dir() and (args.data == str(storage_root/'bases') or args.runtime == str(storage_root/'runtime')):
        parser.error('Disco de armazenamento indisponível: ' + str(storage_root.parent))
    service=Service(args.data,args.runtime,args.workers,args.max_download_gb,legacy_data=args.legacy_data)
    access=Access()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,service=service,access=access))
    print(f'Código para conectar o GitHub Pages (10 minutos): {access.code}',flush=True)
    print(f'SUCURI http://127.0.0.1:{args.port}',flush=True)
    print(f'Novas bases: {service.data} | Resultados e downloads: {service.runtime}',flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        service.pool.shutdown(wait=True)


if __name__=='__main__':
    main()
