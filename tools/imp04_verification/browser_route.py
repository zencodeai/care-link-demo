"""Read-only binding of the qualification browser to its owned TLS ingress."""

import ipaddress
import json
import re

from tools.imp04_deployment.config import PREFIX, record
from tools.imp04_deployment.docker import inspect_container


def address_pin(browser: dict[str, object], ingress: dict[str, object]) -> str:
    """Keep the hostname and TLS verification while selecting the owned route."""
    network = PREFIX + "-ingress"
    browser_link = record(record(record(browser.get("NetworkSettings"))["Networks"])[network])
    ingress_link = record(record(record(ingress.get("NetworkSettings"))["Networks"])[network])
    network_id = ingress_link.get("NetworkID")
    if (
        not isinstance(network_id, str)
        or not re.fullmatch("[0-9a-f]{64}", network_id)
        or browser_link.get("NetworkID") != network_id
    ):
        raise ValueError("Owned browser and ingress must share their exact network identity")
    raw = ingress_link.get("IPAddress")
    if not isinstance(raw, str):
        raise ValueError("Exact owned ingress IPv4 address required")
    address = ipaddress.ip_address(raw)
    subnet = ipaddress.ip_network("172.29.47.0/24")
    if (
        not isinstance(address, ipaddress.IPv4Address)
        or str(address) != raw
        or address not in subnet
        or address in {subnet.network_address, subnet.broadcast_address}
    ):
        raise ValueError("Exact owned IMP04 ingress subnet required")
    return raw


def owned_route() -> dict[str, str]:
    browser = inspect_container(PREFIX + "-review-chrome")
    ingress = inspect_container(PREFIX + "-ingress")
    browser_id, ingress_id = browser.get("Id"), ingress.get("Id")
    if any(
        not isinstance(v, str) or not re.fullmatch("[0-9a-f]{64}", v)
        for v in (browser_id, ingress_id)
    ):
        raise ValueError("Exact inspected owned container identities required")
    return {
        "address": address_pin(browser, ingress),
        "browser_id": str(browser_id),
        "ingress_id": str(ingress_id),
    }


if __name__ == "__main__":
    print(json.dumps(owned_route()))
