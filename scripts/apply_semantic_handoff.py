from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from src.semantic_handoff import SemanticFlow, SemanticHandoffStore, VALID_FLOWS


PUBLIC_FAILURES = {
    "jd-analysis": (
        "JD Analysis result could not be applied. Run `jd-analysis` again, "
        "then return to Market."
    ),
    "capability-analysis": (
        "Capability Analysis result could not be applied. Run "
        "`capability-analysis` again, then return to Capability Inbox."
    ),
    "capability-knowledge-research": (
        "Knowledge 研究结果未通过校验，已有内容未受影响。Run "
        "`capability-knowledge-research` again, then return to Capability Detail "
        "or Capabilities."
    ),
    "job-learning-roadmap": (
        "Roadmap Generation result could not be applied; the current Roadmap is "
        "unchanged. Run `job-learning-roadmap` again, then return to Roadmap."
    ),
}


def apply(flow: SemanticFlow, storage_root: Path) -> str:
    handoffs = SemanticHandoffStore(storage_root)
    request = handoffs.load_request(flow)
    request_id = str(request["request_id"])
    context = request["context"]
    if not isinstance(context, dict):
        raise ValueError("Semantic handoff context is invalid")
    try:
        output = json.loads(handoffs.draft_path(flow).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Semantic handoff draft is invalid") from exc
    if not isinstance(output, dict):
        raise ValueError("Semantic handoff draft must be a JSON object")
    handoffs.save_result(flow, request_id=request_id, output=output)
    payload = json.dumps(output, ensure_ascii=False)

    if flow == "jd-analysis":
        message = MarketOperations(storage_root).import_analyses(
            str(context["role_id"]),
            payload,
            expected_sha256=str(context["expected_sha256"]),
        )
    elif flow == "capability-analysis":
        operations = CapabilityOperations(storage_root)
        input_payload = request["input"]
        if not isinstance(input_payload, dict):
            raise ValueError("Semantic handoff Capability Analysis input is invalid")
        if input_payload.get("mode") == "batch":
            message = operations.save_capability_analysis_batch_results(
                context, input_payload, output
            )
        else:
            operations.save_recommendation_result(
                str(context["role_id"]),
                str(context["candidate_fingerprint"]),
                payload,
            )
            message = "Capability recommendation generated."
    elif flow == "capability-knowledge-research":
        operations = CapabilityOperations(storage_root)
        input_payload = request["input"]
        if not isinstance(input_payload, dict):
            raise ValueError("Semantic handoff Knowledge input is invalid")
        if input_payload.get("mode") == "batch":
            message = operations.save_knowledge_batch_results(
                context, input_payload, output
            )
        else:
            expected = context.get("expected_knowledge_sha256")
            message = operations.save_knowledge_result(
                str(context["role_id"]),
                str(context["capability_id"]),
                payload,
                expected_knowledge_sha256=(
                    str(expected) if expected is not None else None
                ),
            )
    else:
        message = RoadmapOperations(storage_root).save_result(
            str(context["role_id"]), payload
        )
    handoffs.set_status(
        flow,
        request_id=request_id,
        state="completed",
        message=message,
    )
    if flow == "capability-knowledge-research":
        CapabilityOperations(storage_root).prepare_next_knowledge_batch_request()
    if flow == "capability-analysis":
        CapabilityOperations(
            storage_root
        ).prepare_next_capability_analysis_batch_request()
    return message


def apply_with_status(flow: SemanticFlow, storage_root: Path) -> str:
    handoffs = SemanticHandoffStore(storage_root)
    try:
        return apply(flow, storage_root)
    except (ApplicationError, KeyError, OSError, TypeError, ValueError):
        message = PUBLIC_FAILURES[flow]
        try:
            request = handoffs.load_request(flow)
            handoffs.set_status(
                flow,
                request_id=str(request["request_id"]),
                state="error",
                message=message,
            )
        except (KeyError, OSError, TypeError, ValueError):
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply one system-managed semantic handoff result."
    )
    parser.add_argument("flow", choices=sorted(VALID_FLOWS))
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=PROJECT_ROOT / "state",
    )
    args = parser.parse_args()
    flow: SemanticFlow = args.flow
    try:
        print(apply_with_status(flow, args.storage_root.resolve()))
        return 0
    except (ApplicationError, KeyError, OSError, TypeError, ValueError) as exc:
        message = PUBLIC_FAILURES[flow]
        print(f"{message} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
