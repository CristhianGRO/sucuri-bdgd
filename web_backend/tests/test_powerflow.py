from unittest import TestCase
import networkx as nx
import numpy as np
from core.powerflow import BackwardForwardSweep


class BackwardForwardSweepTests(TestCase):
    def test_radial_three_phase_load_has_voltage_drop_and_branch_metrics(self):
        graph = nx.Graph()
        graph.add_node('SE', tipo_no='Substation', voltage_base_kv=13.8)
        graph.add_node('LOAD', Pa_kW=120, Qa_kVAr=50, Pb_kW=100, Qb_kVAr=40, Pc_kW=110, Qc_kVAr=45)
        graph.add_edge('SE', 'LOAD', tipo='MV_Line', Zabc=np.eye(3, dtype=complex) * (.45 + .3j))
        result = BackwardForwardSweep().solve(graph)
        self.assertTrue(result['converged'])
        self.assertLess(graph.nodes['LOAD']['voltage_min_pu'], 1)
        self.assertGreater(graph['SE']['LOAD']['pf_p_kw'], 300)
        self.assertGreater(graph['SE']['LOAD']['pf_current_a'], 0)

    def test_reports_meshed_link_without_failing(self):
        graph = nx.Graph()
        graph.add_node('SE', tipo_no='Substation', voltage_base_kv=13.8)
        graph.add_node('A', Pa_kW=10)
        graph.add_node('B', Pb_kW=10)
        for left, right in [('SE', 'A'), ('A', 'B'), ('B', 'SE')]:
            graph.add_edge(left, right, tipo='MV_Line', Zabc=np.eye(3, dtype=complex) * .1)
        result = BackwardForwardSweep().solve(graph)
        self.assertGreater(result['radial_links_ignored'], 0)
