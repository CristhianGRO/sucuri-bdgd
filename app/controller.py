import os
import pandas as pd
import traceback
import networkx as nx
from typing import Callable, Optional

from core.data_repository import DataRepository
from core.legacy_logic import LegacyTopology
from core.electrical import ElectricalCalculator
from core.exporter import PowerFlowExporter

# Domínio TTEN do Dicionário de Dados ANEEL (valores em V). Algumas GDBs
# publicadas não carregam as tabelas de domínio; por isso o fluxo não pode
# depender da presença física da camada TTEN no arquivo da distribuidora.
TTEN_DDA_VOLTS = {
    '0': 0, '1': 110, '2': 115, '3': 120, '4': 121, '5': 125, '6': 127,
    '7': 208, '8': 216, '9': 216.5, '10': 220, '11': 230, '12': 231,
    '13': 240, '14': 254, '15': 380, '16': 400, '17': 440, '18': 480,
    '19': 500, '20': 600, '21': 750, '22': 1000, '23': 2200, '24': 3200,
    '25': 3600, '26': 3785, '27': 3800, '28': 3848, '29': 3985,
    '30': 4160, '31': 4200, '32': 4207, '33': 4368, '34': 4560,
    '35': 5000, '36': 6000, '37': 6600, '38': 6930, '39': 7960,
    '40': 8670, '41': 11400, '42': 11900, '43': 12000, '44': 12600,
    '45': 12700, '46': 13200, '47': 13337, '48': 13530, '49': 13800,
    '50': 13860, '51': 14140, '52': 14190, '53': 14400, '54': 14835,
    '55': 15000, '56': 15200, '57': 19053, '58': 19919, '59': 21000,
    '60': 21500, '61': 22000, '62': 23000, '63': 23100, '64': 23827,
    '65': 24000, '66': 24200, '67': 25000, '68': 25800, '69': 27000,
    '70': 30000, '71': 33000, '72': 34500, '73': 36000, '74': 38000,
    '75': 40000, '76': 44000, '77': 45000, '78': 45400, '79': 48000,
    '80': 60000, '81': 66000, '82': 69000, '83': 72500, '84': 88000,
    '85': 88200, '86': 92000, '87': 100000, '88': 120000, '89': 121000,
    '90': 123000, '91': 131600, '92': 131630, '93': 131635, '94': 138000,
    '95': 145000, '96': 230000, '97': 345000, '98': 500000, '99': 750000,
    '100': 1000000, '101': 245000, '102': 550000,
}


class Controller:

    def __init__(self, log_callback: Callable, plot_callback: Optional[Callable] = None):
        self.log = log_callback
        self.plot = plot_callback
        self.base_path = ""
        self.stop_flag = False

    # -----------------------------------------------------

    def stop(self):
        self.stop_flag = True

    def _check_islands(self, G):
        comps = list(nx.connected_components(G))

        if len(comps) == 1:
            self.log("Topologia conectada ✔")
            return

        self.log(f"⚠ {len(comps)} ilhas detectadas")

        for i,c in enumerate(comps[:5]):
            tipos = [G.nodes[n].get("tipo_no") for n in list(c)[:5]]
            self.log(f"ilha {i+1} size={len(c)} sample_types={tipos}")
    def _validate_supply_paths(self, G):

        subs = [n for n,d in G.nodes(data=True) if d.get("tipo_no")=="Substation"]
        if not subs:
            self.log("❌ nenhuma subestação")
            return

        root = subs[0]
        bad = 0

        for n,d in G.nodes(data=True):
            if d.get("ucbt_row"):
                if not nx.has_path(G, root, n):
                    bad += 1

        self.log(f"UCs sem caminho = {bad}")


    # -----------------------------------------------------
    # GRAPH CACHE
    # -----------------------------------------------------

    def _save_graph_csv(self, G, node_file, edge_file):

        if len(G.nodes) > 0:
            df_nodes = pd.DataFrame.from_dict(dict(G.nodes(data=True)), orient='index')
            df_nodes.index.name = 'node'
            df_nodes.reset_index(inplace=True)
            df_nodes.to_csv(node_file, index=False)

        if len(G.edges) > 0:
            df_edges = nx.to_pandas_edgelist(G)
            df_edges.to_csv(edge_file, index=False)

    def _load_graph_from_csv(self, node_file, edge_file):

        G = nx.Graph()

        df_nodes = pd.read_csv(node_file)
        for _, r in df_nodes.iterrows():
            n = str(r["node"])
            attrs = r.drop("node").dropna().to_dict()
            G.add_node(n, **attrs)

        df_edges = pd.read_csv(edge_file)
        for _, r in df_edges.iterrows():
            u = str(r["source"])
            v = str(r["target"])
            attrs = r.drop(["source", "target"]).dropna().to_dict()
            G.add_edge(u, v, **attrs)

        return G

    # -----------------------------------------------------
    # PAC INICIAL — CTMT.PAC_INI (REGRA DEFINITIVA)
    # -----------------------------------------------------

    def _select_ctmt(self, table, ctmt_id):
        if table.empty or "COD_ID" not in table.columns:
            raise ValueError("CTMT vazio ou sem COD_ID")
        selected = table[table["COD_ID"].astype(str).str.strip() == str(ctmt_id).strip()]
        if len(selected) != 1:
            raise ValueError(f"Esperada uma linha CTMT para {ctmt_id}; encontradas {len(selected)}")
        return selected

    def _get_pac_inicial_from_ctmt(self, df_ctmt, ctmt_id):
        row = self._select_ctmt(df_ctmt, ctmt_id).iloc[0]
        pac = row.get("PAC_INI")
        if pd.isna(pac) or not str(pac).strip():
            raise ValueError(f"PAC_INI ausente para {ctmt_id}")
        return str(pac).strip()

    @staticmethod
    def _nominal_voltage_kv(ctmt_row, df_tten):
        """Resolve CTMT.TEN_NOM (código TTEN) para a base LL em kV.

        Na BDGD, ``TEN_OPE`` é um valor em pu e não pode ser usado como base
        de impedância. Esta separação é essencial para o fluxo trifásico.
        """
        code = str(ctmt_row.get("TEN_NOM", "")).strip()
        try:
            code = str(int(float(code)))
        except (TypeError, ValueError):
            pass
        voltage_v = None
        if df_tten is not None and not df_tten.empty:
            id_column = next((c for c in df_tten.columns if c.upper() == "COD_ID"), None)
            voltage_column = next((c for c in df_tten.columns if c.upper() == "TEN"), None)
            if id_column and voltage_column:
                matched = df_tten[df_tten[id_column].astype(str).str.strip() == code]
                if len(matched) == 1:
                    try:
                        voltage_v = float(str(matched.iloc[0][voltage_column]).replace(',', '.'))
                    except (TypeError, ValueError):
                        voltage_v = None
        if voltage_v is None:
            voltage_v = TTEN_DDA_VOLTS.get(code)
        if voltage_v is None:
            raise ValueError(f"TTEN não contém uma tensão nominal para o código {code!r}")
        voltage_kv = voltage_v / 1000.0
        if not .1 <= voltage_kv <= 1000:
            raise ValueError(f"Tensão TTEN fora da faixa física: {voltage_v!r} V")
        return voltage_kv

    def _prune_to_substation_island(self, G):

        if G is None or G.number_of_nodes() == 0:
            self.log("Grafo vazio — nada para podar")
            return G

        subs = [n for n,d in G.nodes(data=True)
                if d.get("tipo_no") == "Substation"]

        if not subs:
            self.log("⚠ nenhuma subestação — poda ignorada")
            return G

        root = subs[0]

        comps = list(nx.connected_components(G))

        keep = None

        for c in comps:
            if root in c:
                keep = c
                break

        if keep is None:
            self.log("⚠ subestação não pertence a nenhuma componente")
            return G

        remove_nodes = set(G.nodes()) - set(keep)

        if remove_nodes:
            self.log(f"Removendo {len(remove_nodes)} nós de ilhas desconectadas")
            G.remove_nodes_from(remove_nodes)

        self.log(
            f"Grafo após poda: {G.number_of_nodes()} nós / {G.number_of_edges()} arestas"
        )

        return G

    # -----------------------------------------------------
    # MAIN PIPELINE
    # -----------------------------------------------------

    def run_feeder_process(self,
                           rede: str,
                           ctmt_id: str,
                           cidade_nome: str,
                           force_rebuild: bool,
                           mode: str,
                           output_base=None,
                           strict=False):

        if not self.base_path:
            self.log("Erro: base_path não definido")
            return

        if cidade_nome:
            folder = f"{rede}_{cidade_nome}_{ctmt_id}"
        else:
            folder = ctmt_id

        output_dir = os.path.join(output_base or self.base_path, rede, "Selecionados", folder)
        os.makedirs(output_dir, exist_ok=True)

        suffix = "_EQ" if mode == "Equivalente MT" else ""

        node_file = os.path.join(output_dir, f"G_nodes_CTMT_{ctmt_id}{suffix}.csv")
        edge_file = os.path.join(output_dir, f"G_edges_CTMT_{ctmt_id}{suffix}.csv")

        G = None

        # -------------------------------------------------
        # LOAD CACHE
        # -------------------------------------------------

        if not force_rebuild and os.path.exists(node_file) and os.path.exists(edge_file):

            try:
                self.log(f"[{ctmt_id}] Carregando grafo do cache")
                G = self._load_graph_from_csv(node_file, edge_file)

                if self.plot:
                    self.plot(G, f"{ctmt_id} ({mode})")

                self.log(f"Grafo carregado: {G.number_of_nodes()} nós")

            except Exception as e:
                self.log(f"Falha cache → rebuild: {e}")
                G = None

        # -------------------------------------------------
        # BUILD FROM BDGD
        # -------------------------------------------------

        if G is None:

            try:

                self.log(f"[{ctmt_id}] Carregando BDGD")

                repo = DataRepository(self.base_path)
                data = repo.load_feeder_data(rede, ctmt_id)
                data["CTMT"] = self._select_ctmt(data["CTMT"], ctmt_id)

                # self.log("=== DEBUG KEY SNAPSHOT ===")

                # def _sample(series, n=5):
                #     return list(series.dropna().astype(str).head(n))

                # if not data["SSDMT"].empty:
                #     self.log(f"SSDMT PAC_1 sample = {_sample(data['SSDMT']['PAC_1'])}")

                # if not data["UNTRMT"].empty:
                #     self.log(f"UNTRMT PAC_2 sample = {_sample(data['UNTRMT']['PAC_2'])}")

                # if not data["UCBT"].empty:
                #     self.log(f"UCBT PAC sample = {_sample(data['UCBT']['PAC'])}")

                # if not data["PONNOT"].empty:
                #     self.log(f"PONNOT COD_ID sample = {_sample(data['PONNOT']['COD_ID'])}")

                # self.log("=== END DEBUG KEY SNAPSHOT ===")


                if data["SSDMT"].empty:
                    raise ValueError("SSDMT vazio para o alimentador selecionado")

                # -----------------------------------------
                # PAC INICIAL — CTMT.PAC_INI
                # -----------------------------------------

                self.log("Determinando PAC inicial via CTMT")

                pac_ini = self._get_pac_inicial_from_ctmt(
                    data["CTMT"],
                    ctmt_id
                )

                self.log(f"PAC inicial (CTMT.PAC_INI) = {pac_ini}")

                # -----------------------------------------
                # GRAFO MT — LEGACY
                # -----------------------------------------

                self.log("Construindo grafo MT (Legacy)")

                G = LegacyTopology.create_MV_network(
                    pac_ini,
                    data["SSDMT"],
                    data["UNSEMT"],
                    data["PONNOT"]
                )

                if G is None or G.number_of_nodes() == 0:
                    raise RuntimeError("create_MV_network retornou grafo vazio")

                # -----------------------------------------
                # EXPANSÃO BT — LEGACY COMPLETA
                # -----------------------------------------

                G = LegacyTopology.expand_lv_network(
                    G,
                    data["SSDBT"],
                    data["UNTRMT"],
                    data["UCBT"],
                    data["RAMLIG"],
                    data["PONNOT"]
                )

                # -----------------------------------------
                # MV TRANSFORMERS
                # -----------------------------------------
                ctmt_row = data["CTMT"].iloc[0]
                voltage_base_kv = self._nominal_voltage_kv(ctmt_row, data.get("TTEN"))
                voltage_setpoint_pu = float(str(ctmt_row.get("TEN_OPE", 1.0)).replace(',', '.'))
                if not .8 <= voltage_setpoint_pu <= 1.2:
                    raise ValueError(f"CTMT.TEN_OPE fora da faixa esperada em pu: {voltage_setpoint_pu}")
                G.nodes[pac_ini]["voltage_base_kv"] = voltage_base_kv
                G.nodes[pac_ini]["voltage_setpoint_pu"] = voltage_setpoint_pu
                self.log(f"Base do fluxo: {voltage_base_kv:.3f} kV; setpoint da subestação: {voltage_setpoint_pu:.4f} pu")
                G = LegacyTopology.attach_transformer_parameters(
                    G,
                    ctmt_row,
                    voltage_base_kv,
                )

                self._check_islands(G)

                G = self._prune_to_substation_island(G)

                self._validate_supply_paths(G)

                                

                # -----------------------------------------
                # IMPEDÂNCIAS — LEGACY
                # -----------------------------------------

                G = LegacyTopology.calculate_line_impedances(
                    G,
                    data["SSDMT"],
                    data["SSDBT"],
                    data["SEGCON"]
                )

                # -----------------------------------------
                # CARGAS — ELÉTRICO (SEM ALTERAÇÃO)
                # -----------------------------------------

                self.log("Calculando cargas")

                ec = ElectricalCalculator(self.log)

                G = ec.calculate_loads(
                    G,
                    rede,
                    ctmt_id,
                    data["UCBT"],
                    self.base_path
                )

                # -----------------------------------------
                # CACHE SAVE
                # -----------------------------------------

                self._save_graph_csv(G, node_file, edge_file)

                if self.plot and G.number_of_nodes() > 50000:
                    self.log("Grafo muito grande — plot simplificado")
                    self.plot(None, "Graph too large")
                elif self.plot:
                    self.plot(G, f"{ctmt_id} ({mode})")


            except Exception as e:
                self.log("Erro na construção:")
                self.log(str(e))
                self.log(traceback.format_exc())
                if strict:
                    raise
                return

        # -------------------------------------------------
        # EXPORT POWER FLOW
        # -------------------------------------------------

        try:

            self.log("Exportando arquivos fluxo de potência")

            exporter = PowerFlowExporter(output_base or self.base_path)

            out = exporter.export_all(
                G,
                rede,
                ctmt_id,
                cidade_nome
            )

            self.log(f"Exportação concluída → {out}")
            return {"graph": G, "output": out}

        except Exception as e:
            self.log("Erro export:")
            self.log(str(e))
            self.log(traceback.format_exc())
            if strict:
                raise
