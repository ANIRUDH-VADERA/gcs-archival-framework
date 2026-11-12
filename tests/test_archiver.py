import os
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta

from gcs_archiver import runner
from gcs_archiver.config import ArchiveConfig
from gcs_archiver.cost import GB, estimate, human_bytes
from gcs_archiver.fakes import FakeTransferClient
from gcs_archiver.ledger import Ledger
from gcs_archiver.models import Batch, ObjectInfo
from gcs_archiver.planner import batch_prefix, cutoff_for, eligible, plan_batches
from gcs_archiver.storage import InMemoryBackend
from gcs_archiver.transfer import build_job_spec

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def obj(name, days_old, size=GB, cls="NEARLINE"):
    return ObjectInfo(name, size, NOW - timedelta(days=days_old), cls)


def cfg(**kw):
    base = {"project_id": "p", "source_bucket": "src", "archive_bucket": "arc", "prefixes": ["t/"], "batch_depth": 2}
    return ArchiveConfig(**{**base, **kw})


class PlannerTests(unittest.TestCase):
    def test_only_old_objects_not_already_archived_are_eligible(self):
        objs = [obj("t/a/1", 400), obj("t/a/2", 10), obj("t/a/3", 500, cls="ARCHIVE")]
        chosen = eligible(objs, cutoff_for(395, NOW), "ARCHIVE")
        self.assertEqual([o.name for o in chosen], ["t/a/1"])

    def test_batch_prefix_depth(self):
        self.assertEqual(batch_prefix("tables/x/dt=1/p.parquet", 2), "tables/x/")
        self.assertEqual(batch_prefix("tables/x/dt=1/p.parquet", 0), "")
        self.assertEqual(batch_prefix("root.txt", 2), "")

    def test_batches_split_on_size_and_count(self):
        objs = [obj(f"t/a/{i}", 400, size=3 * GB) for i in range(5)]
        batches = plan_batches(objs, depth=2, max_objects=10, max_bytes=7 * GB)
        self.assertEqual([b.object_count for b in batches], [2, 2, 1])
        self.assertTrue(all(b.prefix == "t/a/" for b in batches))

    def test_single_oversized_object_still_gets_a_batch(self):
        batches = plan_batches([obj("t/a/huge", 400, size=100 * GB)], depth=2, max_objects=10, max_bytes=GB)
        self.assertEqual(len(batches), 1)


class CostTests(unittest.TestCase):
    def test_savings_from_nearline_to_archive(self):
        c = estimate({"NEARLINE": 1000 * GB}, "ARCHIVE", {"STANDARD": 0.02, "NEARLINE": 0.01, "ARCHIVE": 0.0012})
        self.assertAlmostEqual(c.monthly_savings_usd, 8.8)
        self.assertAlmostEqual(c.annual_savings_usd, 105.6)

    def test_human_bytes(self):
        self.assertEqual(human_bytes(1536), "1.5 KB")
        self.assertEqual(human_bytes(104 * 1024**4), "104.0 TB")


class ConfigTests(unittest.TestCase):
    def test_rejects_dangerous_settings(self):
        with self.assertRaises(ValueError):
            cfg(min_age_days=7)
        with self.assertRaises(ValueError):
            cfg(archive_bucket="src")


class TransferSpecTests(unittest.TestCase):
    def test_spec_scopes_prefix_and_age(self):
        spec = build_job_spec(Batch("t/a/"), cfg(min_age_days=395), today=date(2026, 6, 1))
        cond = spec["transferSpec"]["objectConditions"]
        self.assertEqual(cond["includePrefixes"], ["t/a/"])
        self.assertEqual(cond["minTimeElapsedSinceLastModification"], f"{395 * 86400}s")
        self.assertFalse(spec["transferSpec"]["transferOptions"]["deleteObjectsFromSourceAfterTransfer"])
        self.assertEqual(spec["schedule"]["scheduleStartDate"], spec["schedule"]["scheduleEndDate"])


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        now = datetime.now(UTC)
        old = [ObjectInfo(f"t/{t}/dt={d}/p.parquet", GB, now - timedelta(days=400 + d), "NEARLINE")
               for t in ("a", "b", "c") for d in range(3)]
        fresh = [ObjectInfo("t/a/dt=new/p.parquet", GB, now - timedelta(days=5), "STANDARD")]
        self.storage = InMemoryBackend({"src": old + fresh})
        self.cfg = cfg(delete_source_after_transfer=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(os.path.join(self.tmp.name, "l.sqlite"))

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_full_flow_with_failure_and_resume(self):
        plan = runner.make_plan(self.cfg, self.storage)
        self.assertEqual(len(plan.batches), 3)
        self.assertEqual(sum(b.object_count for b in plan.batches), 9)

        fake = FakeTransferClient(self.storage, fail_prefixes={"t/b/"})
        self.assertEqual(runner.submit(plan, self.cfg, fake, self.ledger), 3)
        self.assertEqual(runner.refresh(fake, self.ledger), {"SUCCESS": 2, "FAILED": 1})
        self.assertEqual(runner.verify(plan, self.cfg, self.storage, self.ledger), [])

        # The fresh object stays put; archived ones moved and were deleted from the source.
        self.assertIn("t/a/dt=new/p.parquet", self.storage.buckets["src"])
        self.assertEqual(self.storage.buckets["arc"]["t/a/dt=0/p.parquet"].storage_class, "ARCHIVE")

        # Re-running only retries the failed batch.
        fake.fail_prefixes.clear()
        self.assertEqual(runner.submit(plan, self.cfg, fake, self.ledger), 1)
        runner.refresh(fake, self.ledger)
        runner.verify(plan, self.cfg, self.storage, self.ledger)
        self.assertEqual({r["status"] for r in self.ledger.all()}, {"VERIFIED"})

    def test_verify_flags_missing_objects(self):
        plan = runner.make_plan(self.cfg, self.storage)
        fake = FakeTransferClient(self.storage)
        runner.submit(plan, self.cfg, fake, self.ledger)
        runner.refresh(fake, self.ledger)
        del self.storage.buckets["arc"]["t/c/dt=1/p.parquet"]
        problems = runner.verify(plan, self.cfg, self.storage, self.ledger)
        self.assertEqual(len(problems), 1)
        self.assertIn("t/c/", problems[0])


if __name__ == "__main__":
    unittest.main()
