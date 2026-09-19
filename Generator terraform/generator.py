"""Render an educational Terraform project. Never initialize, apply or deploy it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator_common import load_plan, manifest, validate_plan, write_bundle  # noqa: E402
from json_io import dumps_json  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent / "templates"


def generate(plan: dict, output: Path) -> None:
    plan = validate_plan(plan)
    files = {p.name: p.read_text(encoding="utf-8") for p in TEMPLATES.glob("*.tf")}
    files["lab.auto.tfvars.json"] = dumps_json(plan["cloud_plan"]["settings"], indent=2) + "\n"
    files["manifest.json"] = manifest(plan, "terraform")
    files["arch.json"] = dumps_json(plan, indent=2) + "\n"
    files["README.md"] = (Path(__file__).parent / "PROJECT_README.md").read_text(encoding="utf-8")
    files[".gitignore"] = ".terraform/\n*.tfstate*\n*.tfplan\n*.tfvars\ninventory.json\n"
    write_bundle(output, files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Concrete RAG arch.json plan")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    args = parser.parse_args(argv)
    try:
        generate(load_plan(args.input), args.output)
        print(dumps_json({"generated": str(args.output), "deployed": False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(dumps_json({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
