"""Batch wire-contract verdicts for the cross-language differential test."""

import json
import sys

from care_link_contracts import ContractError, parse_contract


def main() -> None:
    cases = json.load(sys.stdin)
    results: list[bool] = []
    for case in cases:
        try:
            parse_contract(case["schema"], case["raw"])
        except ContractError:
            results.append(False)
        else:
            results.append(True)
    print(json.dumps(results))


if __name__ == "__main__":
    main()
