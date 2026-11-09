from unittest import TestCase

from web_backend.worker import standard_layer_name


class LayerNameTests(TestCase):
    def test_normalizes_cpfl_consumer_table_suffix(self):
        self.assertEqual(standard_layer_name('UCBT_tab'), 'UCBT')
        self.assertEqual(standard_layer_name('UCMT_tab'), 'UCMT')

    def test_preserves_regular_and_qualified_layer_names(self):
        self.assertEqual(standard_layer_name('RAMLIG'), 'RAMLIG')
        self.assertEqual(standard_layer_name('BDGD.SSDBT'), 'SSDBT')
