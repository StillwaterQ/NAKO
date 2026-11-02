"""Command-line interface for benchmark generation."""

import argparse
import json
from pathlib import Path

from .api import generate


def main():
    parser = argparse.ArgumentParser(description="Generate NAKO circuits and reference schedules.")
    parser.add_argument("config", type=Path, help="JSON generation parameters")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--count", type=int, default=1, help="Number of variants")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        targets = [args.output / f"{i:03d}" for i in range(args.count)]
        if any(path.exists() for path in targets):
            raise FileExistsError("A requested output directory already exists.")
        benchmarks = generate(**config, count=args.count)
        for benchmark, directory in zip(benchmarks, targets):
            benchmark.save(directory)
            print(directory)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
