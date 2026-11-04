"""Exporta um recorte geográfico BDGD para o visualizador, preservando geometrias.

Requer fiona e pyproj, já utilizados pelo conversor existente.
Não forma a topologia elétrica nem produz um modelo de fluxo de potência.
"""
import argparse
import json
import math
import os
from pathlib import Path
import tempfile


def export(source, output, layers, feeders):
    import fiona
    from fiona.transform import transform_geom
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    skipped = 0
    fd, temporary = tempfile.mkstemp(dir=output.parent, suffix='.geojson.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as target:
            target.write('{"type":"FeatureCollection","features":[')
            for name in layers:
                with fiona.open(source, layer=name) as src:
                    if not src.crs:
                        raise ValueError(f'Camada {name} sem CRS; informe/corrija a referência antes de exportar.')
                    for feature in src:
                        props = dict(feature['properties'])
                        ctmt = str(props.get('CTMT') or '').strip()
                        if ctmt not in feeders:
                            continue
                        geom = feature['geometry']
                        if not geom or geom['type'] not in ('Point', 'LineString', 'MultiLineString'):
                            skipped += 1
                            continue
                        projected = transform_geom(src.crs, 'EPSG:4326', geom)
                        props['CTMT'] = ctmt
                        props['tipo'] = name
                        props = {k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in props.items()}
                        record = {'type': 'Feature', 'properties': props, 'geometry': {'type': projected['type'], 'coordinates': projected['coordinates']}}
                        if count:
                            target.write(',')
                        target.write(json.dumps(record, ensure_ascii=False, default=str, allow_nan=False))
                        count += 1
            target.write(']}')
        if not count:
            raise ValueError('Nenhum elemento encontrado. Verifique os nomes das camadas e os códigos CTMT.')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'{count} elementos exportados para {output}; {skipped} geometrias ausentes/não suportadas.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Diretório .gdb original')
    parser.add_argument('output', help='Arquivo .geojson de saída')
    parser.add_argument('--layers', nargs='+', required=True, help='Nomes exatos das camadas do GDB')
    parser.add_argument('--feeders', nargs='+', required=True, help='Códigos CTMT desejados')
    args = parser.parse_args()
    export(args.source, args.output, args.layers, set(args.feeders))
