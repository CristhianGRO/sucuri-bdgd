from unittest import TestCase
import networkx as nx
import numpy as np
import pandas as pd
from app.controller import Controller
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

    def test_primary_tap_below_one_elevates_secondary_voltage(self):
        graph = nx.Graph()
        graph.add_node('SE', tipo_no='Substation', voltage_base_kv=13.8)
        graph.add_node('BT')
        graph.add_edge('SE', 'BT', tipo='MT_BT_Transformer_Connection', trafo_params={'Snom':45, 'Rpu':0, 'Xpu':0, 'Vsec':.22, 'tap_ratio':.95})
        BackwardForwardSweep().solve(graph)
        self.assertAlmostEqual(graph.nodes['BT']['voltage_avg_pu'], 1/.95, places=4)

    def test_substation_setpoint_is_not_interpreted_as_a_voltage_base(self):
        graph = nx.Graph()
        graph.add_node('SE', tipo_no='Substation', voltage_base_kv=13.8, voltage_setpoint_pu=1.025)
        graph.add_node('LOAD', Pa_kW=20)
        graph.add_edge('SE', 'LOAD', tipo='MV_Line', Zabc=np.eye(3, dtype=complex) * .1)
        BackwardForwardSweep().solve(graph)
        self.assertAlmostEqual(graph.nodes['SE']['voltage_avg_pu'], 1.025, places=5)
        self.assertAlmostEqual(graph.nodes['SE']['voltage_base_kv'], 13.8, places=4)

    def test_transformer_impedance_is_converted_to_the_system_base(self):
        graph = nx.Graph()
        graph.add_node('SE', tipo_no='Substation', voltage_base_kv=13.8)
        graph.add_node('BT')
        graph.add_edge('SE', 'BT', tipo='MT_BT_Transformer_Connection',
                       trafo_params={'Snom': 100, 'Rpu': .01, 'Xpu': .04, 'Vsec': .22})
        solver = BackwardForwardSweep(sbase_mva=1)
        z = solver._z_pu(graph['SE']['BT'], 13.8)
        self.assertAlmostEqual(z[0, 0].real, .1, places=8)
        self.assertAlmostEqual(z[0, 0].imag, .4, places=8)

    def test_aneel_tten_fallback_resolves_cpfl_code_42(self):
        voltage = Controller._nominal_voltage_kv(pd.Series({'TEN_NOM': '42'}), pd.DataFrame())
        self.assertEqual(voltage, 11.9)
