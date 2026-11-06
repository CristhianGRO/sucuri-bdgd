import contextlib
from types import SimpleNamespace
import unittest

from web.tools.export_geojson import shared_crs


class SharedCRSTest(unittest.TestCase):
    def _fiona(self, crs_by_layer):
        return SimpleNamespace(
            open=lambda source, layer: contextlib.nullcontext(
                SimpleNamespace(crs=crs_by_layer[layer][0], crs_wkt=crs_by_layer[layer][1])
            )
        )

    def test_uses_common_crs_when_ramlig_metadata_is_missing(self):
        fiona = self._fiona({
            'SSDMT': ('EPSG:31983', None),
            'RAMLIG': (None, None),
        })
        self.assertEqual(
            shared_crs(fiona, 'base.gdb', ['SSDMT', 'RAMLIG']),
            ('EPSG:31983', 'SSDMT'),
        )

    def test_uses_wkt_when_fiona_crs_is_empty(self):
        fiona = self._fiona({'SSDMT': (None, 'EPSG:31983')})
        self.assertEqual(
            shared_crs(fiona, 'base.gdb', ['SSDMT']),
            ('EPSG:31983', 'SSDMT'),
        )

    def test_rejects_incompatible_crs(self):
        fiona = self._fiona({
            'SSDMT': ('EPSG:31983', None),
            'RAMLIG': ('EPSG:31982', None),
        })
        with self.assertRaisesRegex(ValueError, 'CRS incompatíveis'):
            shared_crs(fiona, 'base.gdb', ['SSDMT', 'RAMLIG'])


if __name__ == '__main__':
    unittest.main()
