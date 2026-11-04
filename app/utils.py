import datetime
import os
import networkx as nx
import pandas as pd
import numpy as np


class Logger:

    @staticmethod
    def info(msg):
        print(f"[INFO] {datetime.datetime.now().strftime('%H:%M:%S')} - {msg}")


def fases_to_mask(f):

    if f is None:
        return "111"

    f = str(f).upper().strip()
    # print("fases_to_mask:", f)
    if f in ("A", "100"): return "100"
    if f in ("B", "010"): return "010"
    if f in ("C", "001"): return "001"
    if f in ("AB", "110"): return "110"
    if f in ("BC", "011"): return "011"
    if f in ("AC", "101"): return "101"
    if f in ("ABC", "111"): return "111"

    return "111"

def _mask_to_fases(mask):
    s = ""
    if mask[0]: s += "A"
    if mask[1]: s += "B"
    if mask[2]: s += "C"
    return s if s else None


def export_node_database(G, output_path):

    # ------------------------------------------------------
    # nó slack
    # ------------------------------------------------------
    slack = next(
        n for n, d in G.nodes(data=True)
        if d.get("tipo_no") == "Substation"
    )

    # árvore radial
    T = nx.bfs_tree(G, slack)

    # ------------------------------------------------------
    # acumuladores
    # ------------------------------------------------------
    Zmt = {}
    Zbt = {}

    zero = np.zeros(3, dtype=complex)

    Zmt[slack] = zero.copy()
    Zbt[slack] = zero.copy()

    # ------------------------------------------------------
    # propagação
    # ------------------------------------------------------
    for parent, child in nx.bfs_edges(T, slack):

        edge = G[parent][child]

        tipo = edge.get("tipo", "")

        Zabc = edge.get("Zabc")

        if Zabc is None:
            Zabc = np.zeros((3, 3), dtype=complex)

        # somente termos próprios
        Zphase = np.array([
            Zabc[0, 0],
            Zabc[1, 1],
            Zabc[2, 2]
        ])

        Zmt_parent = Zmt[parent].copy()
        Zbt_parent = Zbt[parent].copy()

        # ---------------- MT ----------------

        if tipo in ("MV_Line", "MV_Switch", "UNSEMT"):

            Zmt[child] = Zmt_parent + Zphase
            Zbt[child] = Zbt_parent

        # ---------------- transformador ----------------

        elif tipo == "MT_BT_Transformer_Connection":

            # a impedância MT termina no trafo
            Zmt[child] = Zmt_parent
            Zbt[child] = zero.copy()

        # ---------------- BT ----------------

        elif tipo in ("SSDBT", "RAMLIG"):

            Zmt[child] = Zmt_parent
            Zbt[child] = Zbt_parent + Zphase

        else:

            Zmt[child] = Zmt_parent
            Zbt[child] = Zbt_parent

    # ------------------------------------------------------
    # dataframe
    # ------------------------------------------------------
    rows = []

    for n, d in G.nodes(data=True):

        x = d.get("x", np.nan)
        y = d.get("y", np.nan)

        tipo_no = d.get("tipo_no", "")

        nivel = "BT"
        if tipo_no in ("Substation", "PAC_MV"):
            nivel = "MT"

        zmt = Zmt.get(n, zero)
        zbt = Zbt.get(n, zero)
        ztot = zmt + zbt

        rows.append({

            "BUS_ID": n,
            "TIPO_NO": tipo_no,
            "NIVEL": nivel,
            "X": x,
            "Y": y,

            "R_MT_A": zmt[0].real,
            "X_MT_A": zmt[0].imag,
            "R_MT_B": zmt[1].real,
            "X_MT_B": zmt[1].imag,
            "R_MT_C": zmt[2].real,
            "X_MT_C": zmt[2].imag,

            "R_BT_A": zbt[0].real,
            "X_BT_A": zbt[0].imag,
            "R_BT_B": zbt[1].real,
            "X_BT_B": zbt[1].imag,
            "R_BT_C": zbt[2].real,
            "X_BT_C": zbt[2].imag,

            "R_TOTAL_A": ztot[0].real,
            "X_TOTAL_A": ztot[0].imag,
            "R_TOTAL_B": ztot[1].real,
            "X_TOTAL_B": ztot[1].imag,
            "R_TOTAL_C": ztot[2].real,
            "X_TOTAL_C": ztot[2].imag
        })

    df = pd.DataFrame(rows)

    df.to_csv(output_path, index=False)

    print(f"Node database salva em:\n{output_path}")

    return df