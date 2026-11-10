"""Fluxo de potência radial trifásico por varredura direta/inversa.

Implementação inicial baseada na formulação de Backward/Forward Sweep para
redes de distribuição, com modelo ABC em pu. Redes com enlaces são
radializadas por uma árvore de busca e os enlaces removidos são reportados;
eles não são silenciosamente tratados como se fossem parte da solução.
"""
from collections import deque
import math
import numpy as np


class BackwardForwardSweep:
    def __init__(self, sbase_mva=1.0, tolerance=5e-5, max_iterations=250, relaxation=.35):
        self.sbase_mva = float(sbase_mva)
        self.tolerance = float(tolerance)
        self.max_iterations = int(max_iterations)
        self.relaxation = float(relaxation)

    @staticmethod
    def _complex_voltage():
        return np.array([1 + 0j, complex(-.5, -math.sqrt(3)/2), complex(-.5, math.sqrt(3)/2)])

    @staticmethod
    def _number(value, default=0.0):
        try:
            value = float(value)
            return value if math.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    def _roots_and_tree(self, graph):
        roots = [node for node, data in graph.nodes(data=True) if data.get('tipo_no') == 'Substation']
        if not roots:
            raise ValueError('Fluxo de potência: nenhuma barra de subestação foi encontrada')
        root = roots[0]
        parent = {root: None}
        order = [root]
        tree_edges = {}
        links = []
        queue = deque([root])
        while queue:
            node = queue.popleft()
            for neighbor, edge in graph[node].items():
                if neighbor not in parent:
                    parent[neighbor] = node
                    tree_edges[neighbor] = edge
                    order.append(neighbor)
                    queue.append(neighbor)
                elif parent[node] != neighbor and parent.get(neighbor) != node:
                    edge_id = tuple(sorted((str(node), str(neighbor))))
                    if edge_id not in links:
                        links.append(edge_id)
        return root, parent, order, tree_edges, links

    def _voltage_bases(self, graph, root, parent, order, tree_edges):
        root_kv = self._number(graph.nodes[root].get('voltage_base_kv'), 0)
        if root_kv < .1:
            raise ValueError('Fluxo de potência: tensão nominal da subestação ausente (TTEN/CTMT)')
        bases = {root: root_kv}
        for node in order[1:]:
            predecessor = parent[node]
            edge = tree_edges[node]
            base = bases[predecessor]
            if edge.get('tipo') == 'MT_BT_Transformer_Connection':
                params = edge.get('trafo_params') or {}
                base = self._number(params.get('Vsec'), base)
            bases[node] = max(base, .1)
        return bases

    def _slack_voltage(self, graph, root):
        setpoint = self._number(graph.nodes[root].get('voltage_setpoint_pu'), 1.0)
        if not .8 <= setpoint <= 1.2:
            raise ValueError(f'Fluxo de potência: setpoint da subestação inválido ({setpoint})')
        return setpoint * self._complex_voltage()

    def _z_pu(self, edge, base_kv):
        if edge.get('tipo') == 'MT_BT_Transformer_Connection':
            params = edge.get('trafo_params') or {}
            # Rpu/Xpu foram calculados na base nominal do transformador. A
            # varredura usa uma base comum, logo é necessária a conversão
            # Zpu,sistema = Zpu,trafo * Sbase / Snom.
            snom_kva = max(self._number(params.get('Snom'), 1), 1)
            scale = self.sbase_mva * 1000 / snom_kva
            return np.eye(3, dtype=complex) * scale * complex(
                self._number(params.get('Rpu'), .01), self._number(params.get('Xpu'), .04)
            )
        raw = edge.get('Zabc')
        if raw is None:
            # Não inventa uma impedância de linha: ramais sem modelo são
            # tratados como ligação ideal e continuam reportados no resultado.
            return np.zeros((3, 3), dtype=complex)
        z = np.asarray(raw, dtype=complex)
        if z.shape != (3, 3):
            return np.zeros((3, 3), dtype=complex)
        zbase = base_kv ** 2 / self.sbase_mva
        return z / zbase

    def _load_current(self, data, voltage, multiplier=1.0):
        powers = np.array([
            complex(self._number(data.get('Pa_kW')), self._number(data.get('Qa_kVAr'))),
            complex(self._number(data.get('Pb_kW')), self._number(data.get('Qb_kVAr'))),
            complex(self._number(data.get('Pc_kW')), self._number(data.get('Qc_kVAr'))),
        ])
        # Base por fase: Sbase trifásica / 3.
        s_pu = multiplier * powers / (self.sbase_mva * 1000 / 3)
        safe_voltage = np.where(np.abs(voltage) > 1e-5, voltage, self._complex_voltage())
        return np.conj(s_pu / safe_voltage)

    def _tap_ratio(self, edge):
        if edge.get('tipo') != 'MT_BT_Transformer_Connection':
            return 1.0
        ratio = self._number((edge.get('trafo_params') or {}).get('tap_ratio'), 1.0)
        return ratio if .8 <= ratio <= 1.2 else 1.0

    def _branch_current(self, edge, downstream_current):
        # Com o tap no primário e bases de tensão nominais, a corrente vista
        # pelo lado de alta é a corrente secundária dividida pela relação tap.
        return downstream_current / self._tap_ratio(edge)

    def solve(self, graph):
        root, parent, order, tree_edges, links = self._roots_and_tree(graph)
        bases = self._voltage_bases(graph, root, parent, order, tree_edges)
        children = {node: [] for node in order}
        for node, predecessor in parent.items():
            if predecessor is not None:
                children[predecessor].append(node)
        slack_voltage = self._slack_voltage(graph, root)
        voltages = {node: slack_voltage.copy() for node in order}
        currents = {node: np.zeros(3, dtype=complex) for node in order[1:]}
        converged = False
        total_iterations = 0
        stage_diagnostics = []
        # Continuação de carga: aproxima a solução gradualmente para evitar a
        # oscilação de cargas de potência constante em redes longas.
        for multiplier in (.2, .4, .6, .8, 1.0):
            converged = False
            for iteration in range(1, self.max_iterations + 1):
                total_iterations += 1
                injections = {node: self._load_current(graph.nodes[node], voltages[node], multiplier) for node in order}
                for node in reversed(order[1:]):
                    downstream = injections[node].copy()
                    for child in children[node]:
                        downstream += currents[child]
                    currents[node] = self._branch_current(tree_edges[node], downstream)
                previous = {node: value.copy() for node, value in voltages.items()}
                voltages[root] = slack_voltage.copy()
                for node in order[1:]:
                    predecessor = parent[node]
                    edge = tree_edges[node]
                    z = self._z_pu(edge, bases[predecessor])
                    candidate = voltages[predecessor] / self._tap_ratio(edge) - z @ currents[node]
                    voltages[node] = self.relaxation * candidate + (1 - self.relaxation) * previous[node]
                error = max(float(np.max(np.abs(voltages[node] - previous[node]))) for node in order)
                if error < self.tolerance:
                    converged = True
                    break
            stage_diagnostics.append({
                'load_multiplier': multiplier,
                'iterations': iteration,
                'max_delta_pu': error,
                'min_voltage_pu': min(float(np.min(np.abs(value))) for value in voltages.values()),
                'max_voltage_pu': max(float(np.max(np.abs(value))) for value in voltages.values()),
            })
            if not converged:
                break
        if not converged:
            self.last_diagnostics = {'stages': stage_diagnostics, 'iterations': total_iterations}
            last = stage_diagnostics[-1]
            raise RuntimeError(
                f"Fluxo de potência não convergiu após {self.max_iterations} iterações "
                f"(carga={last['load_multiplier']:.0%}, ΔV={last['max_delta_pu']:.3e} pu); "
                "resultados não foram publicados"
            )
        self.last_diagnostics = {'stages': stage_diagnostics, 'iterations': total_iterations}
        for node in order:
            magnitude = np.abs(voltages[node])
            graph.nodes[node].update({
                'voltage_a_pu': round(float(magnitude[0]), 5),
                'voltage_b_pu': round(float(magnitude[1]), 5),
                'voltage_c_pu': round(float(magnitude[2]), 5),
                'voltage_avg_pu': round(float(np.mean(magnitude)), 5),
                'voltage_min_pu': round(float(np.min(magnitude)), 5),
                'voltage_base_kv': round(float(bases[node]), 4),
            })
        for node in order[1:]:
            predecessor = parent[node]
            edge = tree_edges[node]
            current = currents[node]
            power = np.sum(voltages[predecessor] * np.conj(current)) * (self.sbase_mva * 1000 / 3)
            z = self._z_pu(edge, bases[predecessor])
            loss = np.vdot(current, z @ current) * (self.sbase_mva * 1000 / 3)
            ibase = self.sbase_mva * 1_000_000 / (math.sqrt(3) * bases[predecessor] * 1000)
            edge.update({
                'pf_p_kw': round(float(power.real), 3),
                'pf_q_kvar': round(float(power.imag), 3),
                'pf_current_a': round(float(np.max(np.abs(current)) * ibase), 3),
                'pf_losses_kw': round(float(loss.real), 4),
                'pf_losses_kvar': round(float(loss.imag), 4),
            })
        return {
            'method': 'Backward/Forward Sweep trifásico ABC',
            'converged': converged,
            'iterations': total_iterations,
            'radial_links_ignored': len(links),
            'min_voltage_pu': min(data['voltage_min_pu'] for _, data in graph.nodes(data=True)),
            'max_voltage_pu': max(data['voltage_avg_pu'] for _, data in graph.nodes(data=True)),
        }
