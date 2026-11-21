"""Reference-only LangGraph orchestration; Data owns progress and budgets.

There is no LangGraph checkpointer, store, model client or tool executor. Private
proposal bytes exist only in a closure for this execution and are erased when it
ends. A crash requires fresh actor resumption and cannot restore authority.
"""

# LangGraph 1.2.24 ships inline annotations without a py.typed marker. The narrow
# protocol below bounds its dynamic generic surface; domain types remain strict.
# pyright: reportMissingTypeStubs=false

import os
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import TYPE_CHECKING, Protocol, TypedDict, cast
from uuid import UUID, uuid4

from care_link_contracts import validate_contract
from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from .client import RuntimeClient


class WorkflowState(TypedDict):
    task_id: str
    task_revision: str
    step_id: str
    fence: str
    status: str


class _CompiledGraph(Protocol):
    def invoke(self, state: WorkflowState, *, config: Mapping[str, object]) -> object: ...


class _Graph(Protocol):
    def add_node(self, name: str, action: Callable[[WorkflowState], dict[str, str]]) -> object: ...
    def add_edge(self, source: str, target: str) -> object: ...
    def add_conditional_edges(
        self, source: str, path: Callable[[WorkflowState], str], path_map: Mapping[str, str]
    ) -> object: ...
    def compile(self) -> _CompiledGraph: ...


class _GraphFactory(Protocol):
    def __call__(self, state: type[WorkflowState]) -> _Graph: ...


def run_workflow(
    client: RuntimeClient,
    task_id: str,
    task_revision: str,
    *,
    initial_fence: str = "0",
    renew_interval: float = 5.0,
) -> Mapping[str, object]:
    if str(UUID(task_id)) != task_id or not 0 < renew_interval <= 5:
        raise ValueError("canonical task and bounded renewal interval required")
    if any(
        os.environ.get(key, "").lower() not in {"", "false", "0"}
        for key in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")
    ):
        raise ValueError("external graph tracing must be disabled")
    private: dict[str, Mapping[str, object]] = {}

    def lease(state: WorkflowState) -> dict[str, str]:
        receipt = client.lease(
            state["task_id"],
            {
                "expected_revision": state["task_revision"],
                "step_id": state["step_id"],
                "fence": state["fence"],
            },
        )
        validate_contract("LeaseView", dict(receipt))
        if receipt["task_id"] != task_id or receipt["step_id"] != state["step_id"]:
            raise ValueError("lease task binding changed")
        return {
            "task_revision": str(receipt["task_revision"]),
            "fence": str(receipt["fence"]),
            "status": "leased",
        }

    def infer(state: WorkflowState) -> dict[str, str]:
        renew: dict[str, object] = {
            "expected_revision": state["task_revision"],
            "step_id": state["step_id"],
            "fence": state["fence"],
        }
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bounded-runtime-inference")
        future = executor.submit(
            client.inference,
            task_id=task_id,
            step_id=state["step_id"],
            fence=state["fence"],
            expected_task_revision=state["task_revision"],
        )
        deadline = time.monotonic() + 30
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("runtime inference result deadline expired")
                try:
                    result = future.result(timeout=min(renew_interval, remaining))
                    break
                except TimeoutError:
                    if future.done():
                        raise
                    renewed = client.renew(task_id, renew)
                    validate_contract("LeaseView", dict(renewed))
                    if any(
                        renewed[key] != value
                        for key, value in (
                            ("task_id", task_id),
                            ("step_id", state["step_id"]),
                            ("fence", state["fence"]),
                            ("task_revision", state["task_revision"]),
                        )
                    ):
                        raise ValueError("renewal binding changed") from None
            validate_contract("InferenceResult", dict(result))
            private["result"] = result
            if result["state"] != "completed":
                return {"status": "ended"}
            proposal = cast(Mapping[str, object], result["proposal"])
            validate_contract("Proposal", dict(proposal))
            if (
                any(
                    proposal[key] != value
                    for key, value in (
                        ("task_id", task_id),
                        ("step_id", state["step_id"]),
                        ("fence", state["fence"]),
                        ("expected_task_revision", state["task_revision"]),
                    )
                )
                or proposal["next"] is not None
            ):
                raise ValueError("proposal must preserve task binding and have no tool effect")
            private["proposal"] = proposal
            return {"status": "proposed"}
        finally:
            # Future cancellation cannot prove remote inference has stopped.
            executor.shutdown(wait=False, cancel_futures=True)

    def propose(_state: WorkflowState) -> dict[str, str]:
        private["result"] = client.propose(private.pop("proposal"))
        return {"status": "awaiting_human"}

    graph = cast(_GraphFactory, cast(object, StateGraph))(WorkflowState)
    graph.add_node("lease", lease)
    graph.add_node("infer", infer)
    graph.add_node("propose", propose)
    graph.add_edge(START, "lease")
    graph.add_edge("lease", "infer")

    def next_node(state: WorkflowState) -> str:
        return state["status"]

    graph.add_conditional_edges("infer", next_node, {"proposed": "propose", "ended": END})
    graph.add_edge("propose", END)
    try:
        graph.compile().invoke(
            {
                "task_id": task_id,
                "task_revision": task_revision,
                "step_id": str(uuid4()),
                "fence": initial_fence,
                "status": "requested",
            },
            config={"recursion_limit": 4, "callbacks": []},
        )
        return private["result"]
    finally:
        private.clear()
