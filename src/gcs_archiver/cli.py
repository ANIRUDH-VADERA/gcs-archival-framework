from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import runner
from .config import ArchiveConfig, load_config
from .cost import human_bytes
from .fakes import FakeTransferClient, sample_bucket
from .ledger import Ledger
from .storage import GcsBackend, InMemoryBackend


def print_plan(plan: runner.Plan, cfg: ArchiveConfig, show: int = 15) -> None:
    print(f"Source gs://{cfg.source_bucket} -> archive gs://{cfg.archive_bucket} ({cfg.target_storage_class})")
    print(f"Objects older than {cfg.min_age_days} days, grouped at prefix depth {cfg.batch_depth}\n")
    print(f"{'batch':<52} {'objects':>9} {'size':>12}")
    for batch, seq in plan.numbered()[:show]:
        print(f"{(batch.key + (f' #{seq}' if seq else ''))[:52]:<52} {batch.object_count:>9,} {human_bytes(batch.total_bytes):>12}")
    if len(plan.batches) > show:
        print(f"... {len(plan.batches) - show} more batches")
    c = plan.cost
    print(f"\n{len(plan.batches)} jobs, {sum(b.object_count for b in plan.batches):,} objects, {human_bytes(c.bytes_moved)}")
    print(f"Storage cost: ${c.current_monthly_usd:,.2f}/month now -> ${c.archived_monthly_usd:,.2f}/month archived")
    print(f"Estimated savings: ${c.monthly_savings_usd:,.2f}/month, ${c.annual_savings_usd:,.2f}/year (storage only)")


def print_ledger(ledger: Ledger) -> None:
    rows = ledger.all()
    print(f"\n{'batch':<44} {'job':<18} {'status':<10} {'objects':>8}")
    for r in rows:
        label = r["batch_key"] + (f" #{r['seq']}" if r["seq"] else "")
        print(f"{label[:44]:<44} {r['job_name'] or '-':<18} {r['status']:<10} {r['object_count']:>8,}")


def cmd_demo(args: argparse.Namespace) -> int:
    storage = InMemoryBackend({"ledger-exports": sample_bucket()})
    cfg = ArchiveConfig(project_id="demo", source_bucket="ledger-exports", archive_bucket="ledger-archive",
                        prefixes=["tables/"], batch_depth=2, delete_source_after_transfer=True)
    plan = runner.make_plan(cfg, storage)
    print_plan(plan, cfg)
    fake = FakeTransferClient(storage, fail_prefixes={"tables/postings/"})
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(str(Path(tmp) / "ledger.sqlite"))
        print(f"\nSubmitted {runner.submit(plan, cfg, fake, ledger)} jobs (one is rigged to fail)")
        print("Status:", runner.refresh(fake, ledger))
        problems = runner.verify(plan, cfg, storage, ledger)
        print("Verification problems:", problems or "none")
        print_ledger(ledger)
        ledger.close()
    return 0


def _open(args: argparse.Namespace) -> tuple[ArchiveConfig, Ledger]:
    cfg = load_config(args.config)
    return cfg, Ledger(cfg.ledger_path)


def cmd_plan(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    print_plan(runner.make_plan(cfg, GcsBackend(cfg.project_id)), cfg)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .transfer import StsTransferClient  # noqa: PLC0415 - needs the gcp extra

    cfg, ledger = _open(args)
    plan = runner.make_plan(cfg, GcsBackend(cfg.project_id))
    print_plan(plan, cfg)
    if not args.execute:
        print("\nDry run. Re-run with --execute to create transfer jobs.")
        return 0
    n = runner.submit(plan, cfg, StsTransferClient(cfg.project_id), ledger, limit=args.limit)
    print(f"\nSubmitted {n} transfer jobs. Track them with: gcs-archiver status --config {args.config}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .transfer import StsTransferClient  # noqa: PLC0415

    cfg, ledger = _open(args)
    print(runner.refresh(StsTransferClient(cfg.project_id), ledger))
    print_ledger(ledger)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    cfg, ledger = _open(args)
    storage = GcsBackend(cfg.project_id)
    problems = runner.verify(runner.make_plan(cfg, storage), cfg, storage, ledger)
    for p in problems:
        print("MISMATCH", p)
    print("All successful batches verified." if not problems else f"{len(problems)} batches need attention.")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gcs-archiver", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run the full flow against an in-memory bucket").set_defaults(fn=cmd_demo)
    for name, fn, help_ in [("plan", cmd_plan, "list batches and estimated savings"),
                            ("run", cmd_run, "create transfer jobs (dry run unless --execute)"),
                            ("status", cmd_status, "poll job status into the ledger"),
                            ("verify", cmd_verify, "check archived objects match the plan")]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--config", required=True)
        sp.set_defaults(fn=fn)
        if name == "run":
            sp.add_argument("--execute", action="store_true", help="actually create jobs")
            sp.add_argument("--limit", type=int, help="submit at most N jobs (roll out in phases)")
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
