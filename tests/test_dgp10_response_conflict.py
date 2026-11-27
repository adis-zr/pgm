"""Response conflicts must not turn a tight retained raw enclosure into publication."""
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

from pgm.algorithms.response import markov_certificate as MC
from pgm.algorithms.response import response_certificate as RC
from pgm.algorithms.response import spectral_heatbath_run as RUN


class ResponseConflictPublication(unittest.TestCase):
    def test_conflict_withholds_entire_original_variable(self):
        raw = [(F(499, 1000), F(501, 1000))] * 2
        incompatible = [dict(lo=F(7, 10), hi=F(71, 100)),
                        dict(lo=F(29, 100), hi=F(3, 10))]
        _, conflict = RC.intersect_boxes(raw, incompatible)
        self.assertTrue(conflict)
        other = [(F(749, 1000), F(751, 1000)),
                 (F(249, 1000), F(251, 1000))]
        pub, enc, stats = RUN.publish_response_boxes(
            [raw, other], F(1, 200), [7, 11], {}, [dict(var=7, canonical=0)])
        self.assertEqual(set(pub), {(11, 0), (11, 1)})
        self.assertEqual(enc, [(7, a, *bounds) for a, bounds in enumerate(raw)])
        self.assertEqual(stats['variables_published'], 1)
        self.assertEqual(sum(stats['point_policy_counts'].values()), 1)

    def test_no_conflict_preserves_publication_and_diagnostics(self):
        boxes = [[(F(499, 1000), F(501, 1000))] * 2,
                 [(F(1, 5), F(2, 5)), (F(3, 5), F(4, 5))]]
        expected = MC.rows_from_boxes(boxes, F(1, 200), [3, 9], {})
        self.assertEqual(RUN.publish_response_boxes(
            boxes, F(1, 200), [3, 9], {}, []), expected)

    def test_wide_conflict_keeps_one_enclosure_per_coordinate(self):
        boxes = [[(F(1, 5), F(2, 5)), (F(3, 5), F(4, 5))]]
        pub, enc, stats = RUN.publish_response_boxes(
            boxes, F(1, 200), [5], {}, [dict(var=5, canonical=0)])
        self.assertEqual(pub, {})
        self.assertEqual(enc, [(5, a, *bounds) for a, bounds in enumerate(boxes[0])])
        self.assertEqual(stats['variables_published'], 0)


if __name__ == '__main__':
    unittest.main()
