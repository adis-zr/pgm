"""Population and empirical second moments must use the same physical units."""
import unittest

from research.campaigns.hp import dgp10_analyze as ANALYZE

class MomentDiagnosticUnits(unittest.TestCase):
    @staticmethod
    def heatbath():
        return dict(worst_radius_on_inventory=0.02, certified_N=1000000,
                    transitions_recorded=1000000, steps_per_second=1000,
                    phases_s=dict(sampling=18.0))

    @staticmethod
    def response(k=4, upper=27 / 2048, normalized='1/128', bound='9/16'):
        return dict(executed=True, moment_bounds={str(k): bound},
                    groups=[dict(k=k, U=upper, y_max=normalized, M=15625,
                                 sites=64, U_mode='checked', R=0.02)])

    def test_card4_scaling_changes_limiting_term(self):
        # The physical sample upper moment is (9/16)*(1/128).
        # U is three times that value; mixing units would report 1.6875.
        result = ANALYZE.limiting_term(self.heatbath(), self.response())
        self.assertAlmostEqual(result['moment_inflation'], 3.0)
        self.assertEqual(result['term'], 'moment_conservatism')

    def test_binary_moment_inflation(self):
        result = ANALYZE.limiting_term(
            self.heatbath(), self.response(2, 0.0105, '1/25', '1/4'))
        self.assertAlmostEqual(result['moment_inflation'], 1.05)

    def test_missing_scale_does_not_invent_inflation(self):
        response = self.response()
        del response['moment_bounds']
        result = ANALYZE.limiting_term(self.heatbath(), response)
        self.assertIsNone(result['moment_inflation'])

    def test_raw_result_bound_reaches_analysis(self):
        cell = dict(arm='RESPONSE', _dir='/tmp/dgp10-analysis-unit-test',
                    _result=dict(K=0, answers=[], mechanism=dict(
                        response=dict(B={'4': '9/16'}))),
                    response=dict(executed=True, groups=[]))
        row = ANALYZE.cell_row(cell)
        self.assertEqual(row['response']['moment_bounds'], {'4': '9/16'})
        self.assertNotIn('moment_bounds', cell['response'])


if __name__ == '__main__':
    unittest.main()
