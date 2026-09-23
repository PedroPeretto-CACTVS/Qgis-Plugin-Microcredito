"""Package console entry used by the template script name."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    from cli.admin import main as admin_main

    return admin_main(argv)
