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

            # UCBT é uma carga conectada a uma barra BT; a barra mantém seu
            # tipo físico (PAC_LV/PAC_RAMLIG) para o desenho da topologia.
            if d.get("ucbt_row"):

                n_ucbt_nodes += 1

                rows = d.get("ucbt_rows") or [d.get("ucbt_row")]
                rows = [row for row in rows if isinstance(row, dict)]
                if not rows:
                    continue
                for row in rows:
                    # energia mensal kWh; cada UC da mesma barra contribui
                    # para a potência trifásica do nó.
                    energy = 0.0
                    for i in range(1,13):
                        try:
                            energy += float(row.get(f"ENE_{i:02d}", 0) or 0)
                        except (TypeError, ValueError):
                            pass
                    if energy <= 0:
                        continue
                    # O fator de carga de 0,3 converte a energia média em
                    # uma estimativa de demanda de pico coincidente.
                    power = energy / (12 * 30 * 24 * 0.3)
                    phases = str(row.get("FAS_CON","ABC")).upper().strip()
                    active = [phase for phase in "ABC" if phase in phases] or list("ABC")
                    per_phase = power / len(active)
                    reactive = per_phase * math.tan(math.acos(.95))
                    d["phases"] = "".join("1" if phase in active else "0" for phase in "ABC")
                    d["Area"] = 2
                    for phase in active:
                        d[f"P{phase.lower()}_kW"] += per_phase
                        d[f"Q{phase.lower()}_kVAr"] += reactive
                    n_load_applied += 1

        self.log(f"UCBT nós no grafo = {n_ucbt_nodes}")
        self.log(f"Cargas aplicadas = {n_load_applied}")
        self.log("=== LOAD DEBUG END ===")

        return G



