# Sam v1 Toolchain — Doctrine Note

**Install date:** 2026-04-18
**Platform:** macOS (Darwin 24.6.0)
**Operator's language contract:** Python only. The tools below let Sam
*read, explain, and interact with* the polyglot digital-asset world
while the operator continues writing Python.
**Verified by:** `scratch/toolcheck.py` — run anytime to re-confirm.

---

## The stack at a glance

| Tool               | Version on install  | Role in one line                                    |
| ------------------ | ------------------- | --------------------------------------------------- |
| Homebrew           | 5.1.1               | macOS package manager — installs and updates every other tool here |
| Node.js            | v22.22.2            | JavaScript runtime — powers on-chain tooling and frontends |
| npm                | 10.9.7 (ships w/Node)| Node's package manager — grabs libraries like ethers, hardhat, xrpl |
| Foundry — forge    | 1.5.1-stable        | Solidity build system + test runner (the "hardhat killer") |
| Foundry — cast     | 1.5.1-stable        | Swiss-army CLI for talking to EVM chains from the terminal |
| Foundry — anvil    | 1.5.1-stable        | Local EVM node — a private Ethereum testnet that boots in < 1s |
| Rust — rustc       | 1.95.0              | Compiler for Rust — the language of Solana, NEAR, Substrate, some XRPL sidechains |
| Rust — cargo       | 1.95.0              | Rust's build system + package manager (Rust's npm equivalent) |

---

## Why each tool, and when we reach for it

### Homebrew
The package manager for macOS. Every other tool in this doctrine was
installed via `brew`, which keeps versions current and dependencies sane.
- **Reach for it:** installing any new CLI (`brew install <name>`),
  upgrading versions (`brew upgrade`), or diagnosing "where did this
  binary come from?" (`brew list --versions`).
- **Doctrine:** prefer `brew` over curl-to-bash installers whenever both
  exist. Audit trail is better and upgrades are one command.

### Node.js + npm
JavaScript runtime + package manager. Not our writing language, but it
is the *lingua franca* of Ethereum tooling: block explorers, dapp
frontends, most hardhat-era tutorials, and many SDKs ship as npm
packages first.
- **Reach for it:** pulling a JS-only library (e.g., ethers.js, wagmi,
  XRPL.js) to **read** reference implementations, or running a dapp
  frontend to see how an institutional UX is wired up.
- **Operator boundary:** we never ask you to write JS. If we need a
  Node-side helper script, Sam writes it and you run it once.

### Foundry — forge / cast / anvil
Foundry is the modern Solidity toolchain, written in Rust for speed.
Three binaries, three jobs.

- **forge** — builds, tests, and deploys Solidity contracts. Tests in
  Solidity itself (which means you can read the test intent even without
  a JS test harness).
  - *Reach for it:* when we study a DeFi contract in `references/`,
    `forge build` compiles it so `cast` can interrogate it; when we
    deploy a one-off token contract for the tokenized MMF build or any
    future DvP (Delivery-versus-Payment) sim.

- **cast** — a CLI that speaks the full EVM-JSON-RPC protocol. Read
  balances, encode function calls, send signed transactions, decode logs
  — all from the shell.
  - *Reach for it:* poking at a live contract on mainnet-fork or testnet
    without writing any Python, or double-checking that the Python
    `web3.py` call we just wrote produces the same calldata cast does.

- **anvil** — a local, in-memory EVM node. Boots instantly, gives you
  ten pre-funded test accounts, and can fork mainnet state for
  realistic local experiments.
  - *Reach for it:* any build that needs to actually run a contract
    end-to-end before touching a public testnet. Cheap, fast, zero risk.

- **Doctrine:** Foundry stays the default over Hardhat because (a) it
  is one binary with no Node dependency tree, (b) tests in Solidity
  keep us close to the source, and (c) `cast` alone replaces half a
  day of glue code.

### Rust — rustc / cargo
Rust is the second most important ecosystem language in digital assets
after Solidity. Solana programs, NEAR contracts, Cosmos SDK modules,
Substrate (Polkadot) chains, and several XRPL sidechains are all Rust.
Foundry itself is Rust, which is why we have rustc installed anyway.
- **rustc:** the compiler.
- **cargo:** Rust's npm — pulls crates (libraries), builds, tests.
- **Reach for it:** when we study a Solana program (anchor framework)
  or a Cosmos module in `references/`, cargo lets us compile and read
  the actual bytecode/IDL the chain will execute. The operator never
  writes Rust — Sam reads it, explains it line by line, and builds a
  Python interaction layer (solders, anchorpy, cosmpy) around it.

---

## What this stack explicitly does NOT cover (yet)

- **Python itself** — managed separately via the project `.venv`. The
  operator's writing environment is orthogonal to this toolchain list.
- **Move** (Aptos, Sui), **Cairo** (Starknet), **Vyper** — not installed
  v1. We add them when a build demands them and document the decision
  in a new doctrine note, not as a preemptive install.
- **Docker / container tooling** — deferred. Every v1 build runs on bare
  macOS to keep the audit trail short and the learning surface flat.
- **Hardware-wallet / HSM integrations** — out of scope for testnet v1.

---

## How to re-verify

```bash
python3 scratch/toolcheck.py
```

Exit code 0 means all green. Run it after any `brew upgrade`, any macOS
update, or anytime a build fails in a way that smells like a missing
binary.

---

## Doctrine principles

1. **One binary per job.** If `cast` does it, we don't install a second
   tool to do the same job differently.
2. **Install via `brew` or official one-liners only.** No random tarballs.
3. **Version-pin in build READMEs, not here.** This file records the
   *baseline* at 2026-04-18. Individual builds state the exact versions
   they were validated against.
4. **The operator never writes non-Python.** These tools exist so Sam
   can read, compile, and run polyglot source on the operator's behalf.
