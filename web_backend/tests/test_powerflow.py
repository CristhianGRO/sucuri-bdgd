from unittest import TestCase
import networkx as nx
import numpy as np
import pandas as pd
from app.controller import Controller
from core.powerflow import BackwardForwardSweep
from web_backend.worker import apply_tap_overrides


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

    def test_converged_solution_is_a_hot_start_for_the_next_flow(self):
        graph = nx.Graph()
        graph.add_node('SE', tipo_no='Substation', voltage_base_kv=13.8)
        graph.add_node('LOAD', Pa_kW=180, Qa_kVAr=70, Pb_kW=150, Qb_kVAr=55, Pc_kW=165, Qc_kVAr=60)
        graph.add_edge('SE', 'LOAD', tipo='MV_Line', Zabc=np.eye(3, dtype=complex) * (.45 + .25j))
        first_solver = BackwardForwardSweep()
        cold = first_solver.solve(graph)
        warm = BackwardForwardSweep().solve(graph, initial_voltages=first_solver.last_voltage_state)
        self.assertTrue(warm['warm_start_used'])
        self.assertFalse(warm['warm_start_fallback'])
        self.assertLess(warm['iterations'], cold['iterations'])

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

    def test_tap_override_changes_only_the_selected_transformer(self):
        graph = nx.Graph()
        graph.add_edge('SE', 'BT', tipo='MT_BT_Transformer_Connection', COD_ID='TR_1', trafo_params={'tap_ratio': 1.0})
        graph.add_edge('SE', 'OTHER', tipo='MT_BT_Transformer_Connection', COD_ID='TR_2', trafo_params={'tap_ratio': 1.0})
        self.assertEqual(apply_tap_overrides(graph, {'tr_1': .95}), 1)
        self.assertEqual(graph['SE']['BT']['trafo_params']['tap_ratio'], .95)
        self.assertEqual(graph['SE']['OTHER']['trafo_params']['tap_ratio'], 1.0)

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
