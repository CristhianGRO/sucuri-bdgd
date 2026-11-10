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
WANTED_LAYERS = {'SEGCON','CRVCRG','UNTRAT','CTMT','SSDMT','SSDBT','UNSEMT','UNSEBT','UNTRMT','RAMLIG','UCBT','PONNOT','UCMT','UCAT'}


def standard_layer_name(layer):
    """Normaliza nomes BDGD, inclusive as tabelas ``*_tab`` da CPFL."""
    name = layer.upper().split('.')[-1]
    return re.sub(r'_TAB$', '', name)


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


def write_gdb_layer_csv(gdb, layer, standard, destination):
    """Converte uma camada ou tabela GDB para o CSV usado pelo motor."""
    import fiona
    from fiona.transform import transform
    from shapely.geometry import shape
    with fiona.open(gdb, layer=layer) as src, Path(destination).open('w', encoding='utf-8', newline='') as target:
        fields = list(src.schema['properties'])
        fields += [key for key in ('X', 'Y') if key not in fields]
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for feature in src:
            row = dict(feature['properties'])
            if feature['geometry']:
                if not src.crs:
                    raise ValueError('Camada sem CRS: ' + layer)
                centroid = shape(feature['geometry']).centroid
                xs, ys = transform(src.crs, 'EPSG:4326', [centroid.x], [centroid.y])
                row.update(X=xs[0], Y=ys[0])
            writer.writerow(row)


def migrate_consumer_table(dest, log):
    """Acrescenta UCBT de bases já importadas que usavam o nome UCBT_tab."""
    metadata_path = Path(dest) / 'source.json'
    if not metadata_path.exists():
        return False
    source = json.loads(metadata_path.read_text(encoding='utf-8'))
    if 'UCBT' in source.get('layers', {}):
        return False
    gdb = Path(source.get('gdb', ''))
    if not gdb.is_dir():
        return False
    import fiona
    for layer in fiona.listlayers(gdb):
        if standard_layer_name(layer) != 'UCBT':
            continue
        log('Atualizando UCBT a partir da tabela ' + layer)
        temporary = Path(dest) / '.UCBT.csv.part'
        try:
            write_gdb_layer_csv(gdb, layer, 'UCBT', temporary)
            os.replace(temporary, Path(dest) / 'UCBT.csv')
        finally:
            temporary.unlink(missing_ok=True)
        source['layers']['UCBT'] = layer
        metadata_path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
        log('Tabela UCBT adicionada à base local.')
        return True
    return False


def import_aneel(item_id, data_root, cache_root, log, max_bytes):
    if not re.fullmatch(r'[a-f0-9]{32}', item_id):
        raise ValueError('Identificador ArcGIS inválido')
    item = remote_json('/content/items/' + item_id)
    if item.get('owner') != OWNER or item.get('type') != 'File Geodatabase' or item.get('access') != 'public':
        raise ValueError('O recurso não é um GDB público do catálogo oficial configurado')
    if item.get('size', 0) > max_bytes:
        raise ValueError('Download excede o limite configurado')
    dest = safe_child(data_root, 'ANEEL_' + item_id)
    if (dest / 'source.json').exists():
        if migrate_consumer_table(dest, log):
            log('Base existente atualizada com UCBT; reprocese o alimentador.')
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
    import fiona
    found = {}
    for layer in fiona.listlayers(gdb):
        standard = standard_layer_name(layer)
        if standard not in WANTED_LAYERS:
            continue
        if standard in found:
            raise ValueError('Camada duplicada: ' + standard)
        found[standard] = layer
        log('Convertendo ' + standard)
        write_gdb_layer_csv(gdb, layer, standard, stage / (standard + '.csv'))
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


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def consumer_profile_index(path):
    """Lê as curvas CRVCRG uma vez e as indexa por TIP_CC e tipo de dia."""
    profiles = {}
    path = Path(path)
    if not path.exists():
        return profiles
    with path.open(encoding='utf-8', newline='') as source:
        for row in csv.DictReader(source):
            code = _clean_id(row.get('COD_ID'))
            values = [_number(row.get(f'POT_{index:02d}')) for index in range(1, 97)]
            if not code or not any(value is not None for value in values):
                continue
            profiles.setdefault(code, []).append({
                'day': str(row.get('TIP_DIA') or 'Típico').strip() or 'Típico',
                'points': [value or 0 for value in values],
            })
    return profiles


def consumer_profile_summary(rows, profile_index):
    """Média dos perfis típicos, normalizada em percentual do pico."""
    grouped = {}
    for row in rows:
        for profile in profile_index.get(_clean_id(row.get('TIP_CC')), []):
            item = grouped.setdefault(profile['day'], {'totals': [0] * 96, 'count': 0})
            item['totals'] = [left + right for left, right in zip(item['totals'], profile['points'])]
            item['count'] += 1
    result = []
    for day, item in sorted(grouped.items()):
        average = [value / item['count'] for value in item['totals']]
        peak = max(average, default=0)
        if peak:
            average = [round(value / peak * 100, 1) for value in average]
        result.append({'day': day, 'points': average, 'profiles': item['count']})
    return result


def consumer_detail(row, profile_index):
    """Campos de uma UC que podem aparecer ao selecionar sua folha no mapa."""
    energy = [_number(row.get(f'ENE_{index:02d}')) or 0 for index in range(1, 13)]
    dic = [_number(row.get(f'DIC_{index:02d}')) for index in range(1, 13)]
    fic = [_number(row.get(f'FIC_{index:02d}')) for index in range(1, 13)]
    detail = {
        'id': str(row.get('COD_ID') or row.get('NUM_UC') or row.get('CEG') or '').strip() or 'Sem identificador',
        'class': str(row.get('CLAS_SUB') or 'Não informado').strip() or 'Não informado',
        'profile_code': str(row.get('TIP_CC') or '').strip(),
    }
    capacity = _number(row.get('CAR_INST'))
    if capacity is not None:
        detail['installed_load_kw'] = round(capacity, 2)
    if any(energy):
        detail['energy_monthly_kwh'] = [round(value, 2) for value in energy]
        detail['energy_annual_kwh'] = round(sum(energy), 2)
    dic = [value for value in dic if value is not None]
    fic = [value for value in fic if value is not None]
    if dic:
        detail['dic_monthly_mean'] = round(sum(dic) / len(dic), 2)
    if fic:
        detail['fic_monthly_mean'] = round(sum(fic) / len(fic), 2)
    profiles = consumer_profile_summary([row], profile_index)
    if profiles:
        detail['typical_profiles'] = profiles
    return detail


def consumer_payload(rows, profile_index=None, limit=200, include_details=False):
    """Produz indicadores agregados de UCs, sem expor seu registro completo."""
    classes = {}
    consumers = []
    energy = [0] * 12
    capacities = []
    dic = []
    fic = []
    for row in rows:
        consumer_class = str(row.get('CLAS_SUB') or 'Não informado').strip() or 'Não informado'
        classes[consumer_class] = classes.get(consumer_class, 0) + 1
        capacity = _number(row.get('CAR_INST'))
        if capacity is not None:
            capacities.append(capacity)
        for index in range(1, 13):
            energy[index - 1] += _number(row.get(f'ENE_{index:02d}')) or 0
            value = _number(row.get(f'DIC_{index:02d}'))
            if value is not None:
                dic.append(value)
            value = _number(row.get(f'FIC_{index:02d}'))
            if value is not None:
                fic.append(value)
        if len(consumers) < limit:
            consumer_id = str(row.get('COD_ID') or row.get('NUM_UC') or row.get('CEG') or '').strip()
            consumers.append(
                consumer_detail(row, profile_index or {}) if include_details
                else {'id': consumer_id or 'Sem identificador', 'class': consumer_class}
            )
    result = {
        'consumer_count': len(rows),
        'consumer_classes': classes,
        'consumers': consumers,
        'consumer_list_truncated': len(rows) > len(consumers),
    }
    if capacities:
        result['installed_load_kw'] = round(sum(capacities), 2)
    if any(energy):
        result['energy_monthly_kwh'] = [round(value, 2) for value in energy]
        result['energy_annual_kwh'] = round(sum(energy), 2)
    if dic:
        result['dic_monthly_mean'] = round(sum(dic) / len(dic), 2)
    if fic:
        result['fic_monthly_mean'] = round(sum(fic) / len(fic), 2)
    profiles = consumer_profile_summary(rows, profile_index or {})
    if profiles:
        result['typical_profiles'] = profiles
    return result


def transformer_consumer_summaries(graph, profile_index=None):
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
            summaries[_clean_id(secondary)] = consumer_payload(rows, profile_index)
    return summaries


def _connected_coordinate(graph, node, coordinates, max_depth=80):
    """Procura a barra georreferenciada mais próxima pela topologia BT."""
    allowed = {'SSDBT', 'RAMLIG', 'MT_BT_Transformer_Connection'}
    queue = [(node, 0)]
    seen = {node}
    while queue:
        current, depth = queue.pop(0)
        if current in coordinates:
            return coordinates[current], current
        if depth >= max_depth:
            continue
        for neighbor in graph.neighbors(current):
            edge = graph.get_edge_data(current, neighbor) or {}
            if edge.get('tipo') not in allowed or neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append((neighbor, depth + 1))
    return None, None


def _spread_coordinate(coordinate, node):
    """Evita sobreposição ao distribuir âncoras sem coordenada própria."""
    digest = hashlib.sha256(str(node).encode('utf-8')).digest()
    angle = int.from_bytes(digest[:2], 'big') / 65535 * math.tau
    radius_meters = 9 + digest[2] % 28
    longitude, latitude = coordinate
    latitude += math.sin(angle) * radius_meters / 111_320
    longitude += math.cos(angle) * radius_meters / (111_320 * max(math.cos(math.radians(latitude)), .2))
    return [longitude, latitude]


def consumer_anchor_features(graph, coordinates, ctmt, profile_index=None):
    """Cria pontos de visualização nas barras que concentram UCs sem geometria."""
    features = []
    for node, values in graph.nodes(data=True):
        rows = _consumer_rows(values)
        if not rows:
            continue
        coordinate = coordinates.get(node)
        approximate = coordinate is None
        anchor_node = node
        if approximate:
            coordinate, anchor_node = _connected_coordinate(graph, node, coordinates)
        if coordinate is None:
            continue
        if approximate:
            coordinate = _spread_coordinate(coordinate, node)
        features.append({
            'type': 'Feature',
            'properties': {
                'CTMT': ctmt,
                'COD_ID': 'CONSUMERS_' + str(node),
                'PAC': str(node),
                'tipo': 'ConsumerAnchor',
                'anchor_pac': str(anchor_node),
                'position_estimated': approximate,
                **consumer_payload(rows, profile_index, include_details=True),
            },
            'geometry': {'type': 'Point', 'coordinates': coordinate},
        })
    return features


def graph_geojson(graph, ctmt, crs, profile_index=None):
    from pyproj import Transformer
    transformer = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    coordinates = {}
    features = []
    missing = 0
    summaries = transformer_consumer_summaries(graph, profile_index)
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
            result.update(consumer_payload(rows, profile_index, include_details=True))
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
    features.extend(consumer_anchor_features(graph, coordinates, ctmt, profile_index))
    return {'type':'FeatureCollection','features':features}, missing


def append_consumer_visuals(path, graph, ctmt, crs, profile_index=None):
    """Acrescenta nós topológicos, âncoras de UCs e resumos à BDGD.

    O recorte GIS preserva os traçados reais, mas nem todas as barras são
    feições espaciais exportáveis. Os pontos gerados pelo grafo completam a
    leitura elétrica: subestação, nós MT e barras BT, inclusive onde há UCs.
    """
    generated, _ = graph_geojson(graph, ctmt, crs, profile_index)
    anchors = [feature for feature in generated['features'] if feature['properties'].get('tipo') == 'ConsumerAnchor']
    graph_nodes = [
        feature for feature in generated['features']
        if feature['geometry'].get('type') == 'Point'
        and feature['properties'].get('tipo') != 'ConsumerAnchor'
    ]
    summaries = transformer_consumer_summaries(graph, profile_index)
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    existing_pacs = set()
    for feature in document['features']:
        props = feature.get('properties') or {}
        for key in ('PAC', 'PAC_1', 'PAC_2', 'COD_ID'):
            value = _clean_id(props.get(key))
            if value:
                existing_pacs.add(value)
        summary = summaries.get(_clean_id(props.get('PAC_2')))
        if summary and str(props.get('tipo') or '').upper().split('.')[-1] == 'UNTRMT':
            props['consumer_summary'] = summary
    # Evita duplicar os transformadores/chaves que já têm geometria original,
    # mas mantém todas as barras calculadas que o recorte GIS não contém.
    for feature in graph_nodes:
        props = feature['properties']
        pac = _clean_id(props.get('COD_ID'))
        if pac in existing_pacs:
            continue
        props['map_source'] = 'Nó topológico calculado'
        document['features'].append(feature)
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
            if migrate_consumer_table(dataset, log):
                log('UCBT migrada da GDB original; incluindo consumidores no reprocessamento.')
            ctrl = Controller(log)
            ctrl.base_path = str(data_root)
            result = ctrl.run_feeder_process(dataset.name, ctmt, '', True, 'Modelo Completo', output_base=str(job / 'output'), strict=True)
            if not result:
                raise ValueError('Motor não retornou um resultado')
            profiles = consumer_profile_index(dataset / 'CRVCRG.csv')
            geo, missing = graph_geojson(result['graph'], ctmt, args.get('crs','EPSG:4326'), profiles)
            geometry_mode = 'Ligações retas do grafo'
            metadata = dataset / 'source.json'
            if metadata.exists():
                from web.tools.export_geojson import export
                source = json.loads(metadata.read_text(encoding='utf-8'))
                # UCBT/UCMT podem ser tabelas sem geometria (por exemplo,
                # UCBT_tab da CPFL). Elas entram no grafo, não no exportador
                # geográfico, que exige CRS por camada.
                layers = [v for k,v in source['layers'].items() if k in ('SSDMT','SSDBT','UNTRMT','UNSEMT','UNSEBT','RAMLIG')]
                export(source['gdb'], job / 'network.geojson', layers, {ctmt})
                append_consumer_visuals(job / 'network.geojson', result['graph'], ctmt, args.get('crs','EPSG:4326'), profiles)
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
