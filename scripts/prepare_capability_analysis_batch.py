from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from application.capabilities import CapabilityOperations
from src.semantic_handoff import SemanticHandoffStore


def prepare(storage_root: Path) -> str:
    handoffs = SemanticHandoffStore(storage_root)
    try:
        request = handoffs.load_request("capability-analysis")
    except ValueError:
        request = None
    if request is not None:
        input_payload = request.get("input")
        if isinstance(input_payload, dict) and input_payload.get("mode") != "batch":
            return "SINGLE_CAPABILITY_ANALYSIS_REQUEST_READY"
    message = CapabilityOperations(
        storage_root
    ).prepare_next_capability_analysis_batch_request()
    return message or "NO_PENDING_CAPABILITY_ANALYSIS_BATCH"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recheck and prepare at most one Capability Analysis batch."
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=PROJECT_ROOT / "state",
    )
    args = parser.parse_args()
    print(prepare(args.storage_root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
