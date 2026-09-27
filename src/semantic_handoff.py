from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from src.state_safety import atomic_replace_bytes, sha256_file


SemanticFlow = Literal[
    "jd-analysis",
    "capability-analysis",
    "capability-knowledge-research",
    "job-learning-roadmap",
]

VALID_FLOWS = {
    "jd-analysis",
    "capability-analysis",
    "capability-knowledge-research",
    "job-learning-roadmap",
}


_PREPARED_GUIDANCE = {
    "jd-analysis": (
        "JD Analysis request is prepared. Analysis has not run yet. "
        "Next: run the `jd-analysis` Agent Skill. After it finishes, return to "
        "Market to view the new Market Signals."
    ),
    "capability-analysis": (
        "Capability Analysis request is prepared. The recommendation has not "
        "been generated yet. Next: run the `capability-analysis` Agent Skill. "
        "After it finishes, return to this Capability Inbox candidate to view "
        "the advice and continue with Add, Merge, or Skip."
    ),
    "capability-knowledge-research": (
        "Knowledge Research request is prepared. Research has not run yet. "
        "Next: run the `capability-knowledge-research` Agent Skill. After it "
        "finishes, return to Capability Detail to view the Knowledge."
    ),
    "job-learning-roadmap": (
        "Roadmap Generation request is prepared. The Roadmap has not been "
        "generated yet. Next: run the `job-learning-roadmap` Agent Skill. After "
        "it finishes, return to Roadmap to view the latest version."
    ),
}

_BATCH_KNOWLEDGE_GUIDANCE = (
    "Knowledge Research batch request is prepared. Research has not run for this "
    "batch yet. Next: run the `capability-knowledge-research` Agent Skill. One "
    "Skill run processes one batch. After it finishes, return to Capabilities "
    "to review progress; if items remain, run the same Skill again."
)

_BATCH_CAPABILITY_GUIDANCE = (
    "Capability Analysis batch request is prepared. Recommendations have not "
    "been generated for this batch yet. Next: run the `capability-analysis` "
    "Agent Skill. One Skill run processes one batch. After it finishes, return to "
    "Capability Inbox to review advice and make each Add, Merge, or Skip "
    "decision; if candidates remain, run the same Skill again."
)


def prepared_handoff_message(
    flow: SemanticFlow, *, batch: bool = False
) -> str:
    if flow not in VALID_FLOWS:
        raise ValueError("Unknown semantic handoff flow")
    if flow == "capability-analysis" and batch:
        return _BATCH_CAPABILITY_GUIDANCE
    if flow == "capability-knowledge-research" and batch:
        return _BATCH_KNOWLEDGE_GUIDANCE
    return _PREPARED_GUIDANCE[flow]


@dataclass(frozen=True)
class HandoffStatus:
    state: str
    message: str


class SemanticHandoffStore:
    """Run-scoped files shared by the local UI and an explicitly invoked Agent Skill."""

    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root.resolve() / "handoffs"

    def _flow_root(self, flow: SemanticFlow) -> Path:
        if flow not in VALID_FLOWS:
            raise ValueError("Unknown semantic handoff flow")
        return self.root / flow

    def request_path(self, flow: SemanticFlow) -> Path:
        return self._flow_root(flow) / "request.json"

    def result_path(self, flow: SemanticFlow) -> Path:
        return self._flow_root(flow) / "result.json"

    def draft_path(self, flow: SemanticFlow) -> Path:
        return self._flow_root(flow) / "draft.json"

    def status_path(self, flow: SemanticFlow) -> Path:
        return self._flow_root(flow) / "status.json"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        atomic_replace_bytes(
            path,
            encoded,
            expected_sha256=sha256_file(path),
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, object] | None:
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Semantic handoff artifact is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError("Semantic handoff artifact must be an object")
        return value

    def prepare(
        self,
        flow: SemanticFlow,
        *,
        input_payload: dict[str, object],
        context: dict[str, object],
    ) -> str:
        request_id = str(uuid4())
        request = {
            "handoff_version": "1.0",
            "flow": flow,
            "request_id": request_id,
            "prepared_at": datetime.now().astimezone().isoformat(),
            "context": context,
            "input": input_payload,
        }
        self._write_json(self.request_path(flow), request)
        self._write_json(
            self.status_path(flow),
            {
                "request_id": request_id,
                "state": "prepared",
                "message": prepared_handoff_message(
                    flow, batch="batch_manifest_id" in context
                ),
            },
        )
        return request_id

    def load_request(self, flow: SemanticFlow) -> dict[str, object]:
        request = self._read_json(self.request_path(flow))
        if request is None:
            raise ValueError("No prepared semantic handoff request")
        if (
            request.get("handoff_version") != "1.0"
            or request.get("flow") != flow
            or not isinstance(request.get("request_id"), str)
            or not isinstance(request.get("context"), dict)
            or not isinstance(request.get("input"), dict)
        ):
            raise ValueError("Semantic handoff request is invalid")
        return request

    def save_result(
        self,
        flow: SemanticFlow,
        *,
        request_id: str,
        output: dict[str, object],
    ) -> None:
        request = self.load_request(flow)
        if request["request_id"] != request_id:
            raise ValueError("Semantic handoff result is stale")
        self._write_json(
            self.result_path(flow),
            {"request_id": request_id, "output": output},
        )

    def load_current_output(self, flow: SemanticFlow) -> dict[str, object] | None:
        request = self.load_request(flow)
        result = self._read_json(self.result_path(flow))
        if result is None or result.get("request_id") != request["request_id"]:
            return None
        output = result.get("output")
        if not isinstance(output, dict):
            raise ValueError("Semantic handoff result is invalid")
        return output

    def output_for(
        self,
        flow: SemanticFlow,
        *,
        context: dict[str, object],
    ) -> dict[str, object] | None:
        request = self.load_request(flow)
        if request["context"] != context:
            return None
        return self.load_current_output(flow)

    def set_status(
        self,
        flow: SemanticFlow,
        *,
        request_id: str,
        state: Literal["completed", "error"],
        message: str,
    ) -> None:
        request = self.load_request(flow)
        if request["request_id"] != request_id:
            raise ValueError("Semantic handoff status is stale")
        self._write_json(
            self.status_path(flow),
            {"request_id": request_id, "state": state, "message": message},
        )

    def status_for(
        self,
        flow: SemanticFlow,
        *,
        context: dict[str, object],
    ) -> HandoffStatus | None:
        if not self.request_path(flow).is_file():
            return None
        try:
            request = self.load_request(flow)
            if request["context"] != context:
                return None
            status = self._read_json(self.status_path(flow))
        except ValueError:
            return HandoffStatus("error", "请求状态不可用，请重新运行。")
        if status is None or status.get("request_id") != request["request_id"]:
            return None
        state, message = status.get("state"), status.get("message")
        if not isinstance(state, str) or not isinstance(message, str):
            return HandoffStatus("error", "请求状态不可用，请重新运行。")
        return HandoffStatus(state, message)
