from unittest import TestCase
import json
import networkx as nx
import pandas as pd
from pathlib import Path
import tempfile
from core.legacy_logic import LegacyTopology
from web_backend.worker import append_consumer_visuals, graph_geojson

class ConsumerAttributes(TestCase):
    def test_topology_keeps_every_consumer_connected_to_the_same_bus(self):
        graph=nx.Graph();graph.add_node('PAC_BT')
        consumers=pd.DataFrame([
            {'PAC':'PAC_BT','COD_ID':'UC-1','CLAS_SUB':'RE1'},
            {'PAC':'PAC_BT','COD_ID':'UC-2','CLAS_SUB':'CO1'},
        ])
        LegacyTopology.expand_lv_network(graph,pd.DataFrame(),pd.DataFrame(),consumers,pd.DataFrame(),pd.DataFrame())
        self.assertEqual(len(graph.nodes['PAC_BT']['ucbt_rows']),2)
        self.assertEqual(graph.nodes['PAC_BT']['ucbt_row']['COD_ID'],'UC-1')
        self.assertTrue(graph.nodes['PAC_BT']['has_ucbt'])
        self.assertNotEqual(graph.nodes['PAC_BT'].get('tipo_no'), 'UCBT')

    def test_class_is_preserved_without_dumping_original_consumer_record(self):
        graph=nx.Graph();graph.add_node('N1',tipo_no='UCBT',x=-51,y=-30,ucbt_row={'CLAS_SUB':'CO1','FAS_CON':'AB','CEP':'private','TIP_CC':'COM'})
        geo,missing=graph_geojson(graph,'F1','EPSG:4326')
        props=geo['features'][0]['properties']
        self.assertEqual(props['CLAS_SUB'],'CO1')
        self.assertEqual(props['FAS_CON'],'AB')
        self.assertNotIn('ucbt_row',props)
        self.assertNotIn('CEP',props)
        self.assertEqual(missing,0)

    def test_multiple_consumers_are_grouped_at_the_bus_and_transformer(self):
        graph=nx.Graph()
        graph.add_node('MT',tipo_no='PAC_MV',x=-51,y=-30)
        graph.add_node('TR',tipo_no='Transformer_Sec',x=-51.001,y=-30.001)
        graph.add_node('PAC_BT',tipo_no='UCBT',x=-51.002,y=-30.002,ucbt_rows=[
            {'COD_ID':'UC-1','CLAS_SUB':'RE1'},
            {'COD_ID':'UC-2','CLAS_SUB':'CO1'},
        ])
        graph.add_edge('MT','TR',tipo='MT_BT_Transformer_Connection')
        graph.add_edge('TR','PAC_BT',tipo='SSDBT')
        geo,_=graph_geojson(graph,'F1','EPSG:4326')
        features={feature['properties']['COD_ID']:feature['properties'] for feature in geo['features'] if feature['geometry']['type']=='Point'}
        self.assertEqual(features['PAC_BT']['consumer_count'],2)
        self.assertEqual(features['PAC_BT']['consumer_classes'],{'RE1':1,'CO1':1})
        self.assertEqual(features['TR']['consumer_summary']['consumer_count'],2)

    def test_original_geometries_receive_transformer_summary_and_bus_anchor(self):
        graph=nx.Graph()
        graph.add_node('MT',tipo_no='PAC_MV',x=-51,y=-30)
        graph.add_node('TR',tipo_no='Transformer_Sec',x=-51.001,y=-30.001)
        graph.add_node('PAC_BT',tipo_no='UCBT',x=-51.002,y=-30.002,ucbt_rows=[{'COD_ID':'UC-1','CLAS_SUB':'RE1'}])
        graph.add_edge('MT','TR',tipo='MT_BT_Transformer_Connection')
        graph.add_edge('TR','PAC_BT',tipo='RAMLIG')
        with tempfile.TemporaryDirectory() as root:
            output=Path(root)/'network.geojson'
            output.write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','properties':{'tipo':'UNTRMT','PAC_2':'TR'},'geometry':{'type':'Point','coordinates':[-51.001,-30.001]}}]}),encoding='utf-8')
            append_consumer_visuals(output,graph,'F1','EPSG:4326')
            features=json.loads(output.read_text(encoding='utf-8'))['features']
        self.assertEqual(features[0]['properties']['consumer_summary']['consumer_count'],1)
        anchors=[feature for feature in features if feature['properties'].get('tipo')=='ConsumerAnchor']
        self.assertEqual(len(anchors),1)
        self.assertEqual(anchors[0]['properties']['PAC'],'PAC_BT')

    def test_consumer_without_coordinates_is_anchored_near_connected_bus(self):
        graph=nx.Graph()
        graph.add_node('BAR',tipo_no='PAC_LV',x=-51,y=-30)
        graph.add_node('PAC_BT',tipo_no='UCBT',ucbt_rows=[{'COD_ID':'UC-1','CLAS_SUB':'RE1'}])
        graph.add_edge('BAR','PAC_BT',tipo='SSDBT')
        geo,missing=graph_geojson(graph,'F1','EPSG:4326')
        anchors=[feature for feature in geo['features'] if feature['properties'].get('tipo')=='ConsumerAnchor']
        self.assertEqual(missing,1)
        self.assertEqual(len(anchors),1)
        self.assertTrue(anchors[0]['properties']['position_estimated'])
        self.assertEqual(anchors[0]['properties']['anchor_pac'],'BAR')
        self.assertNotEqual(anchors[0]['geometry']['coordinates'],[-51,-30])

    def test_original_geometry_keeps_calculated_substation_and_low_voltage_nodes(self):
        graph=nx.Graph()
        graph.add_node('SE',tipo_no='Substation',x=-51,y=-30)
        graph.add_node('BT',tipo_no='PAC_LV',x=-51.001,y=-30.001)
        graph.add_edge('SE','BT',tipo='SSDBT')
        with tempfile.TemporaryDirectory() as root:
            output=Path(root)/'network.geojson'
            output.write_text(json.dumps({'type':'FeatureCollection','features':[]}),encoding='utf-8')
            append_consumer_visuals(output,graph,'F1','EPSG:4326')
            features=json.loads(output.read_text(encoding='utf-8'))['features']
        nodes={feature['properties']['COD_ID']:feature['properties'] for feature in features}
        self.assertEqual(nodes['SE']['tipo_no'],'Substation')
        self.assertEqual(nodes['BT']['tipo_no'],'PAC_LV')
