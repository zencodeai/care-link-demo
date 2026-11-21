"""Named coordinator and inference ports; Core never imports business storage."""

from typing import Protocol

from care_link_domain import Actor, WorkloadPeer

Record = dict[str, object]


class Coordinator(Protocol):
    def task_read(self, actor: Actor, task_id: str) -> Record: ...
    def step_lease(
        self, actor: Actor, task_id: str, data: Record, peer: WorkloadPeer
    ) -> Record: ...
    def step_renew(
        self, actor: Actor, task_id: str, data: Record, peer: WorkloadPeer
    ) -> Record: ...
    def reserve_proposal(self, actor: Actor, data: Record, peer: WorkloadPeer) -> Record: ...
    def proposal_submit(
        self, actor: Actor, data: Record, peer: WorkloadPeer, reservation_id: str
    ) -> Record: ...
    def tool_invoke(self, actor: Actor, data: Record, peer: WorkloadPeer) -> Record: ...


class InferencePort(Protocol):
    def infer(self, request: Record) -> Record: ...
