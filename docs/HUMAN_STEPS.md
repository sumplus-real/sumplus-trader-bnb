# Human steps — what only you can do

Everything in the repo is built and offline-tested. These steps need real money, your auth, your
browser, or your screen. Ordered by the deadline they serve.

## Before tonight's code-lock (Jun 21 12:00 UTC = 20:00 Beijing)

### 1. Create the public GitHub repo + push
Same deploy-key pattern as the Mantle repo (one repo, one key — never a PAT here):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/sumplus_trader_bnb_deploy -N "" -C "sumplus-trader-bnb"
cat ~/.ssh/sumplus_trader_bnb_deploy.pub          # paste into the new repo's Deploy keys (allow write)
```
- Create empty public repo `sumplus-real/sumplus-trader-bnb` in the browser, paste the public key
  (tick "Allow write access").
- Tell me when done — I'll add the SSH host alias + remote and push. (Mantle repo is untouched.)

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
- This must land BEFORE code-lock. Put the resulting tx hash into `config/proof.json` → `commit_tx`.

## Before the live window opens (Jun 22)

### 3. Install TWAK (needs Node ≥ 22.14; you're on Node 20)
```bash
nvm install 22 && nvm use 22
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
twak wallet create                  # creates the dedicated self-custody agent wallet
twak compete register               # registers it on the BSC competition contract
```
- Put the wallet address into `config/proof.json` → `agent_wallet`, and the ERC-8004 id (if shown)
  → `erc8004_id`. Verify the exact `twak swap` flags against `twak --help` and tell me if they
  differ from the template in `agent/execution/twak_backend.py`.

### 4. Fund the agent wallet (~$500)
- Send ~$500 of USDT (+ a few $ of BNB for gas) to the registered agent wallet on BSC.
- This is real money at risk. Risky exposure is capped at 12% and the drawdown ladder flattens at
  3%; the stress test never breached the 6% gate, but live markets can gap. Size accordingly.

### 5. Start the live loop (unattended, runs the week)
```bash
EXECUTION_BACKEND=twak MODE=live python -m agent.cli loop
```
- Runs ops-hardened (watchdog restarts, persistent state, fail-closed). To stop: `touch STOP`.
- Keep the dashboard up for judges: `python -m agent.cli web` (or deploy it).

## For the submission

### 6. Record the demo video (~90s)
Script in `docs/DEMO_SCRIPT.md`. Everything is clicks in the dashboard at `http://127.0.0.1:8800`
after `python -m agent.cli simulate 6` populates a full week.

### 7. Submit the DoraHacks BUIDL form (T1 + T2)
Paste-ready text in `submission_buidl.txt`. Track 1 = the live agent; Track 2 = `docs/TRACK2_RESEARCH.md`.

---

**Note:** `config/strategy.json` is frozen — its hash is the on-chain commitment. Do not edit it
after step 2, or the commitment won't match the live receipts.
