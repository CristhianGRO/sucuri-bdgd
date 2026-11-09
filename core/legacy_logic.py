import pandas as pd
import numpy as np
import networkx as nx
from collections import deque
from scipy.optimize import minimize_scalar
from app.utils import fases_to_mask, _mask_to_fases

class LegacyTopology:

    # ---------------------------------------------------------
    # helpers
    # ---------------------------------------------------------

    @staticmethod
    def _clean(x):
        if x is None:
            return None
        return str(x).strip().upper()

    # ---------------------------------------------------------
    # MT NETWORK — robusto (legado real)
    # ---------------------------------------------------------

    @staticmethod
    def create_MV_network(PAC_inicial, df_SSDMT, df_UNSEMT, df_PONNOT):

        G = nx.Graph()
        clean = LegacyTopology._clean

        # --- limpeza PAC ---
        for df in [df_SSDMT, df_UNSEMT]:
            for c in ["PAC_1", "PAC_2"]:
                if c not in df.columns:
                    if not df.empty:
                        raise ValueError(f"Tabela de conexões MT sem a coluna {c}")
                    df[c] = pd.Series(dtype=str)
                df[c+"_C"] = df[c].map(clean)

        if not df_PONNOT.empty:
            df_PONNOT["COD_ID_C"] = df_PONNOT["COD_ID"].map(clean)
            pon_xy = df_PONNOT.set_index("COD_ID_C")[["X","Y"]].to_dict("index")
        else:
            pon_xy = {}

        def coord_from_pac(pac):

            pac = clean(pac)

            rows = df_SSDMT[
                (df_SSDMT["PAC_1_C"] == pac) |
                (df_SSDMT["PAC_2_C"] == pac)
            ]

            for _, r in rows.iterrows():
                for pn in [r.get("PN_CON_1"), r.get("PN_CON_2")]:
                    pn = clean(pn)
                    if pn in pon_xy:
                        return pon_xy[pn]

            rows = df_UNSEMT[
                (df_UNSEMT["PAC_1_C"] == pac) |
                (df_UNSEMT["PAC_2_C"] == pac)
            ]

            for _, r in rows.iterrows():
                if "X" in r and "Y" in r:
                    return {"X": r["X"], "Y": r["Y"]}

            return None

        PAC0 = clean(PAC_inicial)

        G.add_node(PAC0, tipo_no="Substation")

        c0 = coord_from_pac(PAC0)
        if c0:
            G.nodes[PAC0]["x"] = c0["X"]
            G.nodes[PAC0]["y"] = c0["Y"]

        fila = deque([PAC0])
        visit = {PAC0}

        while fila:

            pac = fila.popleft()

            conns = df_SSDMT[
                (df_SSDMT["PAC_1_C"] == pac) |
                (df_SSDMT["PAC_2_C"] == pac)
            ]

            sws = df_UNSEMT[
                (df_UNSEMT["PAC_1_C"] == pac) |
                (df_UNSEMT["PAC_2_C"] == pac)
            ]

            # --- linhas MT ---
            for _, r in conns.iterrows():

                p1 = r["PAC_1_C"]
                p2 = r["PAC_2_C"]
                other = p2 if p1 == pac else p1

                if not G.has_node(other):
                    G.add_node(other, tipo_no="PAC_MV")
                    c = coord_from_pac(other)
                    if c:
                        G.nodes[other]["x"] = c["X"]
                        G.nodes[other]["y"] = c["Y"]

                if not G.has_edge(pac, other):

                    # -------------------------------
                    # FASES — coerência ramo ↔ barras
                    # -------------------------------

                    fases_line = r.get("FAS_CON")

                    def fases_to_mask_local(f):
                        if not f:
                            return [0,0,0]
                        f = str(f).upper()
                        return [
                            int("A" in f),
                            int("B" in f),
                            int("C" in f),
                        ]

                    mask_line = fases_to_mask_local(fases_line)

                    mask_bus_a = fases_to_mask_local(G.nodes[pac].get("fases"))
                    mask_bus_b = fases_to_mask_local(G.nodes[other].get("fases"))

                    mask_final = [
                        int(mask_line[i] or mask_bus_a[i] or mask_bus_b[i])
                        for i in range(3)
                    ]

                    fases_final = _mask_to_fases(mask_final)

                    G.add_edge(
                        pac, other,
                        tipo="MV_Line",
                        COD_ID=r.get("COD_ID"),
                        fases="ABC", #TODO: FIX IT FOR TWO-PHASE AND SINGLE-PHASE LINES
                        comprimento=r.get("COMP")
                    )



                if other not in visit:
                    visit.add(other)
                    fila.append(other)

            # --- chaves ---
            for _, r in sws.iterrows():

                p1 = r["PAC_1_C"]
                p2 = r["PAC_2_C"]
                other = p2 if p1 == pac else p1

                if not G.has_node(other):
                    G.add_node(other, tipo_no="PAC_MV")

                if not G.has_edge(pac, other):
                    G.add_edge(pac, other, tipo="MV_Switch")

                if other not in visit:
                    visit.add(other)
                    fila.append(other)

        return G

    # ---------------------------------------------------------
    # LV + TRAFO + RAMLIG + UCBT
    # ---------------------------------------------------------

    @staticmethod
    def expand_lv_network(G, df_SSDBT, df_UNTRMT, df_UCBT, df_RAMLIG, df_PONNOT):

        clean = LegacyTopology._clean

        # -------------------------------------------------
        # índice legado PN_CON → coordenadas (PONNOT)
        # -------------------------------------------------

        if not df_PONNOT.empty:
            df_PONNOT["COD_ID_C"] = df_PONNOT["COD_ID"].map(clean)
            pon_map = df_PONNOT.set_index("COD_ID_C")[["X","Y"]].to_dict("index")
        else:
            pon_map = {}

        # -------------------------------------------------
        # TRAFOS — legado usa X,Y direto do UNTRMT
        # -------------------------------------------------

        for _, tr in df_UNTRMT.iterrows():

            pac_mt = clean(tr["PAC_1"])
            pac_bt = clean(tr["PAC_2"])

            if pac_mt not in G:
                continue

            if not G.has_node(pac_bt):
                G.add_node(pac_bt, tipo_no="Transformer_Sec")

            G.add_edge(
                pac_mt,
                pac_bt,
                tipo="MT_BT_Transformer_Connection",
                COD_ID=tr.get("COD_ID"),
                # fases=tr.get("FAS_CON_S"),
                fases="ABC",
                trafo_row=tr.to_dict()
            )

            # ✅ coordenada trafo — igual legado
            if "X" in tr and "Y" in tr:
                try:
                    G.nodes[pac_bt]["x"] = float(tr["X"])
                    G.nodes[pac_bt]["y"] = float(tr["Y"])
                except:
                    pass

        # -------------------------------------------------
        # BT — coordenada via PN_CON → PONNOT (legado)
        # -------------------------------------------------

        if not df_SSDBT.empty:

            df_SSDBT["PAC_1_C"] = df_SSDBT["PAC_1"].map(clean)
            df_SSDBT["PAC_2_C"] = df_SSDBT["PAC_2"].map(clean)

            for _, r in df_SSDBT.iterrows():

                u = r["PAC_1_C"]
                v = r["PAC_2_C"]

                for n in (u, v):
                    if not G.has_node(n):
                        G.add_node(n, tipo_no="PAC_LV")

                if not G.has_edge(u, v):
                    G.add_edge(
                        u,
                        v,
                        tipo="SSDBT",
                        COD_ID=r.get("COD_ID"),
                        # fases=r.get("FAS_CON"),
                        fases="ABC",
                        comprimento=r.get("COMP")
                    )

                # ✅ coordenadas BT — legado via PN_CON
                pn1 = clean(r.get("PN_CON_1"))
                pn2 = clean(r.get("PN_CON_2"))

                if pn1 in pon_map:
                    G.nodes[u]["x"] = pon_map[pn1]["X"]
                    G.nodes[u]["y"] = pon_map[pn1]["Y"]

                if pn2 in pon_map:
                    G.nodes[v]["x"] = pon_map[pn2]["X"]
                    G.nodes[v]["y"] = pon_map[pn2]["Y"]

        # -------------------------------------------------
        # RAMLIG — legado cria aresta explícita
        # -------------------------------------------------

        if not df_RAMLIG.empty:

            for _, r in df_RAMLIG.iterrows():

                u = clean(r["PAC_1"])
                v = clean(r["PAC_2"])

                for n in (u, v):
                    if not G.has_node(n):
                        G.add_node(n, tipo_no="PAC_RAMLIG")

                if not G.has_edge(u, v):
                    G.add_edge(
                        u,
                        v,
                        tipo="RAMLIG",
                        COD_ID=r.get("COD_ID")
                    )

        # -------------------------------------------------
        # UCBT — attach igual legado
        # -------------------------------------------------

        if not df_UCBT.empty and "PAC" in df_UCBT.columns:

            df_UCBT["PAC_C"] = df_UCBT["PAC"].map(clean)
            node_map = {clean(n): n for n in G.nodes()}

            for _, r in df_UCBT.iterrows():

                pac = r["PAC_C"]

                if pac in node_map:
                    n = node_map[pac]
                    node = G.nodes[n]
                    # Uma barra pode atender várias unidades consumidoras. O
                    # campo singular é mantido para compatibilidade elétrica,
                    # enquanto a lista preserva a associação completa para o
                    # mapa e para agregações por transformador.
                    consumer = r.to_dict()
                    # A UC é uma carga *ligada à barra*, não um novo tipo de
                    # barra. Preservar PAC_LV/PAC_RAMLIG (ou outro tipo físico)
                    # permite que o mapa continue desenhando o nó da rede BT.
                    # A presença de ``ucbt_rows`` identifica a carga para os
                    # cálculos e para a visualização dos consumidores.
                    node["has_ucbt"] = True
                    node.setdefault("ucbt_rows", []).append(consumer)
                    node.setdefault("ucbt_row", consumer)

        return G

    # ---------------------------------------------------------
    # TRAFO PARAMS
    # ---------------------------------------------------------

    @staticmethod
    def attach_transformer_parameters(G, ctmt_row):

        import numpy as np

        if G is None:
            raise RuntimeError("attach_transformer_parameters recebeu G=None")

        ten_ope = float(ctmt_row["TEN_OPE"])

        for u, v, d in G.edges(data=True):

            if d.get("tipo") != "MT_BT_Transformer_Connection":
                continue

            tr = d.get("trafo_row")
            if not tr:
                continue

            Snom = float(tr.get("POT_NOM", 45))
            Vsec = float(tr.get("TEN_LIN_SE", 0.22))
            Vprim = ten_ope

            perdas_tot = float(tr.get("PER_TOT", 0))
            perdas_fer = float(tr.get("PER_FER", 0))
            Pcobre = max(perdas_tot - perdas_fer, 0)

            S = Snom * 1000.0
            V = Vsec * 1000.0

            I = S / (np.sqrt(3)*V + 1e-9)

            R = Pcobre / (3*I**2 + 1e-9)
            Rpu = (R*S)/(V**2 + 1e-9)

            # fallback típico BDGD quando Z% não disponível
            Xpu = 0.04

            d["trafo_params"] = {
                "Snom": Snom,
                "Rpu": Rpu,
                "Xpu": Xpu,
                "Vprim": Vprim,
                "Vsec": Vsec
            }

        return G


    # ---------------------------------------------------------
    # IMPEDÂNCIA DE LINHA (modelo legado simplificado robusto)
    # ---------------------------------------------------------
    @staticmethod
    def calculate_line_impedances(G, df_SSDMT, df_SSDBT, df_SEGCON):

        import numpy as np
        from scipy.optimize import minimize_scalar

        clean = LegacyTopology._clean

        if df_SSDMT.empty or df_SEGCON.empty:
            return G

        # --------------------------------------------------
        # mapa trecho → TIP_CND  (legado)
        # --------------------------------------------------

        # MT
        tip_map = {
            str(r["COD_ID"]): clean(r.get("TIP_CND"))
            for _, r in df_SSDMT.iterrows()
        }

        # BT — legado também fazia isso
        for _, r in df_SSDBT.iterrows():
            tip_map[str(r["COD_ID"])] = clean(r.get("TIP_CND"))


        # --------------------------------------------------
        # SEGCON → R1 X1 (legado)
        # --------------------------------------------------

        cols = {c.upper(): c for c in df_SEGCON.columns}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        cR1 = pick("R1","RES_FAS","R_POS")
        cX1 = pick("X1","REAT_FAS","X_POS")

        if cR1 is None or cX1 is None:
            raise RuntimeError("SEGCON não possui R1/X1")

        seg_map = {
            clean(r["COD_ID"]): r
            for _, r in df_SEGCON.iterrows()
        }

        # --------------------------------------------------
        # Carson modificado — FUNÇÃO LEGADO
        # --------------------------------------------------

        def carson_modificada_Zabc(R1, X1, distancias):

            dab, dbc, dac = distancias

            posicoes = {
                'a': (0, 0),
                'b': (dab, 0),
                'c': (dac, 0)
            }

            Z1_alvo = R1 + 1j*X1
            r = R1

            K = 0.0754
            constante = 7.934
            Rg = 0.0592

            def montar_Zabc(GMR):

                ch = ['a','b','c']
                Z = np.zeros((3,3),dtype=complex)

                for i,fi in enumerate(ch):
                    xi,_ = posicoes[fi]

                    for j,fj in enumerate(ch):
                        xj,_ = posicoes[fj]

                        if i==j:
                            Z[i,j] = (r+Rg) + 1j*K*(np.log(1/GMR)+constante)
                        else:
                            Dij = abs(xi-xj)
                            Z[i,j] = Rg + 1j*K*(np.log(1/Dij)+constante)

                return Z

            def Zabc_to_seq(Z):

                a = np.exp(1j*2*np.pi/3)

                A = np.array([
                    [1,1,1],
                    [1,a*a,a],
                    [1,a,a*a]
                ])

                return np.linalg.inv(A) @ Z @ A

            def erro(GMR):
                if GMR <= 0:
                    return 1e6
                Z = montar_Zabc(GMR)
                Zseq = Zabc_to_seq(Z)
                return abs(Zseq[1,1] - Z1_alvo)

            res = minimize_scalar(erro, bounds=(1e-4,0.1), method='bounded')
            return montar_Zabc(res.x)

        # distâncias típicas que você definiu
        distancias = (0.6, 0.6, 1.2)

        # --------------------------------------------------
        # aplicar nas arestas
        # --------------------------------------------------

        for u,v,d in G.edges(data=True):

            if d.get("tipo") not in ("MV_Line","SSDBT"):
                continue

            line_id = str(d.get("COD_ID"))
            tip = tip_map.get(line_id)

            if not tip:
                continue

            seg = seg_map.get(tip)
            if seg is None:
                continue

            R1 = float(seg[cR1])
            X1 = float(seg[cX1])

            Zabc_km = carson_modificada_Zabc(R1, X1, distancias)

            L_km = float(d.get("comprimento",1.0)) / 1000.0
            Zabc = Zabc_km * L_km

            # respeitar fases (legado)
            fas = clean(d.get("fases","ABC")).replace("N","")
            mask = ['A' in fas, 'B' in fas, 'C' in fas]

            for i,a in enumerate(mask):
                if not a:
                    Zabc[i,:]=0
                    Zabc[:,i]=0

            d["Zabc"] = Zabc

        return G
