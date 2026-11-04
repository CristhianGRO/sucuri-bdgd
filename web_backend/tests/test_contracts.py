import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import pandas as pd
import networkx as nx
from app.controller import Controller
from web_backend.worker import safe_child, extract_archive, graph_geojson

class IntegrationContracts(unittest.TestCase):
    def test_ctmt_exact_id_and_no_fallback(self):
        c=Controller(lambda _:None)
        rows=pd.DataFrame([{'COD_ID':'A','NOME':'nameA','PAC_INI':'rootA'}, {'COD_ID':'B','NOME':'nameB','PAC_INI':'rootB'}])
        self.assertEqual(c._get_pac_inicial_from_ctmt(rows,'B'),'rootB')
        with self.assertRaises(ValueError):c._get_pac_inicial_from_ctmt(rows,'missing')
        with self.assertRaises(ValueError):c._select_ctmt(pd.concat([rows,rows]),'A')
    def test_output_paths_cannot_escape_base(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ['..','../elsewhere','x/y','C:\\outside','']:
                with self.assertRaises(ValueError):safe_child(directory,value)
            self.assertEqual(safe_child(directory,'CTMT_01').parent,Path(directory).resolve())
    def test_archive_rejects_traversal_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'test.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape','unsafe')
            with self.assertRaises(ValueError):extract_archive(archive,Path(directory)/'out',100)
            self.assertFalse((Path(directory)/'escape').exists())
            with zipfile.ZipFile(archive,'w') as z:z.writestr('safe','123456')
            with self.assertRaises(ValueError):extract_archive(archive,Path(directory)/'out',2)
    def test_geojson_missing_coordinates_are_counted(self):
        graph=nx.Graph();graph.add_node('a',x=-51,y=-30);graph.add_node('b',x=-51.01,y=-30.01);graph.add_node('c')
        graph.add_edge('a','b',id='line');graph.add_edge('b','c')
        result,missing=graph_geojson(graph,'FEEDER','EPSG:4326')
        self.assertEqual(missing,1);self.assertEqual(len(result['features']),3)
        self.assertTrue(all(f['properties']['CTMT']=='FEEDER' for f in result['features']))
        self.assertIn('Ligação reta',result['features'][-1]['properties']['geometria'])

if __name__=='__main__':unittest.main()
