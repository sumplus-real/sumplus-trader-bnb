"""Publish the commit-reveal: put the policy hash on-chain BEFORE code-lock.

We send one 0-value transaction from the agent wallet to itself whose calldata carries a
human-readable tag plus the committed policy hash. On BscScan anyone can read the input data and
the block timestamp, proving the agent fixed its rules before the live window opened. After the
week, recompute the hash from config/strategy.json and check it matches — and that every receipt
referenced it. That is rule-adherence as a proof instead of a promise.

Dry-run by default (prints the unsigned tx + the readable tag). A real send needs AGENT_PRIVATE_KEY
+ a BSC RPC + a little BNB for gas — a human step (see docs/HUMAN_STEPS.md).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from agent.policy.commit import build_commitment
from agent.policy.canonical import committed_policy_hash

TAG = "sumplus.policy/v1 "


def commitment_calldata() -> tuple[str, str]:
    """Return (human_tag, hex_calldata) embedding the committed policy hash."""
    ph = committed_policy_hash()
    tag = TAG + ph
    return tag, "0x" + tag.encode("utf-8").hex()


def build_unsigned_tx(*, agent_address: str, chain_id: int = 56, nonce: int = 0,
                      gas_price_wei: int = 1_000_000_000, gas: int = 60_000) -> dict[str, Any]:
    _, data = commitment_calldata()
    return {
        "from": agent_address, "to": agent_address, "value": 0,
        "data": data, "chainId": chain_id, "nonce": nonce,
        "gas": gas, "gasPrice": gas_price_wei,
    }


def publish(*, dry_run: bool = True) -> dict[str, Any]:
    tag, data = commitment_calldata()
    agent_address = os.environ.get("AGENT_ADDRESS", "")
    commitment = build_commitment(agent_id=os.environ.get("AGENT_ID", "sumplus-trader-bnb"),
                                  repo_url=os.environ.get("REPO_URL", ""))
    key = os.environ.get("AGENT_PRIVATE_KEY", "")
    rpc = os.environ.get("BSC_RPC", "https://bsc-dataseed.bnbchain.org")

    if dry_run or not key or not agent_address:
        return {"dry_run": True, "tag": tag, "calldata": data,
                "commitment": commitment,
                "note": "set AGENT_PRIVATE_KEY + AGENT_ADDRESS + BSC_RPC and pass --send to broadcast"}

    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(rpc))
    nonce = w3.eth.get_transaction_count(agent_address)
    tx = build_unsigned_tx(agent_address=agent_address, nonce=nonce,
                           gas_price_wei=w3.eth.gas_price)
    signed = w3.eth.account.sign_transaction(tx, private_key=key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return {"dry_run": False, "tx_hash": tx_hash.hex(), "tag": tag,
            "commitment": commitment, "explorer": f"https://bscscan.com/tx/{tx_hash.hex()}"}


def main() -> None:
    dry = "--send" not in sys.argv
    print(json.dumps(publish(dry_run=dry), indent=2))


if __name__ == "__main__":
    main()
