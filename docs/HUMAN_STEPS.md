# Human steps: what only you can do

Everything in the repo is built and offline-tested. These steps need real money, your auth, your
browser, or your screen. They are ordered by the deadline they serve.

## Before tonight's code-lock (Jun 21 12:00 UTC = 20:00 Beijing)

### 1. Push to the public GitHub repo
Status: the repo `sumplus-real/sumplus-trader-bnb` is created and the deploy key is added (write
access). The SSH alias and remote are configured locally. When you give the word, I run
`git push -u origin main`. The Mantle repo stays untouched.

### 2. Commit-reveal the policy hash on-chain
The committed hash (recompute anytime with `python -m agent.cli commit`) is currently:
`sha256:fb0d30ef0f7d31b868055a51ca651a39fd03736e9f4d597150614686a6bdb65a`
- Fund the agent wallet with a little BNB for gas first (see step 4).
- Then:
```bash
export AGENT_ADDRESS=0x...          # the dedicated agent wallet
export AGENT_PRIVATE_KEY=0x...      # its key (never commit this)
export BSC_RPC=https://bsc-dataseed.bnbchain.org
python -m agent.cli commit --send   # broadcasts the 0-value self-tx carrying the policy hash
```
- This must land before code-lock. Put the resulting tx hash into `config/proof.json` under
  `commit_tx`.

## Before the live window opens (Jun 22)

### 3. Install TWAK and create the agent wallet (needs Node ≥ 22.14; you're on Node 20)
```bash
nvm install 22 && nvm use 22
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
twak wallet create                  # creates the dedicated self-custody agent wallet (its address is the BNB agent address)
twak compete register               # registers that address on the BSC competition contract
```
- Put the wallet address into `config/proof.json` under `agent_wallet`, and the ERC-8004 id (if
  shown) under `erc8004_id`. Check the exact `twak swap` flags against `twak --help` and tell me if
  they differ from the template in `agent/execution/twak_backend.py`.

### 4. Fund the agent wallet (~$500)
- Send ~$500 of USDT (plus a few dollars of BNB for gas) to the registered agent wallet on BSC.
- This is real money at risk. Risky exposure is capped at 12% and the drawdown ladder flattens at
  3%. The stress test never breached the 6% gate, but live markets can gap, so size accordingly.

### 5. Start the live loop (unattended, runs the week)
```bash
EXECUTION_BACKEND=twak MODE=live python -m agent.cli loop
```
- Runs ops-hardened: watchdog restarts, persistent state, fail-closed. To stop: `touch STOP`.

## For the submission

### 6. Deploy the dashboard as a public link
`render.yaml` and `Dockerfile` are in the repo. In Render, choose New > Blueprint, connect
`sumplus-real/sumplus-trader-bnb`, and it builds a public URL. The committed demo data renders right
away, and live data accrues into the same URL during 6/22 to 6/28. That URL goes in the BUIDL demo
field. (A ~90s video script is in `docs/DEMO_SCRIPT.md` as a fallback.)

### 7. Submit the DoraHacks BUIDL form (T1 + T2)
Paste-ready text in `submission_buidl.txt`. Track 1 is the live agent; Track 2 is
`docs/TRACK2_RESEARCH.md`.

---

**Note:** `config/strategy.json` is frozen. Its hash is the on-chain commitment. Do not edit it
after step 2, or the commitment will not match the live receipts.
