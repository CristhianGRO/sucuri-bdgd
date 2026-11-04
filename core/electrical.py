import os
import pandas as pd
import math


class ElectricalCalculator:

    def __init__(self, logger=None):
        self.log = logger if logger else print

    def calculate_loads(self, G, rede, CTMT, df_UCBT, base_path):

        self.log("=== LOAD DEBUG START ===")

        ctmt_path = os.path.join(base_path, rede, "CTMT.csv")
        ctmt_df = pd.read_csv(ctmt_path)

        T_pu = float(
            ctmt_df[ctmt_df['COD_ID'].astype(str)==str(CTMT)]['TEN_OPE'].values[0]
        )

        crv_path = os.path.join(base_path, rede, "CRVCRG.csv")
        if os.path.exists(crv_path):
            CRV = pd.read_csv(crv_path)
        else:
            CRV = pd.DataFrame()

        n_ucbt_nodes = 0
        n_load_applied = 0


        for n, d in G.nodes(data=True):

            # -------- defaults --------

            d["phases"]="111"
            d["Z"]=0; d["I"]=0; d["P"]=1
            d["Area"]=1
            d["Type"]=1
            d["Vnom"]=1.0
            d["Connection"]=0

            d["VLN_a"]=d["VLN_b"]=d["VLN_c"]=1.0
            d["Deg_a"]=0; d["Deg_b"]=-120; d["Deg_c"]=120

            d["Pa_kW"]=d["Qa_kVAr"]=0.0
            d["Pb_kW"]=d["Qb_kVAr"]=0.0
            d["Pc_kW"]=d["Qc_kVAr"]=0.0

            d["Vmin[pu]"]=0.93
            d["Vmax[pu]"]=1.05
            d["DESCRICAO"]=str(n)

            # -------- slack --------

            if d.get("tipo_no")=="Substation":
                d["Type"]=0
                d["VLN_a"]=d["VLN_b"]=d["VLN_c"]=T_pu
                continue

            # -------- loads --------

            if d.get("tipo_no") == "UCBT":

                n_ucbt_nodes += 1

                row = d.get("ucbt_row")
                if not row:
                    continue

                tip = row.get("TIP_CC")

                if tip and not CRV.empty:
                    r = CRV[CRV["COD_ID"] == tip]
                    if len(r):
                        r = r.iloc[0]
                        for i in range(1,97):
                            k = f"POT_{i:02d}"
                            if k in r:
                                d[k] = float(r[k])


                # energia mensal kWh (seu schema confirmado)
                E_total = 0.0
                for i in range(1,13):
                    k = f"ENE_{i:02d}"
                    if k in row:
                        try:
                            E_total += float(row[k])
                        except:
                            pass

                if E_total <= 0:
                    continue

                # kW médio
                P = E_total / (12 * 30 * 24 * 0.3) # 0.3 é o fator de carga médio

                fases = str(row.get("FAS_CON","ABC")).upper().strip()

                mask = "".join(
                    "1" if p in fases else "0"
                    for p in "ABC"
                )

                d["phases"] = mask
                d["Area"] = 2

                k = mask.count("1") or 1

                fp = 0.95
                def Q(x): 
                    return x*math.tan(math.acos(fp))

                if mask[0]=="1":
                    d["Pa_kW"]=P/k; d["Qa_kVAr"]=Q(d["Pa_kW"])
                if mask[1]=="1":
                    d["Pb_kW"]=P/k; d["Qb_kVAr"]=Q(d["Pb_kW"])
                if mask[2]=="1":
                    d["Pc_kW"]=P/k; d["Qc_kVAr"]=Q(d["Pc_kW"])

                n_load_applied += 1

        self.log(f"UCBT nós no grafo = {n_ucbt_nodes}")
        self.log(f"Cargas aplicadas = {n_load_applied}")
        self.log("=== LOAD DEBUG END ===")

        return G



