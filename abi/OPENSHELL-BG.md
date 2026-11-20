# OpenShell backend for `bg` — investigation (board #13)

Status: investigated 2026-11-20 from the NVIDIA/OpenShell CLI contract
(`cli-reference.md`, `skills/openshell-cli`). No openshell binary on this host;
verification of the exec semantics below is deferred to a real gateway host.

## Question

`bg` is refused when the effective driver is openshell: a detached host
process would bypass the sandbox. Can a persistent sandbox carry background
procs with `proc` semantics (list / poll / wait / log / kill / write)?

## What the CLI offers

- `sandbox create --name X --detach` — retained sandbox; without `--no-keep`
  it persists after its canonical main process (`/bin/bash -l` PTY) exits.
- `sandbox exec X --workdir /sandbox -- cmd` — spawns an independent sibling
  process, streams stdout/stderr, returns the remote exit code.
- `sandbox exec --tty` — PTY-backed exec for interactive procs.
- `sandbox upload <name> <path> [dest]` and
  `sandbox download <name> <path> [dest]` — tar-over-SSH file transfer in
  **both** directions, usable after create (not just at create time).
- `sandbox stop` / `sandbox delete` — lifecycle teardown.
- `sandbox connect` — attaches to the canonical main process with a ~1 MiB
  output replay buffer.

## Hard constraint (from QA 18.11)

Bg procs must write into the real workspace fs, not a sandbox snapshot.
`--upload` at create is host→sandbox only; writes inside the sandbox are
invisible to the host until pulled. `sandbox download` closes that gap — a
`proc wait`/exit hook can pull the workdir back — but it is a copy, not a
live mount, so mid-run fs side-effects stay sandbox-local.

## Options

- **(a) persistent sandbox + exec + fs-sync**: one named sandbox per workdir
  (`agents-term-<hash>`), `bg` becomes `sandbox exec --detach`-style procs,
  `proc log` reads via connect replay or exec'd tail, `proc kill` execs
  `kill`, exit triggers `download /sandbox`. Full fidelity, heaviest build.
- **(b) output-only procs**: same persistent sandbox, but document that
  sandbox-side fs writes are ephemeral; `proc wait` optionally pulls changed
  paths. Cheap to layer on (a) later.
- **(c) keep refusing + document the split**: current state. Zero risk.

## Recommendation

Adopt **(a)** behind `AGENTS_TERMINAL_BG_SANDBOX=persistent` once a real
openshell host validates: exec streaming, exit-code delivery, download
fidelity, and kill propagation through the supervisor. Until then keep the
refusal — it is a closed door, not a hole. `proc` needs a per-proc sandbox
name + remote pid in `meta.json` and a `proc wait`→`sandbox download` sync
step. Relates to agents-runtime ExecBackend (E-track): that interface should
own "exec into named sandbox + pull fs" so terminal stays thin.
