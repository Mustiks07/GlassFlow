import argparse
from pathlib import Path

from glassflow.modules.platform.reports import build_reports

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build only from actual run and labor evidence; no research answer fallback"
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=["all", "examples", "economics"], default="all")
    parser.add_argument(
        "--font", type=Path, required=True, help="Licensed Cyrillic TrueType font; embedded in PDF"
    )
    args = parser.parse_args()
    result = build_reports(args.evidence, args.output, args.font, only=args.only)
    print(result["status"])
