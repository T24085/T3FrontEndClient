"""Ensure source map choices retain the full verified player-package catalog."""
from pathlib import Path
import unittest
from community_maps import BY_ID

class CatalogDefinitionTests(unittest.TestCase):
 def test_full_catalog_and_native_namespace_are_retained(self):
  native={'Torment','DangerousCrossing','Drydock','Katabatic','Wavemist','Hollow','Raindance','Moonrise'}
  self.assertEqual(len(BY_ID),22)
  self.assertEqual({n for n,d in BY_ID.items()if d.native},native)
  for name in native:self.assertTrue(BY_ID[name].package.startswith('/Game/Maps/Active/'))
 def test_source_and_packaged_helper_definitions_agree(self):
  root=Path(__file__).resolve().parent
  path=root/'lib/community_maps.py'
  if not path.exists():path=root/'host/lib/community_maps.py'
  self.assertEqual((root/'community_maps.py').read_text(),path.read_text())

if __name__=='__main__':unittest.main()
