import datetime
import os
import networkx as nx
import pandas as pd
import numpy as np


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