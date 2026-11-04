import networkx as nx
import pandas as pd
import numpy as np
from pyproj import CRS, Transformer
import re

class TopologyBuilder:
    def __init__(self, data_dict: dict):
        self.data = data_dict
        self.G = nx.Graph()
        
        try:
            # Configura conversão UTM -> Lat/Lon
            crs_in = CRS.from_epsg(31982) 
            crs_out = CRS.from_epsg(4326)
            self.transformer = Transformer.from_crs(crs_in, crs_out, always_xy=True)
        except:
            self.transformer = None

    def _get_coords(self, x, y):
        try:
            # Tenta converter string com vírgula para float
            sx = str(x).replace(',', '.')
            sy = str(y).replace(',', '.')
            fx, fy = float(sx), float(sy)
            
            # Se valores parecerem UTM (ex: > 180), converte
            if self.transformer and (abs(fx) > 180 or abs(fy) > 90):
                return self.transformer.transform(fx, fy)
            return fx, fy
        except: return None

    def build_mv_network(self, pac_ini=None) -> nx.Graph:
        # --- ESTRATÉGIA DE COORDENADAS REFORÇADA ---
        # O problema é: Rede pede 'ALIM-123', PONNOT tem '123'.
        # Vamos indexar o PONNOT de forma que '123' possa ser achado.
        
        coords = {}
        df_ponnot = self.data.get('PONNOT', pd.DataFrame())
        
        print(f"[Topology] Processando {len(df_ponnot)} registros de coordenadas...")
        
        if not df_ponnot.empty:
            for _, row in df_ponnot.iterrows():
                # ID Original do PONNOT (ex: 1421518233)
                raw_id = str(row['COD_ID']).strip().upper()
                xy = self._get_coords(row['X'], row['Y'])
                
                if xy:
                    # Guarda o ID exato
                    coords[raw_id] = xy
        
        if not coords:
            print("[Topology] ALERTA: Dicionário de coordenadas vazio!")

        # Constrói grafo MT
        for table_key in ['SSDMT', 'UNSEMT']:
            df = self.data.get(table_key, pd.DataFrame())
            if df.empty: continue
            
            for _, row in df.iterrows():
                # IDs da Rede (ex: 681717862-1421518233)
                u = str(row['PAC_1']).strip().upper()
                v = str(row['PAC_2']).strip().upper()
                
                attr = {
                    'id': str(row['COD_ID']),
                    'tipo': table_key,
                    'tensao': 'MT',
                    'fases': str(row.get('FAS_CON', 'ABC')),
                    'comprimento': float(row.get('COMP', 0.001))
                }
                if table_key == 'UNSEMT':
                    attr['estado'] = str(row.get('ESTADO', 'F'))
                
                self.G.add_edge(u, v, **attr)

        # Aplica coordenadas (MATCH INTELIGENTE)
        count = 0
        debug_miss = 0
        
        for n in self.G.nodes():
            found = False
            
            # 1. Tentativa Exata (O nó da rede é igual ao do PONNOT?)
            if n in coords:
                self.G.nodes[n]['x'], self.G.nodes[n]['y'] = coords[n]
                found = True
            else:
                # 2. Tentativa Sufixo: Rede 'ALIM-POSTE' -> busca 'POSTE' no coords
                # Divide por hífen, underline ou espaço
                parts = re.split(r'[-_ ]', n)
                
                # Se tiver partes, tenta casar a última parte (o ID do poste)
                if len(parts) > 1:
                    suffix_id = parts[-1] 
                    if suffix_id in coords:
                        self.G.nodes[n]['x'], self.G.nodes[n]['y'] = coords[suffix_id]
                        found = True
                    
                    # Tenta também o primeiro pedaço (caso raro)
                    elif parts[0] in coords:
                        self.G.nodes[n]['x'], self.G.nodes[n]['y'] = coords[parts[0]]
                        found = True

            if found:
                count += 1
            else:
                debug_miss += 1
                if debug_miss <= 3: # Amostra de erros
                    print(f"[Topology] Nó sem coordenada: {n} (Tentado sufixo: {parts[-1] if 'parts' in locals() else 'N/A'})")
            
            self.G.nodes[n]['tipo_no'] = 'MT_Node'

        print(f"[Topology] Resultado Final: {count} nós com coordenadas / {debug_miss} sem.")
        
        if pac_ini:
            pac_clean = str(pac_ini).strip().upper()
            if pac_clean in self.G.nodes:
                self.G.nodes[pac_clean]['tipo_no'] = 'Substation'
                self.G.nodes[pac_clean]['Vnom'] = 1.0

        return self.G

    def expand_lv_network(self, G: nx.Graph) -> nx.Graph:
        # 1. Trafos
        df_trafo = self.data.get('UNTRMT', pd.DataFrame())
        if not df_trafo.empty:
            for _, row in df_trafo.iterrows():
                u = str(row['PAC_1']).strip().upper()
                v = str(row['PAC_2']).strip().upper()
                if v in ['NAN', 'NONE', '', '0', 'nan']: v = f"TR_{row['COD_ID']}"
                
                attr = {
                    'id': row['COD_ID'], 'tipo': 'MT_BT_Transformer_Connection',
                    'Snom_kVA': float(row.get('POT_NOM', 45)), 'phases': str(row.get('FAS_CON', 'ABC'))
                }
                G.add_edge(u, v, **attr)
                G.nodes[v]['tipo_no'] = 'Transformer_Sec'
                
                # Herda coordenadas do primário
                if u in G.nodes and 'x' in G.nodes[u]:
                    G.nodes[v]['x'] = G.nodes[u]['x'] + 0.00005 
                    G.nodes[v]['y'] = G.nodes[u]['y'] - 0.00005 

        # 2. Rede BT
        df_bt = self.data.get('SSDBT', pd.DataFrame())
        if not df_bt.empty:
            for _, row in df_bt.iterrows():
                u = str(row['PAC_1']).strip().upper()
                v = str(row['PAC_2']).strip().upper()
                attr = {
                    'id': row['COD_ID'], 'tipo': 'SSDBT', 'tensao': 'BT',
                    'comprimento': float(row.get('COMP', 0.001)), 'fases': str(row.get('FAS_CON', 'ABC'))
                }
                G.add_edge(u, v, **attr)
                
                # Herança de coordenadas para BT
                # Tenta propagar de U para V ou de V para U
                if u in G.nodes and 'x' in G.nodes[u] and v in G.nodes and 'x' not in G.nodes[v]:
                     G.nodes[v]['x'] = G.nodes[u]['x'] + 0.00002
                     G.nodes[v]['y'] = G.nodes[u]['y'] + 0.00002
                elif v in G.nodes and 'x' in G.nodes[v] and u in G.nodes and 'x' not in G.nodes[u]:
                     G.nodes[u]['x'] = G.nodes[v]['x'] + 0.00002
                     G.nodes[u]['y'] = G.nodes[v]['y'] + 0.00002

        return G

    def add_consumers(self, G: nx.Graph):
        df_uc = self.data.get('UCBT', pd.DataFrame())
        df_ram = self.data.get('RAMLIG', pd.DataFrame())
        
        # Ramais
        if not df_ram.empty:
            for _, row in df_ram.iterrows():
                u = str(row['PAC_1']).strip().upper()
                v = str(row['PAC_2']).strip().upper()
                G.add_edge(u, v, tipo='RAMLIG', tensao='BT', comprimento=0.01)
        
        # UCs
        if not df_uc.empty:
            for _, row in df_uc.iterrows():
                pac = str(row['PAC']).strip().upper()
                if pac in G.nodes: G.nodes[pac]['tipo_no'] = 'UCBT'