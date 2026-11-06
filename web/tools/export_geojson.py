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


def layer_crs(source):
    """Retorna a referência espacial exposta pelo Fiona, quando existir."""
    # Em algumas combinações de FileGDB/GDAL, a referência é exposta apenas
    # como WKT, embora a classe de feição tenha um CRS válido.
    return source.crs or source.crs_wkt or None


def _same_crs(left, right):
    """Compara CRSs sem depender da representação textual utilizada."""
    try:
        from pyproj import CRS
        return CRS.from_user_input(left) == CRS.from_user_input(right)
    except Exception:
        return left == right


def shared_crs(fiona, source, layers):
    """Obtém o CRS comum declarado pelas classes de feição solicitadas.

    Algumas bases BDGD não trazem metadados de CRS na RAMLIG. Nessas bases, as
    coordenadas da camada permanecem no mesmo sistema das demais classes da
    rede. A inferência só é feita quando as referências disponíveis concordam;
    referências incompatíveis continuam interrompendo a exportação.
    """
    reference = None
    reference_layer = None
    for name in layers:
        with fiona.open(source, layer=name) as src:
            crs = layer_crs(src)
        if not crs:
            continue
        if reference is None:
            reference, reference_layer = crs, name
        elif not _same_crs(reference, crs):
            raise ValueError(
                f'CRS incompatíveis nas camadas {reference_layer} e {name}; '
                'não é seguro inferir a referência espacial.'
            )
    return reference, reference_layer


def export(source, output, layers, feeders):
    import fiona
    from fiona.transform import transform_geom
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    skipped = 0
    fallback_crs, fallback_layer = shared_crs(fiona, source, layers)
    fd, temporary = tempfile.mkstemp(dir=output.parent, suffix='.geojson.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as target:
            target.write('{"type":"FeatureCollection","features":[')
            for name in layers:
                with fiona.open(source, layer=name) as src:
                    crs = layer_crs(src)
                    if not crs:
                        if not fallback_crs:
                            raise ValueError(f'Camada {name} sem CRS; informe/corrija a referência antes de exportar.')
                        crs = fallback_crs
                        print(f'Camada {name} sem CRS; usando o CRS comum da camada {fallback_layer}.')
                    for feature in src:
                        props = dict(feature['properties'])
                        ctmt = str(props.get('CTMT') or '').strip()
                        if ctmt not in feeders:
                            continue
                        geom = feature['geometry']
                        if not geom or geom['type'] not in ('Point', 'LineString', 'MultiLineString'):
                            skipped += 1
                            continue
                        projected = transform_geom(crs, 'EPSG:4326', geom)
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
