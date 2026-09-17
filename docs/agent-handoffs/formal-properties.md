# Formal properties

## Status
Done

## Requested outcome
Machine-checked safety and liveness properties for the engine, the December
roadmap item, using the SymbiYosys toolchain already present in the local
nix-portable store.

## Constraints and acceptance criteria
- No change to synthesized RTL: properties live in `formal/properties.vh`,
  included under `ifdef FORMAL` at the end of `src/engine.v`.
- Unbounded proof (k-induction), not only BMC; reachability covers so the
  assertions are not vacuous; negative controls so the properties bite.
- Pinned tools, reproducible by `just formal`; evidence in `reports/formal.json`.

## Evidence gathered
- `~/.nix-portable` holds Yosys 0.66 with sby, Yices 2.7.0, Boolector and Z3
  from the LibreLane flake; `nix-portable nix shell <store paths>` runs them.
- Yosys 0.66 did not resolve hierarchical `dut.*` references from a wrapper
  module (undriven wires after flatten), hence the include-under-FORMAL pattern.

## Proposed or completed changes
- `formal/properties.vh`, `formal/engine.sby`, `tools/formal.sh`, `just formal`.
- `tools/check_formal_mutations.py`: six one-bug engine mutations, each must
  fail bmc at depth 32.
- `tools/formal_report.py` → `reports/formal.json`.
- `docs/verification.md` formal section; README and roadmap.

## Verification
- `just formal`: bmc depth 40 PASS, prove depth 24 PASS (induction closes),
  cover: six of six reached (steps 13–28). Logs under `build/formal/`.
- Negative controls: see `reports/formal.json` (`negative_controls`).
- Induction needed two strengthening invariants beyond the original intent:
  the tagged FIFO slot lies inside the occupied window, and a nonzero
  `wait_elapsed` while running occurs only at an issuable WAIT with a timeout.
  The second exposed that an aborted RUN leaves `wait_elapsed` set until the
  next RUN rising edge clears it; harmless, and now documented in the property.

## Risks, open questions, and next owner
- Properties constrain the RTL only; firmware and the routed netlist are covered
  by simulation. The CI workflows do not yet run `just formal`.
