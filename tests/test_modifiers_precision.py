#!/usr/bin/env python3
import os
import sys
import unittest

# Allow running as a script without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestModifiersPrecision(unittest.TestCase):
    def test_quantize_scientific_step_nearest(self):
        from core.utils.modifiers import quantize_to_step

        # Steps are sometimes represented as scientific notation (e.g. 1e-05).
        self.assertAlmostEqual(quantize_to_step(0.15702, 1e-05), 0.15702)
        self.assertAlmostEqual(quantize_to_step(0.157023, 1e-05), 0.15702)
        # Exact half-step tie should use half-even for "nearest"
        self.assertAlmostEqual(quantize_to_step(0.157025, 1e-05, rounding="nearest"), 0.15702)

    def test_quantize_scientific_step_down(self):
        from core.utils.modifiers import quantize_to_step

        self.assertAlmostEqual(quantize_to_step(0.157029, 1e-05, rounding="down"), 0.15702)
        self.assertAlmostEqual(quantize_to_step(-0.157029, 1e-05, rounding="down"), -0.15702)
        # Avoid negative zero
        self.assertEqual(quantize_to_step(-1e-10, 1e-05, rounding="down"), 0.0)

    def test_sanitize_lots_dust_to_zero(self):
        from core.utils.modifiers import sanitize_lots

        self.assertEqual(
            sanitize_lots(0.000009, 1e-05, 1e-05, allow_below_min_to_zero=True, rounding="down"),
            0.0,
        )

    def test_scale_size_and_price_scientific_step(self):
        from core.utils.modifiers import scale_size_and_price

        lots, price, _ = scale_size_and_price(
            "DOGEUSDT",
            size=0.00003,
            price=0.09361,
            lot_size=1e-05,
            min_lots=1e-05,
            tick_size=1e-05,
            contract_value=1.0,
        )
        self.assertAlmostEqual(lots, 0.00003)
        self.assertAlmostEqual(price, 0.09361)

        lots, _, _ = scale_size_and_price(
            "DOGEUSDT",
            size=0.000001,  # below min
            price=0,
            lot_size=1e-05,
            min_lots=1e-05,
            tick_size=1e-05,
            contract_value=1.0,
        )
        self.assertAlmostEqual(lots, 1e-05)


if __name__ == "__main__":
    unittest.main()
