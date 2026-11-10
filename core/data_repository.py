import os
import pandas as pd


class DataRepository:

    CHUNK = 50000

    HEAVY = {
        "SSDMT",
        "SSDBT",
        "UNSEMT",
        "UNSEBT",
        "UNTRMT",
        "RAMLIG",
        "UCBT"
    }

    TABLES = [
        "SEGCON",
        "CRVCRG",
        "UNTRAT",
        "CTMT",
        # TTEN converte o código CTMT.TEN_NOM para tensão nominal em volts.
        # TEN_OPE não é uma tensão em kV: é o setpoint de operação em pu.
        "TTEN",
        "SSDMT",
        "SSDBT",
        "UNSEMT",
        "UNSEBT",
        "UNTRMT",
        "RAMLIG",
        "UCBT",
        "PONNOT"
    ]

    # -----------------------------------------------------

    def __init__(self, base_path):
        self.base = base_path

    # -----------------------------------------------------

    def load_feeder_data(self, rede, ctmt):

        print(f"[Repo] === feeder {ctmt} ===")

        folder = os.path.join(self.base, rede)
        data = {}

        for t in self.TABLES:

            if t == "PONNOT":
                continue

            path = os.path.join(folder, f"{t}.csv")
            if not os.path.exists(path):
                data[t] = pd.DataFrame()
                continue

            if t in self.HEAVY:
                df = self._read_heavy_filtered(path, ctmt)
            else:
                df = pd.read_csv(path, dtype=str)

            data[t] = df
            print(f"[Repo] {t}: {len(df)}")

        # ---------------------------------------------
        # PONNOT sob demanda (igual legado)
        # ---------------------------------------------

        needed = self._collect_needed_pn_pac(data)
        print(f"[Repo] PN/PAC needed for PONNOT = {len(needed)}")

        pon_path = os.path.join(folder, "PONNOT.csv")
        data["PONNOT"] = self._read_ponnot_filtered(pon_path, needed)

        print(f"[Repo] PONNOT: {len(data['PONNOT'])}")

        return data

    # -----------------------------------------------------
    # heavy reader — chunk + filtro CTMT
    # -----------------------------------------------------

    def _read_heavy_filtered(self, path, ctmt):

        print(f"[Repo][DEBUG] heavy read → {os.path.basename(path)} filter=CTMT")

        kept = []
        total = 0

        for i, chunk in enumerate(pd.read_csv(
                path,
                chunksize=self.CHUNK,
                dtype=str,
                low_memory=True
        )):

            total += len(chunk)

            if "CTMT" in chunk.columns:
                sub = chunk[chunk["CTMT"] == ctmt]
            else:
                sub = chunk

            if len(sub):
                kept.append(sub)

            if i % 20 == 0:
                print(f"[Repo][DEBUG] chunk {i} total={total} kept_rows={sum(len(x) for x in kept)}")

        if not kept:
            print("[Repo][DEBUG] nenhum registro do feeder")
            return pd.DataFrame()

        df = pd.concat(kept, ignore_index=True)
        print(f"[Repo][DEBUG] FINAL kept={len(df)}")
        return df

    # -----------------------------------------------------
    # coletar PN/PAC necessários — igual legado
    # -----------------------------------------------------

    def _collect_needed_pn_pac(self, data):

        needed = set()

        def add(col, df):
            if df is None or df.empty or col not in df.columns:
                return
            needed.update(df[col].dropna().astype(str))

        # SSDMT
        add("PN_CON_1", data["SSDMT"])
        add("PN_CON_2", data["SSDMT"])
        add("PAC_1", data["SSDMT"])
        add("PAC_2", data["SSDMT"])

        # SSDBT
        add("PAC_1", data["SSDBT"])
        add("PAC_2", data["SSDBT"])

        # UNTRMT
        add("PAC_1", data["UNTRMT"])
        add("PAC_2", data["UNTRMT"])

        # RAMLIG
        add("PAC_1", data["RAMLIG"])
        add("PAC_2", data["RAMLIG"])

        # UCBT
        add("PAC", data["UCBT"])

        return needed

    # -----------------------------------------------------
    # PONNOT chunked sob demanda
    # -----------------------------------------------------

    def _read_ponnot_filtered(self, path, needed):

        if not os.path.exists(path):
            return pd.DataFrame()

        kept = []

        for chunk in pd.read_csv(
                path,
                chunksize=self.CHUNK,
                dtype=str,
                low_memory=True
        ):

            if "COD_ID" not in chunk.columns:
                continue

            sub = chunk[chunk["COD_ID"].isin(needed)]

            if len(sub):
                kept.append(sub)

        if not kept:
            return pd.DataFrame()

        return pd.concat(kept, ignore_index=True)
