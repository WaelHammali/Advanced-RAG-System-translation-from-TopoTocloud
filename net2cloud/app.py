"""Architecture JSON -> readiness check -> retrieval -> AWS JSON plan."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import RETRIEVAL_BACKEND, TOP_K
from .contracts import JSONObject, Retriever
from .corrections import apply_corrections
from .hosting import select_hosting
from .json_io import dumps_json, loads_json, write_json
from .planner import plan_with_rag
from .readiness import ArchitectureNotReady, check_readiness, require_ready
from .retriever import KnowledgeRetriever


def plan_architecture(
    architecture: JSONObject,
    *,
    client: Any = None,
    retriever: Retriever | None = None,
) -> JSONObject:
    """Block incomplete architectures, then translate without altering their fields."""
    require_ready(architecture)
    select_hosting(architecture)  # Stop unsupported profiles before model retrieval/downloads.
    original = deepcopy(architecture)
    engine = retriever if retriever is not None else KnowledgeRetriever()
    knowledge = engine.retrieve(deepcopy(original))
    plan = plan_with_rag(deepcopy(original), knowledge, client=client)
    return {
        **plan,
        "architecture": original,
        "knowledge": [
            {"rule_id": c["rule_id"], "source": c["source"], "heading": c["heading"]}
            for c in knowledge
        ],
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("plan", "Return a JSON plan from a prepared architecture JSON."),
        ("context", "Inspect retrieved records without calling the LLM."),
    ]:
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("--input", type=Path, required=True, help="Architecture .json file")
        command.add_argument("--output", type=Path, help="Optional JSON output file")
        command.add_argument(
            "--retrieval", choices=["hybrid", "lexical"], default=RETRIEVAL_BACKEND
        )
        command.add_argument(
            "--top-k",
            type=int,
            default=TOP_K,
            help="Optional ranked records, plus required topology rules",
        )
    check = subcommands.add_parser(
        "check", help="Check architecture readiness without retrieval or an LLM."
    )
    check.add_argument("--input", type=Path, required=True)
    check.add_argument("--output", type=Path, help="Optional readiness report JSON file")
    correct = subcommands.add_parser(
        "correct", help="Apply explicit correction tuples and revalidate."
    )
    correct.add_argument("--input", type=Path, required=True)
    correct.add_argument(
        "--corrections", type=Path, required=True, help="JSON list of [ID, path, value]"
    )
    correct.add_argument("--revision", required=True, help="Revision from the readiness report")
    correct.add_argument(
        "--output", type=Path, help="Optional corrected architecture and validation envelope"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI boundary: JSON results on stdout, runtime errors on stderr."""
    args = _argument_parser().parse_args(argv)
    try:
        if args.output and args.input.resolve() == args.output.resolve():
            raise ValueError("The output path must differ from the input architecture path.")
        architecture = loads_json(args.input.read_text(encoding="utf-8"))
        if args.command == "check":
            result = check_readiness(architecture)
        elif args.command == "correct":
            if args.output and args.output.resolve() == args.corrections.resolve():
                raise ValueError("The output path must differ from the corrections path.")
            result = apply_corrections(
                architecture,
                loads_json(args.corrections.read_text(encoding="utf-8")),
                expected_revision=args.revision,
            )
        else:
            require_ready(architecture)
            retriever = KnowledgeRetriever(backend=args.retrieval, top_k=args.top_k)
            if args.command == "context":
                result = {"knowledge": retriever.retrieve(architecture)}
            else:
                result = plan_architecture(architecture, retriever=retriever)
        serialized = dumps_json(result, indent=2) + "\n"
        if args.output:
            write_json(args.output, result, indent=2)
        print(serialized, end="")
        report = result.get("validation", result)
        return 2 if args.command in {"check", "correct"} and not report["ready"] else 0
    except ArchitectureNotReady as error:
        print(dumps_json(error.report), file=sys.stderr)
        return 2
    except Exception as error:
        # Catch at the CLI boundary only; the Python API preserves exceptions.
        print(dumps_json({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
