import os
import pandas as pd
import traceback
import networkx as nx
from typing import Callable, Optional

from core.data_repository import DataRepository
from core.legacy_logic import LegacyTopology
from core.electrical import ElectricalCalculator
from core.exporter import PowerFlowExporter


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
            if d.get("tipo_no")=="UCBT":
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
                G = LegacyTopology.attach_transformer_parameters(
                    G,
                    data["CTMT"].iloc[0]
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
