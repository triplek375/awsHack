"""Command-line entrypoint for the job data pipeline."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, load_config
from .pipeline import run


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="job_pipeline",
        description="Fetch, normalize, dedupe and store job postings.",
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Path to the YAML config file."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Read cached fixtures from samples/ instead of the network.",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        metavar="ROLE",
        help="Job role(s) to search, overriding search.keywords in config. "
        'Example: --keywords "data engineer" "cloud engineer"',
    )
    parser.add_argument(
        "--locations",
        nargs="+",
        metavar="LOC",
        help="Location(s) to search, overriding search.locations in config.",
    )
    storage = parser.add_mutually_exclusive_group()
    storage.add_argument(
        "--local", action="store_true", help="Force local storage mode."
    )
    storage.add_argument(
        "--s3", action="store_true", help="Force S3 storage mode."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging."
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    # CLI flags override config.
    if args.offline:
        cfg.offline = True
    if args.local:
        cfg.storage.mode = "local"
    if args.s3:
        cfg.storage.mode = "s3"
    if args.keywords:
        cfg.search.keywords = args.keywords
    if args.locations:
        cfg.search.locations = args.locations

    stats = run(cfg)
    print(
        f"Done. fetched={stats.fetched} new={stats.new} skipped={stats.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
