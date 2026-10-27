import unittest

from cagerail.simulate import run


class TestSimulate(unittest.TestCase):
    def test_cage_survives_better_than_naked(self):
        naked = run(caged=False)
        caged = run(caged=True)
        self.assertGreater(caged.final_equity, naked.final_equity)
        self.assertLess(caged.max_drawdown, naked.max_drawdown)
        self.assertLessEqual(caged.max_drawdown, 0.30)

    def test_deterministic(self):
        self.assertEqual(run(caged=True).final_equity, run(caged=True).final_equity)


if __name__ == "__main__":
    unittest.main()
