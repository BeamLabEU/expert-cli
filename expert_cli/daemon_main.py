"""Entry point for running the daemon as a subprocess."""

import argparse
import os
import sys

from expert_cli.daemon import run_daemon


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Project root path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    os.chdir(args.root)
    run_daemon(args.root, verbose=args.verbose)


if __name__ == "__main__":
    main()
