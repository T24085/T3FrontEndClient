"""Validate that community radar uses one spatial scale at native zoom."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = (Path(__file__).with_name("lua") / "client.lua").read_text(encoding="utf-8")


class RadarProjectionTest(unittest.TestCase):
    def fixture(self):
        start = SOURCE.index("local radar_playable_width=")
        end = SOURCE.index("-- Production network-client radar binding.", start)
        return LuaRuntime().execute(SOURCE[start:end] + """
            local settings={MapSize=1075200}
            local widget={CachedZoom=1,TargetZoom=1}
            function widget:UpdateSublevel()
                if self.fail then error('native projection failed') end
                self.CachedMapScale=1024/settings.MapSize
            end
            return {
                width=radar_projection_width,
                initialize=function(width)initialize_radar_projection(widget,settings,width)end,
                widget=widget,settings=settings,
            }
        """)

    def test_damnation_coverage_and_native_zoom(self):
        f = self.fixture()
        width = f.width("Damnation2026", f.settings.MapSize)
        self.assertEqual(width, 155000)
        self.assertGreater(width / 2, 70323.5)
        f.initialize(width)
        self.assertAlmostEqual(f.widget.CachedMapScale, 1024 / width)
        self.assertEqual((f.widget.CachedZoom, f.widget.TargetZoom), (1, 1))
        self.assertEqual(f.settings.MapSize, 1075200)

    def test_unknown_map_or_tighter_authored_size_uses_native_scale(self):
        f = self.fixture()
        self.assertEqual(f.width("Unlisted", 234000), 234000)
        self.assertEqual(f.width("Damnation2026", 150000), 150000)

    def test_native_projection_error_restores_authored_settings(self):
        f = self.fixture()
        f.widget.fail = True
        with self.assertRaisesRegex(Exception, "native projection failed"):
            f.initialize(155000)
        self.assertEqual(f.settings.MapSize, 1075200)

    def test_katabatic_t2_uses_community_radar_with_authored_settings(self):
        start = SOURCE.index("local function radar_descriptor(selected)")
        end = SOURCE.index("\nreturn function(env)", start)
        lua = LuaRuntime()
        descriptor_for = lua.execute(SOURCE[start:end] + "\nreturn radar_descriptor")
        selected = lua.table_from({
            "native": True,
            "name": "KatabaticT22026",
            "package": "/Game/Maps/Community/KatabaticT2/Arena_KatabaticT2_2026_P",
        })
        descriptor = descriptor_for(selected)
        self.assertTrue(descriptor.native)
        self.assertEqual(descriptor.assembly_asset,
                         "/Game/Community/KatabaticT2/Edition2026/SM_Structures2026.SM_Structures2026")
        self.assertIsNone(selected.assembly_asset)
        selected.package = "/Game/Maps/Active/Katabatic/Arena_Katabatic_P"
        self.assertIsNone(descriptor_for(selected))
