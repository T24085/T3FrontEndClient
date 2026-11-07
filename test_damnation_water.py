"""Check splash contact math without launching the retail game."""

import unittest
from pathlib import Path

try:
    from lupa.lua54 import LuaRuntime
except ImportError:
    LuaRuntime = None


@unittest.skipUnless(LuaRuntime, "Lua 5.4 test runtime required")
class DamnationWaterContactTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        source = Path(__file__).parent / "lua" / "damnation_water.lua"
        _, self.contact = self.lua.execute(source.read_text(encoding="utf-8"))
        self.surface = self.lua.table(z=100, xmin=0, xmax=1000, ymin=0, ymax=1000)

    def point(self, x, z):
        return self.lua.table(X=x, Y=200, Z=z)

    def test_basin_entry_and_exit_interpolate_at_the_waterline(self):
        a, b = self.point(200, 170), self.point(400, 30)
        for previous, current in ((a, b), (b, a)):
            self.assertEqual(self.contact(previous, current, self.surface, .05), (300, 200, 2800))

    def test_dry_ground_parallel_flight_and_small_bobbing_do_not_splash(self):
        for a, b in ((self.point(1100, 200), self.point(1300, 0)),
                     (self.point(0, 200), self.point(100, 190)),
                     (self.point(200, 102), self.point(200, 98))):
            self.assertIsNone(self.contact(a, b, self.surface, .05))

    def test_ski_landing_registers_above_surface_and_takeoff_does_not(self):
        self.surface.ski = True
        a, b = self.point(200, 150), self.point(300, 112)
        self.assertEqual(self.contact(a, b, self.surface, .05), (300, 200, 760))
        self.assertIsNone(self.contact(b, a, self.surface, .05))
