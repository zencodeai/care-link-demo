"""One exact evaluated function bundle; absence keeps actor service manual."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from care_link_core.assistance_broker import ReleasedFunction
from care_link_domain import ManualError
from care_link_inference import InferenceDenied, ModelManifest

Record = dict[str, object]


@dataclass(frozen=True)
class ReleaseBindings:
    manifest: ModelManifest | None
    functions: tuple[ReleasedFunction, ...]
    current: Callable[[], bool]
    # Part of trusted evaluated release custody, never a value supplied by the
    # browser/runtime/model. None preserves the legacy no-RAG release shape.
    knowledge_digest: str | None = None

    def knowledge_matches(self, actual_digest: str | None) -> bool:
        return self.knowledge_digest == actual_digest and (
            actual_digest is None or re.fullmatch(r"[0-9a-f]{64}", actual_digest) is not None
        )

    def release_for_knowledge(self, function: str, actual_digest: str | None) -> ReleasedFunction:
        if not self.knowledge_matches(actual_digest):
            raise ManualError("assistance.knowledge_release_unverified", 503)
        return self.release(function)

    def admitted_for_knowledge(self, function: str, actual_digest: str | None) -> bool:
        try:
            self.release_for_knowledge(function, actual_digest)
            return True
        except ManualError:
            return False

    def release(self, function: str) -> ReleasedFunction:
        if self.manifest is None or function != "worker_summary" or not self.current():
            raise ManualError("assistance.function_disabled", 503)
        try:
            evidence = self.manifest.admit(function, release_verified=self.current())
        except InferenceDenied as error:
            raise ManualError("assistance.function_disabled", 503) from error
        matches = [bundle for bundle in self.functions if bundle.function == function]
        if len(matches) != 1:
            raise ManualError("assistance.release_unverified", 503)
        bundle = matches[0]
        item: Record = {
            "source": bundle.instruction_source,
            "label": "approved_instruction",
            "text": bundle.instruction,
            "critical": True,
        }
        encoded = json.dumps(
            [item], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        if (
            bundle.model_digest != self.manifest.artifact_digest
            or bundle.prompt_digest != evidence.prompt_digest
            or bundle.prompt_digest != hashlib.sha256(encoded).hexdigest()
        ):
            raise ManualError("assistance.release_unverified", 503)
        return bundle

    def admitted(self, function: str) -> bool:
        try:
            self.release(function)
            return True
        except ManualError:
            return False

    def records(self) -> dict[str, Record]:
        result: dict[str, Record] = {}
        for candidate in self.functions:
            if self.admitted(candidate.function):
                bundle = self.release(candidate.function)
                result[bundle.function] = {
                    "instruction_source": bundle.instruction_source,
                    "instruction": bundle.instruction,
                    "model_digest": bundle.model_digest,
                    "prompt_digest": bundle.prompt_digest,
                }
        return result
