"""Fixed-broker runtime worker. No model, store, actor credential or send tool."""

import argparse
import ssl
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from care_link_contracts import validate_contract

from .client import HttpBrokerTransport, RuntimeClient


class RuntimeWorker:
    def __init__(
        self,
        client: RuntimeClient,
        poll: Callable[[], Mapping[str, object]],
    ) -> None:
        self.client, self.poll = client, poll

    def run_once(self) -> Mapping[str, object] | None:
        item = self.poll()
        validate_contract("RuntimeWorkItem", dict(item))
        refs = [item["task_id"], item["task_revision"], item["fence"]]
        if all(value is None for value in refs):
            return None
        if any(value is None for value in refs):
            raise ValueError("complete work binding required")
        # Poll consumption and Data leases bound replay. An error is surfaced;
        # this worker never creates a replacement task or retries its budget.
        return self.client.run_one_turn(
            str(item["task_id"]),
            str(item["task_revision"]),
            initial_fence=str(item["fence"]),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--cert-file", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    tls = ssl.create_default_context(cafile=str(args.ca_file))
    tls.load_cert_chain(str(args.cert_file), str(args.key_file))
    transport = HttpBrokerTransport(tls)
    worker = RuntimeWorker(RuntimeClient(transport), transport.poll_work)
    try:
        while True:
            worker.run_once()
            if args.once:
                break
            time.sleep(1)
    finally:
        transport.close()


if __name__ == "__main__":
    main()
