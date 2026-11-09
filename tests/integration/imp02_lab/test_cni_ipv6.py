"""CNI template regression; live interface observations remain separate evidence."""

import json

import pytest

from tools.imp02_lab.cluster import disable_pod_ipv6


def test_ipv6_is_disabled_by_tuning_in_new_pod_namespace_with_mtu_preserved() -> None:
    original = (
        '{"name":"k8s-pod-network","cniVersion":"1.0.0","plugins":['
        '{"type":"calico","mtu":__CNI_MTU__,"nodename":"__KUBERNETES_NODE_NAME__"},'
        '{"type":"portmap","snat":true}]}'
    )
    rendered = disable_pod_ipv6(original)
    assert rendered.count("__CNI_MTU__") == 1
    value = json.loads(rendered.replace("__CNI_MTU__", "1450"))
    assert value["plugins"][0]["mtu"] == 1450
    assert value["plugins"][0]["nodename"] == "__KUBERNETES_NODE_NAME__"
    assert value["plugins"][-1] == {
        "type": "tuning",
        "sysctl": {
            "net.ipv6.conf.all.disable_ipv6": "1",
            "net.ipv6.conf.default.disable_ipv6": "1",
        },
    }
    assert disable_pod_ipv6(rendered) == rendered


def test_unknown_plugin_or_sysctl_chain_requires_review() -> None:
    for types in (
        [{"type": "bridge"}, {"type": "portmap"}],
        [
            {"type": "calico"},
            {"type": "portmap"},
            {"type": "tuning", "sysctl": {"net.ipv4.ip_forward": "1"}},
        ],
    ):
        value = {"plugins": types, "mtu": "__CNI_MTU__"}
        raw = json.dumps(value).replace('"__CNI_MTU__"', "__CNI_MTU__")
        with pytest.raises(ValueError):
            disable_pod_ipv6(raw)
