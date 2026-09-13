"""
Mei — entry point.

  py app.py              → launch TUI (default)
  py app.py --headless   → plain terminal fallback (for debugging TUI issues)
"""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Mei AI Agent")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without TUI — plain terminal mode for debugging",
    )
    args = parser.parse_args()

    if args.headless:
        from Mei._headless import run_headless
        run_headless()
    else:
        from Mei.cli.tui import MeiTUI
        MeiTUI().run()


if __name__ == "__main__":
    main()
