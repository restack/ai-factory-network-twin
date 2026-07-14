"""Lazy pybatfish boundary returning plain answer records."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from aftwin.errors import AssuranceError

type AnswerRows = tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class BatfishAnswers:
    """Plain records for every admitted question, one dict per answer row."""

    parse_files: AnswerRows
    parse_issues: AnswerRows
    session_compatibility: AnswerRows
    session_status: AnswerRows
    loops: AnswerRows
    bgp_routes: AnswerRows


def collect_batfish_answers(
    snapshot_dir: Path,
    *,
    host: str,
    network: str,
    snapshot: str,
) -> BatfishAnswers:
    """Initialize one snapshot and collect the admitted question answers."""
    try:
        # The optional dependency stays behind this call so the baseline
        # compile and verify workflow never imports it.
        module = import_module("pybatfish.client.session")
    except ImportError as error:
        raise AssuranceError(
            "pybatfish is not installed; install the 'assure' dependency group "
            "(uv sync --group assure)",
        ) from error

    try:
        session: Any = module.Session(host=host)
        session.set_network(network)
        session.init_snapshot(str(snapshot_dir), name=snapshot, overwrite=True)

        def rows(question: Any) -> AnswerRows:
            records = cast(
                "list[dict[str, Any]]",
                question.answer().frame().to_dict(orient="records"),
            )
            return tuple(dict(record) for record in records)

        return BatfishAnswers(
            parse_files=rows(session.q.fileParseStatus()),
            parse_issues=rows(session.q.initIssues()),
            session_compatibility=rows(session.q.bgpSessionCompatibility()),
            session_status=rows(session.q.bgpSessionStatus()),
            loops=rows(session.q.detectLoops()),
            bgp_routes=rows(session.q.routes(protocols="bgp")),
        )
    except AssuranceError:
        raise
    except Exception as error:
        raise AssuranceError(
            f"Batfish query failed: {type(error).__name__}: {error}",
            details={"host": host, "network": network, "snapshot": snapshot},
        ) from error
