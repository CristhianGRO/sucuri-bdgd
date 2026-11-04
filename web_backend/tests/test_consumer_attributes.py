from unittest import TestCase
import networkx as nx
from web_backend.worker import graph_geojson

class ConsumerAttributes(TestCase):
    def test_class_is_preserved_without_dumping_original_consumer_record(self):
        graph=nx.Graph();graph.add_node('N1',tipo_no='UCBT',x=-51,y=-30,ucbt_row={'CLAS_SUB':'CO1','FAS_CON':'AB','CEP':'private','TIP_CC':'COM'})
        geo,missing=graph_geojson(graph,'F1','EPSG:4326')
        props=geo['features'][0]['properties']
        self.assertEqual(props['CLAS_SUB'],'CO1')
        self.assertEqual(props['FAS_CON'],'AB')
        self.assertNotIn('ucbt_row',props)
        self.assertNotIn('CEP',props)
        self.assertEqual(missing,0)
