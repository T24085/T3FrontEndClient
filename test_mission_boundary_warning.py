from pathlib import Path
import re
import unittest

from lupa.lua54 import LuaRuntime


class BoundaryWarningPackagingTest(unittest.TestCase):
    def test_signed_client_embeds_the_offline_warning_module(self):
        root = Path(__file__).parent
        source = (root / "lua/client.lua").read_text(encoding="utf-8")
        shared = (root / "runtime-fixes/mission_boundary_warning.lua").read_text(encoding="utf-8").strip()
        block = re.search(
            r"-- BEGIN SHARED mission_boundary_warning.lua\n(.*?)\n-- END SHARED mission_boundary_warning.lua",
            source, flags=re.DOTALL,
        )
        self.assertIsNotNone(block)
        self.assertEqual(block[1], shared)
        self.assertIn("warn_mission_boundary(pc,ps)", source)
        # client_entry turns warnings off for --no-boundary-warning by flipping this one line (#96).
        self.assertEqual(source.count("local missionBoundaryWarnings=true" + chr(10)), 1)
        self.assertIn("if missionBoundaryWarnings then warn_mission_boundary(pc,ps) end", source)
        entry = (root / "client_entry.py").read_text(encoding="utf-8")
        self.assertIn("'--no-boundary-warning'", entry)
        self.assertIn("local missionBoundaryWarnings=false", entry)
        LuaRuntime().compile(re.sub(r"@@[A-Z0-9_]+@@", "nil", source))
