"""Real package/staging cache boundaries across independent digest owners."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bulk_verification_receipts import BulkReceipts, MAX_AGE
from verified_file_cache import VerifiedFileCache, identity
import verified_file_cache


class BulkReceiptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.package, self.workspace = self.root/'package', self.root/'workspace'
        self.package.mkdir(); self.workspace.mkdir()
        self.asset = self.package/'content/Community/Test/terrain.ubulk'
        self.asset.parent.mkdir(parents=True); self.asset.write_bytes(b'verified asset')
        self.stamp = [100000.0]
    def tearDown(self): self.temp.cleanup()
    def store(self): return BulkReceipts(self.package, self.workspace, clock=lambda:self.stamp[0])
    def cache(self):
        cache = VerifiedFileCache(); cache.receipts = self.store(); return cache
    def test_second_owner_reuses_bytes_only_while_identity_and_age_match(self):
        first = self.cache(); expected = first.digest(self.asset); first.receipts.flush()
        second = self.cache(); self.assertEqual(second.digest(self.asset), expected)
        self.assertEqual(second.snapshot()['bytes_hashed'], 0)
        self.assertEqual(second.snapshot()['retained_bulk_hits'], 1)
        self.asset.write_bytes(b'changed asset payload')
        third = self.cache(); self.assertNotEqual(third.digest(self.asset), expected)
        self.assertEqual(third.snapshot()['retained_bulk_hits'], 0)
        self.assertEqual(third.snapshot()['bytes_hashed'], self.asset.stat().st_size)
    def test_force_expiry_and_future_receipts_require_fresh_hashes(self):
        first = self.cache(); first.digest(self.asset); first.receipts.flush()
        for stamp, force in ((100000, True), (100000+MAX_AGE, False), (99999, False)):
            with self.subTest(stamp=stamp, force=force):
                self.stamp[0] = stamp; cache = self.cache(); cache.digest(self.asset, force=force)
                self.assertEqual(cache.snapshot()['retained_bulk_hits'], 0)
                self.assertEqual(cache.snapshot()['bytes_hashed'], self.asset.stat().st_size)
    def test_runtime_and_executable_are_always_fresh_in_new_owner(self):
        for name in ('runtime/ue4ss.dll', 'client.py', 'package-manifest.json', 'content/test.dll'):
            path=self.package/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'fresh critical bytes')
            first=self.cache(); first.digest(path); first.receipts.flush()
            second=self.cache(); second.digest(path)
            self.assertEqual(second.snapshot()['bytes_hashed'],path.stat().st_size)
    def test_shared_asset_receipt_and_current_expected_hash_still_belong_to_consumer(self):
        expected=hashlib.sha256(self.asset.read_bytes()).hexdigest()
        path=self.workspace/'asset-cache'/expected[:2]/(expected+'.asset')
        path.parent.mkdir(parents=True); path.write_bytes(self.asset.read_bytes())
        first=self.cache(); self.assertEqual(first.digest(path),expected); first.receipts.flush()
        second=self.cache(); self.assertEqual(second.digest(path),expected)
        self.assertEqual(second.snapshot()['bytes_hashed'],0)
        # A current manifest requesting another digest does not become aligned.
        self.assertNotEqual(second.digest(path),'0'*64)
    def test_malformed_or_unknown_receipt_is_retained_and_hashing_continues(self):
        store=self.store(); store.path.write_text('{invalid')
        cache=self.cache(); cache.digest(self.asset); cache.receipts.flush()
        self.assertEqual(store.path.read_text(),'{invalid')
        self.assertEqual(cache.snapshot()['bytes_hashed'],self.asset.stat().st_size)
    def test_changed_cached_identity_is_rejected_even_when_original_source_matches(self):
        first=self.cache(); first.digest(self.asset); first.receipts.flush()
        data=json.loads(first.receipts.path.read_bytes())
        data['records'][str(self.asset)]['identity'][1]+=1
        first.receipts.path.write_text(json.dumps(data))
        cache=self.cache(); cache.digest(self.asset)
        self.assertEqual(cache.snapshot()['retained_bulk_hits'],0)
    def test_receipt_hits_preserve_process_cache_entry_bound(self):
        first=self.cache()
        files=[self.asset.with_name(str(i)+'.ubulk')for i in range(3)]
        for path in files:path.write_bytes(b'asset');first.digest(path)
        first.receipts.flush()
        second=VerifiedFileCache(max_entries=1);second.receipts=self.store()
        for path in files:second.digest(path)
        self.assertEqual(second.snapshot()['entries'],1)

    def test_actual_package_verifier_compares_current_manifest_after_receipt_hit(self):
        manifest=self.package/'package-manifest.json'
        row={'path':self.asset.relative_to(self.package).as_posix(),'bytes':self.asset.stat().st_size,
             'sha256':hashlib.sha256(self.asset.read_bytes()).hexdigest()}
        manifest.write_text(json.dumps({'files':[row]}))
        first=self.cache()
        with patch.object(verified_file_cache,'_PROCESS_CACHE',first):verified_file_cache.verify_package(self.package)
        first.receipts.flush()
        row['sha256']='0'*64;manifest.write_text(json.dumps({'files':[row]}))
        second=self.cache()
        with patch.object(verified_file_cache,'_PROCESS_CACHE',second),self.assertRaisesRegex(ValueError,'failed verification'):
            verified_file_cache.verify_package(self.package)
        self.assertEqual(second.snapshot()['retained_bulk_hits'],1)

    def test_verified_work_is_durable_before_preparer_exit(self):
        first=self.cache()
        # A long preparation crosses a checkpoint before it can finish staging.
        self.stamp[0]+=16
        expected=first.digest(self.asset)
        second=self.cache()
        self.assertEqual(second.digest(self.asset),expected)
        self.assertEqual(second.snapshot()['bytes_hashed'],0)
        self.assertEqual(second.snapshot()['retained_bulk_hits'],1)

    def test_failed_optional_checkpoint_does_not_break_verification(self):
        first=self.cache();self.stamp[0]+=16
        with patch.object(first.receipts,'flush',side_effect=OSError('unwritable cache')):
            self.assertEqual(first.digest(self.asset),hashlib.sha256(self.asset.read_bytes()).hexdigest())
        self.assertFalse(first.receipts.writable)


if __name__=='__main__': unittest.main()
