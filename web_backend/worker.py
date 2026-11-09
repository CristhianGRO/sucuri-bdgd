"""Local SUCURI workers. No GUI or HTTP state is shared between processes."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCGIS = 'https://www.arcgis.com/sharing/rest'
OWNER = 'aneel_aneel'


def remote_json(path, params=None):
    url = ARCGIS + path + '?' + urllib.parse.urlencode({'f': 'json', **(params or {})})
    req = urllib.request.Request(url, headers={'User-Agent': 'Sucuri-BDGD/0.2'})
    with urllib.request.urlopen(req, timeout=45) as response:
        result = json.load(response)
    if 'error' in result:
        raise ValueError(str(result['error']))
    return result


def catalog(query='', start=1):
    words = re.findall(r'[\w-]+', query, re.UNICODE)
    q = f'owner:{OWNER} AND type:"File Geodatabase"'
    if words:
        q += ' AND ' + ' AND '.join('"' + word + '"' for word in words)
    result = remote_json('/search', {'q': q, 'num': 30, 'start': start, 'sortField': 'modified', 'sortOrder': 'desc'})
    return {'total': result.get('total', 0), 'next': result.get('nextStart', -1), 'items': [
        {'id': item['id'], 'title': item['title'], 'size': item.get('size', 0), 'modified': item.get('modified')}
        for item in result.get('results', []) if item.get('owner') == OWNER and item.get('type') == 'File Geodatabase']}


def safe_child(base, name):
    if not isinstance(name, str) or not re.fullmatch(r'[\w.-]+', name) or name in ('.', '..'):
        raise ValueError('Identificador inválido')
    base = Path(base).resolve()
    child = (base / name).resolve()
    if child.parent != base:
        raise ValueError('Caminho fora da base')
    return child


def extract_archive(archive, target, max_bytes):
    target = Path(target).resolve()
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > max_bytes:
            raise ValueError('Arquivo descompactado excede o limite configurado')
        for item in z.infolist():
            # Reject traversal and symbolic links before extracting any member.
            name = item.filename.replace('\\', '/')
            dest = (target / name).resolve()
            if target not in dest.parents or ':' in name or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Caminho inseguro no ZIP')
        z.extractall(target)


def import_aneel(item_id, data_root, cache_root, log, max_bytes):
    import fiona
    from fiona.transform import transform
    from shapely.geometry import shape
    if not re.fullmatch(r'[a-f0-9]{32}', item_id):
        raise ValueError('Identificador ArcGIS inválido')
    item = remote_json('/content/items/' + item_id)
    if item.get('owner') != OWNER or item.get('type') != 'File Geodatabase' or item.get('access') != 'public':
        raise ValueError('O recurso não é um GDB público do catálogo oficial configurado')
    if item.get('size', 0) > max_bytes:
        raise ValueError('Download excede o limite configurado')
    dest = safe_child(data_root, 'ANEEL_' + item_id)
    if (dest / 'source.json').exists():
        log('Base já importada; reutilizando cópia local.')
        return {'dataset': dest.name}
    cache = Path(cache_root) / item_id
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / 'source.zip'
    temporary = cache / 'source.zip.part'
    digest = hashlib.sha256()
    size = 0
    log('Baixando ' + item['title'])
    req = urllib.request.Request(ARCGIS + '/content/items/' + item_id + '/data', headers={'User-Agent': 'Sucuri-BDGD/0.2'})
    try:
        with urllib.request.urlopen(req, timeout=60) as response, temporary.open('wb') as out:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > max_bytes:
                    raise ValueError('Download excede o limite configurado')
                digest.update(block)
                out.write(block)
                if size % (32 * 1024 * 1024) == 0:
                    log(f'Download: {size // (1024*1024)} MB')
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    extraction = cache / 'extracted'
    extraction.mkdir(exist_ok=True)
    log('Validando e extraindo GDB')
    extract_archive(archive, extraction, max_bytes * 8)
    gdbs = list(extraction.rglob('*.gdb'))
    if len(gdbs) != 1:
        raise ValueError('Esperado exatamente um diretório .gdb no arquivo')
    gdb = gdbs[0]
    stage = cache / 'csv'
    stage.mkdir(exist_ok=True)
    wanted = {'SEGCON','CRVCRG','UNTRAT','CTMT','SSDMT','SSDBT','UNSEMT','UNSEBT','UNTRMT','RAMLIG','UCBT','PONNOT','UCMT','UCAT'}
    found = {}
    for layer in fiona.listlayers(gdb):
        standard = layer.upper().split('.')[-1]
        if standard not in wanted:
            continue
        if standard in found:
            raise ValueError('Camada duplicada: ' + standard)
        found[standard] = layer
        log('Convertendo ' + standard)
        with fiona.open(gdb, layer=layer) as src, (stage / (standard + '.csv')).open('w', encoding='utf-8', newline='') as target:
            fields = list(src.schema['properties'])
            fields += [k for k in ('X','Y') if k not in fields]
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            for f in src:
                row = dict(f['properties'])
                if f['geometry']:
                    if not src.crs:
                        raise ValueError('Camada sem CRS: ' + layer)
                    centroid = shape(f['geometry']).centroid
                    xs, ys = transform(src.crs, 'EPSG:4326', [centroid.x], [centroid.y])
                    row.update(X=xs[0], Y=ys[0])
                writer.writerow(row)
    if not {'CTMT','SSDMT','PONNOT'}.issubset(found):
        raise ValueError('GDB não contém as camadas mínimas CTMT, SSDMT e PONNOT com nomes reconhecidos')
    (stage / 'source.json').write_text(json.dumps({'title':item['title'],'item_id':item_id,'sha256':digest.hexdigest(),'gdb':str(gdb),'layers':found,'crs':'EPSG:4326'},ensure_ascii=False),encoding='utf-8')
    # Publish only a complete CSV dataset; partial copies remain outside the catalog.
    publish = Path(tempfile.mkdtemp(prefix='.import-', dir=data_root))
    try:
        shutil.copytree(stage, publish, dirs_exist_ok=True)
        os.replace(publish, dest)
    finally:
        if publish.exists():
            shutil.rmtree(publish)
    log('Base pronta. Geometrias originais preservadas no GDB em cache.')
    return {'dataset': dest.name}


CONSUMER_FIELDS = ('CLAS_SUB', 'FAS_CON', 'TIP_CC', 'GRU_TEN', 'TEN_FORN', 'GRU_TAR')


def _clean_id(value):
    return str(value or '').strip().upper()


def _consumer_rows(values):
    rows = values.get('ucbt_rows')
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    row = values.get('ucbt_row')
    return [row] if isinstance(row, dict) else []


def consumer_payload(rows, limit=200):
    """Produz dados de visualização, sem expor o registro completo da UC."""
    classes = {}
    consumers = []
    for row in rows:
        consumer_class = str(row.get('CLAS_SUB') or 'Não informado').strip() or 'Não informado'
        classes[consumer_class] = classes.get(consumer_class, 0) + 1
        if len(consumers) < limit:
            consumer_id = str(row.get('COD_ID') or row.get('NUM_UC') or row.get('CEG') or '').strip()
            consumers.append({'id': consumer_id or 'Sem identificador', 'class': consumer_class})
    return {
        'consumer_count': len(rows),
        'consumer_classes': classes,
        'consumers': consumers,
        'consumer_list_truncated': len(rows) > len(consumers),
    }


def transformer_consumer_summaries(graph):
    """Agrega as UCs alcançáveis pela rede BT de cada transformador."""
    summaries = {}
    low_voltage_edges = {'SSDBT', 'RAMLIG'}
    for left, right, edge in graph.edges(data=True):
        if edge.get('tipo') != 'MT_BT_Transformer_Connection':
            continue
        secondary = right if graph.nodes[right].get('tipo_no') == 'Transformer_Sec' else left
        queue = [secondary]
        seen = {secondary}
        rows = []
        while queue:
            node = queue.pop()
            rows.extend(_consumer_rows(graph.nodes[node]))
            for neighbor in graph.neighbors(node):
                branch = graph.get_edge_data(node, neighbor) or {}
                if branch.get('tipo') not in low_voltage_edges or neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        if rows:
            summaries[_clean_id(secondary)] = consumer_payload(rows)
    return summaries


def consumer_anchor_features(graph, coordinates, ctmt):
    """Cria pontos de visualização nas barras que concentram UCs sem geometria."""
    features = []
    for node, values in graph.nodes(data=True):
        rows = _consumer_rows(values)
        if node not in coordinates or not rows:
            continue
        features.append({
            'type': 'Feature',
            'properties': {
                'CTMT': ctmt,
                'COD_ID': 'CONSUMERS_' + str(node),
                'PAC': str(node),
                'tipo': 'ConsumerAnchor',
                **consumer_payload(rows),
            },
            'geometry': {'type': 'Point', 'coordinates': coordinates[node]},
        })
    return features


def graph_geojson(graph, ctmt, crs):
    from pyproj import Transformer
    transformer = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    coordinates = {}
    features = []
    missing = 0
    summaries = transformer_consumer_summaries(graph)
    def props(node, values):
        result = {k: str(v) for k,v in values.items() if not k.startswith('_') and k not in ('ucbt_row','ucbt_rows','trafo_row')}
        consumer = values.get('ucbt_row')
        if isinstance(consumer, dict):
            for key in CONSUMER_FIELDS:
                value = consumer.get(key)
                if value is not None and str(value).strip().lower() not in ('nan','none',''):
                    result[key] = str(value)
        rows = _consumer_rows(values)
        if rows:
            result.update(consumer_payload(rows))
        summary = summaries.get(_clean_id(node))
        if summary:
            result['consumer_summary'] = summary
        return result
    for node, d in graph.nodes(data=True):
        try:
            x,y = transformer.transform(float(d['x']), float(d['y']))
            if not math.isfinite(x+y) or abs(x)>180 or abs(y)>90:
                raise ValueError('coordinate')
            coordinates[node] = [x,y]
            features.append({'type':'Feature','properties':{**props(node,d),'CTMT':ctmt,'COD_ID':str(node)},'geometry':{'type':'Point','coordinates':[x,y]}})
        except (KeyError,ValueError,TypeError):
            missing += 1
    for u,v,d in graph.edges(data=True):
        if u in coordinates and v in coordinates:
            features.append({'type':'Feature','properties':{**props('',d),'CTMT':ctmt,'COD_ID':str(d.get('id',str(u)+'_'+str(v))),'geometria':'Ligação reta entre nós; não é o traçado original'},'geometry':{'type':'LineString','coordinates':[coordinates[u],coordinates[v]]}})
    return {'type':'FeatureCollection','features':features}, missing


def append_consumer_visuals(path, graph, ctmt, crs):
    """Acrescenta âncoras de UCs e resumos aos traços originais BDGD."""
    generated, _ = graph_geojson(graph, ctmt, crs)
    anchors = [feature for feature in generated['features'] if feature['properties'].get('tipo_no') == 'UCBT' and feature['properties'].get('consumer_count')]
    summaries = transformer_consumer_summaries(graph)
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    for feature in document['features']:
        props = feature.get('properties') or {}
        summary = summaries.get(_clean_id(props.get('PAC_2')))
        if summary and str(props.get('tipo') or '').upper().split('.')[-1] == 'UNTRMT':
            props['consumer_summary'] = summary
    # Os nós UCBT gerados são âncoras na barra: as coordenadas vêm do grafo,
    # não da unidade consumidora, que pode não ter geometria própria.
    for feature in anchors:
        pac = feature['properties']['COD_ID']
        feature['properties']['PAC'] = pac
        feature['properties']['COD_ID'] = 'CONSUMERS_' + pac
        feature['properties']['tipo'] = 'ConsumerAnchor'
    document['features'].extend(anchors)
    Path(path).write_text(json.dumps(document, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def _run_job_impl(kind, args, data_root, jobs_root, cache_root, job_id, max_bytes):
    import contextlib
    job = Path(jobs_root) / job_id
    job.mkdir(parents=True, exist_ok=True)
    with (job / 'log.txt').open('a',encoding='utf-8',buffering=1) as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        def log(message):
            print(message, flush=True)
        try:
            if kind == 'import':
                return import_aneel(args['item_id'], data_root, cache_root, log, max_bytes)
            from app.controller import Controller
            dataset = safe_child(data_root, args['dataset'])
            ctmt = args['feeder']
            safe_child(dataset, ctmt)
            ctrl = Controller(log)
            ctrl.base_path = str(data_root)
            result = ctrl.run_feeder_process(dataset.name, ctmt, '', True, 'Modelo Completo', output_base=str(job / 'output'), strict=True)
            if not result:
                raise ValueError('Motor não retornou um resultado')
            geo, missing = graph_geojson(result['graph'], ctmt, args.get('crs','EPSG:4326'))
            geometry_mode = 'Ligações retas do grafo'
            metadata = dataset / 'source.json'
            if metadata.exists():
                from web.tools.export_geojson import export
                source = json.loads(metadata.read_text(encoding='utf-8'))
                layers = [v for k,v in source['layers'].items() if k in ('SSDMT','SSDBT','UNTRMT','UNSEMT','UNSEBT','RAMLIG','UCBT','UCMT')]
                export(source['gdb'], job / 'network.geojson', layers, {ctmt})
                append_consumer_visuals(job / 'network.geojson', result['graph'], ctmt, args.get('crs','EPSG:4326'))
                geometry_mode = 'Geometrias originais BDGD (associação direta por CTMT)'
            else:
                if not geo['features']:
                    raise ValueError('Rede sem coordenadas válidas; confira o CRS da base')
                (job/'network.geojson').write_text(json.dumps(geo,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            summary = {'dataset':dataset.name,'feeder':ctmt,'nodes':result['graph'].number_of_nodes(),'edges':result['graph'].number_of_edges(),'nodes_without_coordinates':missing,'geometry':geometry_mode,'note':'Arquivos de entrada para fluxo de potência; não representam uma simulação executada. O motor legado ainda requer validação elétrica.'}
            (job/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
            with zipfile.ZipFile(job/'powerflow.zip','w',zipfile.ZIP_DEFLATED) as archive:
                for path in Path(result['output']).rglob('*'):
                    if path.is_file():
                        archive.write(path,path.relative_to(result['output']))
                archive.write(job/'report.json','report.json')
            log('Concluído; exportação elétrica e mapa disponíveis.')
            return summary
        except Exception as exc:
            log('Falha: ' + str(exc))
            raise


def run_job(kind, args, data_root, jobs_root, cache_root, job_id, max_bytes):
    from .result_cache import write_json, fingerprint, publish_cached
    from datetime import datetime, timezone
    job = Path(jobs_root)/job_id
    state = {'id':job_id,'kind':kind,'args':args,'status':'running'}
    write_json(job/'state.json', state)
    try:
        result = _run_job_impl(kind,args,data_root,jobs_root,cache_root,job_id,max_bytes)
        state.update(status='completed',result=result,completed_at=datetime.now(timezone.utc).isoformat())
        key = args.get('_cache_key')
        if kind == 'process' and key:
            if key == fingerprint(safe_child(data_root,args['dataset']),args['feeder'],args['crs']):
                state['cache_key'] = key
        write_json(job/'state.json',state)
        if state.get('cache_key'):
            publish_cached(jobs_root,key,job_id)
        return result
    except Exception as exc:
        state.update(status='failed',error=str(exc))
        write_json(job/'state.json',state)
        raise
