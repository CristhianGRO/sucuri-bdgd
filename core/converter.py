import os
import shutil
import tempfile
import pandas as pd
import geopandas as gpd
import fiona
import warnings
import gc
from shapely.geometry import shape
from typing import Callable

warnings.filterwarnings("ignore")


class GeoDataConverter:

    CHUNK = 20000

    LAYER_MAPPING = {
        'SSDMT': ['SSDMT'],
        'SSDBT': ['SSDBT'],
        'UNTRMT': ['UNTRMT'],
        'UNTRAT': ['UNTRAT'],
        'UNSEMT': ['UNSEMT'],
        'UNSEBT': ['UNSEBT'],
        'RAMLIG': ['RAMLIG'],
        'UCBT':  ['UCBT'],
        'UCMT':  ['UCMT'],
        'UCAT':  ['UCAT'],
        'CTMT':  ['CTMT'],
        'PONNOT': ['PONNOT'],
        'SEGCON': ['SEGCON'],
        'CRVCRG': ['CRVCRG']
    }

    def __init__(self, log_callback: Callable[[str], None]):
        self.log = log_callback
        self.temp_dir = None

    def convert_folder(self, source_path, out_base, distributor):

        out_dir = os.path.join(out_base, distributor)
        os.makedirs(out_dir, exist_ok=True)

        self.log("=== BDGD ingestion start ===")

        gdb = source_path
        if not gdb.lower().endswith(".gdb"):
            for f in os.listdir(source_path):
                if f.lower().endswith(".gdb"):
                    gdb = os.path.join(source_path, f)

        layers = fiona.listlayers(gdb)
        self.log(f"GDB layers: {len(layers)}")

        for layer in layers:
            std = self._identify(layer.upper())
            if not std:
                continue

            try:
                self.log(f"Processing {layer} → {std}")
                self._export_layer_stream(gdb, layer, std, out_dir)
            except Exception as e:
                self.log(f"Layer error {layer}: {e}")

            gc.collect()

        self.log("=== BDGD ingestion done ===")

    def _identify(self, name):
        for k, v in self.LAYER_MAPPING.items():
            for p in v:
                if p in name:
                    return k
        return None

    def _export_layer_stream(self, gdb, layer, name, out_dir):

        out = os.path.join(out_dir, f"{name}.csv")
        tmp = out + ".tmp"

        first = True
        batch = []

        with fiona.open(gdb, layer=layer) as src:

            for feat in src:

                row = dict(feat["properties"])

                geom = feat.get("geometry")

                if geom:
                    try:
                        pt = shape(geom).centroid
                        row["X"] = pt.x
                        row["Y"] = pt.y
                    except:
                        row["X"] = None
                        row["Y"] = None

                batch.append(row)

                if len(batch) >= self.CHUNK:
                    self._write_batch(batch, tmp, first)
                    first = False
                    batch.clear()

            if batch:
                self._write_batch(batch, tmp, first)

        os.replace(tmp, out)
        self.log(f"Saved {name} (stream)")

    def _write_batch(self, rows, path, first):

        df = pd.DataFrame(rows)

        df.to_csv(
            path,
            mode="w" if first else "a",
            header=first,
            index=False
        )
