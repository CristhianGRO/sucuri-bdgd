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

    def test_consumer_indicators_aggregate_energy_quality_and_profile(self):
        graph=nx.Graph();graph.add_node('N1',tipo_no='PAC_LV',x=-51,y=-30,ucbt_rows=[
            {'COD_ID':'UC-1','CLAS_SUB':'RE1','TIP_CC':'RES_A','CAR_INST':'4.5','ENE_01':'10','ENE_02':'20','DIC_01':'1.5','FIC_01':'2'},
            {'COD_ID':'UC-2','CLAS_SUB':'RE1','TIP_CC':'RES_A','CAR_INST':'2','ENE_01':'15','ENE_02':'5','DIC_01':'2.5','FIC_01':'4'},
        ])
        profiles={'RES_A':[{'day':'DU','points':[1,2] + [0] * 94}]}
        geo,_=graph_geojson(graph,'F1','EPSG:4326',profiles)
        props=geo['features'][0]['properties']
        self.assertEqual(props['installed_load_kw'],6.5)
        self.assertEqual(props['energy_monthly_kwh'][:2],[25,25])
        self.assertEqual(props['energy_annual_kwh'],50)
        self.assertEqual(props['dic_monthly_mean'],2)
        self.assertEqual(props['fic_monthly_mean'],3)
        self.assertEqual(props['typical_profiles'][0]['day'],'DU')
        self.assertEqual(props['typical_profiles'][0]['points'][:2],[50,100])
        individual=props['consumers'][0]
        self.assertEqual(individual['installed_load_kw'],4.5)
        self.assertEqual(individual['energy_monthly_kwh'][:2],[10,20])
        self.assertEqual(individual['dic_monthly_mean'],1.5)
        self.assertEqual(individual['typical_profiles'][0]['points'][:2],[50,100])

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

    def test_original_line_receives_powerflow_metrics_by_cod_id(self):
        graph=nx.Graph()
        graph.add_node('A',tipo_no='PAC_MV',x=-51,y=-30)
        graph.add_node('B',tipo_no='PAC_MV',x=-51.001,y=-30.001)
        graph.add_edge('A','B',tipo='MV_Line',COD_ID='LINE_1',pf_p_kw=10,pf_q_kvar=3,pf_current_a=1,pf_losses_kw=.1,pf_losses_kvar=.05)
        with tempfile.TemporaryDirectory() as root:
            output=Path(root)/'network.geojson'
            output.write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','properties':{'tipo':'SSDMT','COD_ID':'LINE_1'},'geometry':{'type':'LineString','coordinates':[[-51,-30],[-51.001,-30.001]]}}]}),encoding='utf-8')
            append_consumer_visuals(output,graph,'F1','EPSG:4326')
            props=json.loads(output.read_text(encoding='utf-8'))['features'][0]['properties']
        self.assertEqual(props['pf_p_kw'],'10')
