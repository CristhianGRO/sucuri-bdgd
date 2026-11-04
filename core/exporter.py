import os
import numpy as np
from pathlib import Path
from app.utils import fases_to_mask


class PowerFlowExporter:

    # ---------------- PHASE HELPERS ----------------

    def _infer_phases_from_z(self, Z, eps=1e-9):
        keep = [0, 0, 0]
        for k in range(3):
            if np.max(np.abs(Z[k, :])) > eps or np.max(np.abs(Z[:, k])) > eps:
                keep[k] = 1
        return keep

    def _phase_flag_to_int(self, keep):
        keep = (keep + [0, 0, 0])[:3]
        return int(f"{keep[0]}{keep[1]}{keep[2]}")

    def _mask_to_keep3(self, mask):
        s = str(mask).zfill(3)
        s = s[-3:]
        return [1 if c == "1" else 0 for c in s]

    # ---------------- NUMERIC HELPERS ----------------

    def _fallback_small_Zabc(self, branch_id):
        base = 0.05 + 1j * 0.10
        h = (abs(hash(branch_id)) % 1000) / 1000.0

        Zaa = base * (1 + 0.3*(h-0.5))
        Zbb = base * (1 - 0.2*(h-0.5))
        Zcc = base * (1 + 0.1*(h-0.5))

        Zm = base * 0.08

        Z = np.array([
            [Zaa, Zm, Zm*0.9],
            [Zm*0.95, Zbb, Zm*1.1],
            [Zm*1.05, Zm*0.9, Zcc]
        ], dtype=complex)

        return Z

    def _fmt(self, v):
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            return f"{v:.6f}"
        try:
            if isinstance(v, np.integer):
                return str(int(v))
            if isinstance(v, np.floating):
                return f"{float(v):.6f}"
        except:
            pass
        return str(v)

    def _write_rows(self, path, rows):
        with open(path, "w") as f:
            f.write(str(len(rows)) + "\n")
            for r in rows:
                f.write(" ".join(self._fmt(x) for x in r) + "\n")

    # ---------------- INIT ----------------

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self._n_areas = 2

    def _out(self, rede, cidade, ctmt):
        cidade = cidade or "INDEFINIDO"
        path = os.path.join(self.base_dir, rede, "PowerFlow", cidade, ctmt)
        os.makedirs(path, exist_ok=True)
        return path

    # =========================================================
    # ÁREAS POR TRANSFORMADOR BT
    # =========================================================

    def _build_transformer_area_map(self, G):
        area_id = 2
        for _, _, d in G.edges(data=True):
            if d.get("tipo") == "MT_BT_Transformer_Connection":
                d["_area_id"] = area_id
                area_id += 1
        self._n_areas = area_id - 1

    def _assign_bus_areas_by_transformer(self, G):

        BT_EDGE_TYPES = {"SSDBT", "RAMLIG"}

        # default MV
        for n in G.nodes():
            G.nodes[n]["Area"] = 1

        for u, v, d in G.edges(data=True):

            if d.get("tipo") != "MT_BT_Transformer_Connection":
                continue

            area_id = d["_area_id"]

            tu = G.nodes[u].get("tipo_no")
            tv = G.nodes[v].get("tipo_no")

            if tv in ("PAC_LV", "PAC_RAMLIG", "Transformer_Sec", "UCBT"):
                start = v
            else:
                start = u

            stack = [start]
            visited = set()

            while stack:
                n = stack.pop()
                if n in visited:
                    continue
                visited.add(n)

                G.nodes[n]["Area"] = area_id

                for a, b, ed in G.edges(n, data=True):

                    if ed.get("tipo") == "MT_BT_Transformer_Connection":
                        continue

                    if ed.get("tipo") in BT_EDGE_TYPES:
                        nxt = b if a == n else a
                        if nxt not in visited:
                            stack.append(nxt)

    # ---------------- BUS PHASE REBUILD ----------------

    def _recompute_bus_phases_from_branches(self, G):
        phase_acc = {n: [0, 0, 0] for n in G.nodes()}

        for u, v, d in G.edges(data=True):

            Z = d.get("Zabc")
            if Z is None or np.allclose(Z, 0):
                Z = self._fallback_small_Zabc(d.get("COD_ID", 0))

            keep_z = self._infer_phases_from_z(Z)

            f = d.get("fases") or d.get("FAS_CON")
            keep_decl = None

            if f and str(f).upper() not in ("", "NAN", "NONE"):
                mask = fases_to_mask(f)
                keep_decl = [int(c) for c in mask]

            if keep_decl is not None:
                keep = [keep_decl[i] & keep_z[i] for i in range(3)]
            else:
                keep = keep_z

            if keep == [0,0,0]:
                continue

            for k in range(3):
                if keep[k]:
                    phase_acc[u][k] = 1
                    phase_acc[v][k] = 1

        for n in G.nodes():
            keep = phase_acc[n]
            if keep == [0,0,0]:
                keep = [1,0,0]
            G.nodes[n]["phases"] = self._phase_flag_to_int(keep)

    # ---------------- EXPORT ----------------

    def export_all(self, G, rede, ctmt, cidade=""):
        out = self._out(rede, cidade, ctmt)

        self._build_transformer_area_map(G)
        self._assign_bus_areas_by_transformer(G)
        self._recompute_bus_phases_from_branches(G)

        nodes = sorted(G.nodes(), key=lambda x: str(x))
        node_map = {n: i+1 for i, n in enumerate(nodes)}

        self._bus(G, node_map, out)
        self._branch(G, node_map, out)
        self._areas(out)
        self._transformer(G, node_map, out)

        return out

    # ---------------- BUS ----------------

    def _bus(self, G, node_map, out):

        rows = []
        ordered_nodes = sorted(G.nodes(), key=lambda n: node_map[n])

        for n in ordered_nodes:
            d = G.nodes[n]

            rows.append([
                node_map[n],
                d["Area"],
                d.get("phases", 111),
                str(n),
                d.get("DESCRICAO", ""),
                d.get("Type", 1),
                d.get("Z", 0),
                d.get("I", 0),
                d.get("P", 1),
                d.get("Vnom", 1.0),
                d.get("Connection", 0),
                d.get("VLN_a", 1), d.get("Deg_a", 0),
                d.get("VLN_b", 1), d.get("Deg_b", -120),
                d.get("VLN_c", 1), d.get("Deg_c", 120),
                d.get("Pa_kW", 0), d.get("Qa_kVAr", 0),
                d.get("Pb_kW", 0), d.get("Qb_kVAr", 0),
                d.get("Pc_kW", 0), d.get("Qc_kVAr", 0),
                0.93, 1.05
            ])

        self._write_rows(os.path.join(out, "data_bus.dad"), rows)

    # ---------------- BRANCH ----------------

    def _branch(self, G, node_map, out):

        rows = []
        k = 1

        for u, v, d in G.edges(data=True):

            tipo = d.get("tipo", "")

            if tipo == "MT_BT_Transformer_Connection":
                type_code = 1
            elif "Switch" in tipo:
                type_code = 4
            else:
                type_code = 0

            Z = d.get("Zabc")
            used_fallback = False

            if Z is None or np.allclose(Z, 0):
                Z = self._fallback_small_Zabc(d.get("COD_ID", k))
                used_fallback = True

            keep_z = self._infer_phases_from_z(Z)

            f = d.get("fases") or d.get("FAS_CON")
            keep_decl = None

            if f and str(f).upper() not in ("", "NAN", "NONE"):
                mask = fases_to_mask(f)
                keep_decl = [int(c) for c in mask]

            if keep_decl is not None:
                keep = [keep_decl[i] & keep_z[i] for i in range(3)]
            else:
                keep = keep_z

            if keep == [0, 0, 0]:
                keep = keep_z if any(keep_z) else [1, 0, 0]

            phases = self._phase_flag_to_int(keep)

            if used_fallback:
                for i in range(3):
                    if keep[i] == 0:
                        Z[i, :] = 0
                        Z[:, i] = 0

            if tipo == "MT_BT_Transformer_Connection":
                area = d["_area_id"]
            else:
                au = G.nodes[u]["Area"]
                av = G.nodes[v]["Area"]
                area = au if au == av else au

            row = [
                k,
                area,
                phases,
                node_map[u],
                node_map[v],
                type_code,
                0, 0, 0,
                Z[0,0].real, Z[0,0].imag,
                Z[1,0].real, Z[1,0].imag,
                Z[1,1].real, Z[1,1].imag,
                Z[2,0].real, Z[2,0].imag,
                Z[2,1].real, Z[2,1].imag,
                Z[2,2].real, Z[2,2].imag,
                0, 0, 0, 0, 0, 0
            ]

            rows.append(row)
            d["branch_id"] = k
            k += 1

        self._write_rows(os.path.join(out, "data_branch.dad"), rows)

    # ---------------- TRANSFORMER ----------------

    def _transformer(self, G, node_map, out):
        out = Path(out)
        rows = []

        for u, v, d in G.edges(data=True):
            if d.get("tipo") != "MT_BT_Transformer_Connection":
                continue

            p = d.get("trafo_params")
            if not p:
                continue

            rows.append([
                len(rows)+1,
                d["branch_id"],
                1,
                d["_area_id"],
                0,
                node_map[u],
                node_map[v],
                p["Snom"],
                p["Rpu"],
                p["Xpu"],
                13.8,
                0.22,
                1.0,
                1.0
            ])

        self._write_rows(out / "data_transformer.dad", rows)

    # ---------------- AREAS ----------------

    def _areas(self, out):

        SBASE = 10
        VBASE_MT = 13.8
        VBASE_BT = 0.22

        with open(os.path.join(out, "data_areas.dad"), "w") as f:
            f.write(str(self._n_areas) + "\n")
            f.write(f"1 {SBASE} {VBASE_MT}\n")

            for a in range(2, self._n_areas + 1):
                f.write(f"{a} {SBASE} {VBASE_BT}\n")
