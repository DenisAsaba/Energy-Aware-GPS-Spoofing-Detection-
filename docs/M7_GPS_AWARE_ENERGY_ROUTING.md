# M7 GPS aware energy routing — Stage 1

## Scope and status

Stage 1 implements an isolated SUMO routing experiment and a 12-run paired smoke test. It is a research benchmark, not a production navigation or spoofing defense system. The smoke matrix covers normal GPS, offset, jump, and drift observations under normal navigation, unprotected GPS-responsive navigation, and detector-protected navigation.

## Architecture and trust boundary

SUMO runs the EV on the new M7 diamond network. `approach` is shared by two connected alternatives: `direct_a`/`direct_b` and `alternate_a`/`alternate_b`; both start at `origin` and end at `destination`. GPS X/Y observations are generated during each trip from the current SUMO position plus seeded Gaussian noise and the configured attack. The navigation controller compares each GPS fix with route reference points and installs a connected route through TraCI while the vehicle remains on `approach`.

M5 remains unchanged. At each timestep the M7 runner writes the chronological GPS-only prefix to the M5 input schema (`time_s,vehicle_id,gps_x_m,gps_y_m`), calls `extract_gps_features()` and `apply_temporal_thresholds()`, and uses the last `predicted_attack` value. Thresholds are frozen values from M6 normal calibration trips. The M5 calls do not receive SUMO position, route progress, attack type, attack labels, future fixes, or battery telemetry. A one-fix prefix is ineligible under M5 and cannot alert.

Protected navigation continues to use GPS for its initial route choice. Only after an M5 alert does it query `traci.simulation.findRoute(current_edge, destination_edge)`. SUMO edge/route state is an oracle fallback; this condition is **oracle-assisted research navigation**, not a GPS-only deployable solution. An alert itself is not a localization result.

## Routing and energy methods

SUMO network coordinates are local X/Y meters; timestamps and simulation step are seconds. Each paired arm holds network, EV/type, departure, initial charge (25,000 Wh), SUMO seed, GPS seed, and attack parameters fixed. Attack labels are retained only in run-level results and never enter M5. The three conditions are run in separate SUMO processes with the same seeds.

The controller records every actual `setRoute` call, timestamp, reason, starting edge, and installed edge list. Per-step telemetry records the observed road ID, active SUMO route ID, speed, electricity, battery charge/capacity, cumulative energy consumption, and SOC when returned by the configured battery device. GPS observations and attack labels are written to separate files. Energy is summarized from SUMO's cumulative consumed-energy values; missing telemetry remains null. Route distance uses SUMO's `getDistance` odometer getter, not the proposed route length. Arrival time comes from SUMO's arrived-vehicle event.

The full matrix exposed a route-reachability edge case absent from Stage 1: an M5 alert can arrive after a vehicle has entered the alternate branch, where routing to the direct branch's terminal edge is disconnected. The isolated M7 controller was updated to select the terminal edge on the vehicle's current branch and to maintain the already-connected SUMO route across an internal junction edge. A regression test covers fallback from the alternate branch. No M0-M6 code was changed.

## Smoke command and outputs

From this project root, after verifying SUMO is on `PATH` and TraCI is importable:

```powershell
python -m src.experiments.m7_energy_routing --config config/m7_energy_routing.yaml --run-id stage1_smoke_01
python -m unittest tests.test_m7_routing_controller -v
python -m unittest discover -s tests -v
```

Each run ID is new-only under `reports/m7/stage1_smoke/`. It contains a copied config, metadata, paired `CSV`/JSON summaries, per-run GPS observations and telemetry. Re-running with another run ID supports byte-for-byte reproducibility checks of result files; the run ID itself is intentionally different.

## Stage 1 smoke results

The checked-in smoke configuration uses seed 713, GPS seed 2713, 1 m per-axis Gaussian noise, 180 m northward offset/jump intensity, and drift capped at 180 m (2 m/s). It is a deliberately small causal demonstration, not an attack-intensity evaluation.

All 12 trips reached the destination. Normal navigation stayed on the direct path with no detector alerts. Unprotected offset GPS selected and executed the alternate path: SUMO odometer distance 1,449.65 m and consumed energy 224.53 Wh versus 1,378.50 m and 162.06 Wh for the paired normal-GPS direct trip. This one smoke pair is not evidence of general energy savings or loss. Protected offset also chose the alternate path before M5 alerted; M5 produced no alert, so no oracle fallback occurred. M5 likewise produced no alert for drift, and drift did not change the executed route in this configuration.

M5 alerted when the temporary jump ended and the GPS fix returned toward normal, after the spoofed interval had ceased. Unprotected navigation made two GPS-based route changes and ultimately executed the direct path; protected navigation invoked the oracle fallback at the alert and arrived on the direct path. The alert came too late to mitigate the jump. These observations distinguish detector alert, fallback activation, executed route, and arrival; none alone implies successful mitigation. The fixed M5 thresholds are not retuned on these smoke results.

## Limitations

Only one EV, network, SUMO seed, GPS seed, attack intensity, and traffic state are used. The controller only accepts GPS-directed route changes on the shared approach edge; it does not map-match arbitrary observations or perform safe-stop behavior. SUMO ground truth is available to the routing fallback only after detector activation. The frozen M5 rules missed both offset and drift in this smoke configuration. The route-distance statistic is sampled odometer approximation, while SUMO battery telemetry provides the energy values. The smoke does not establish statistical significance, broad detector performance, causal energy effects across scenarios, or production readiness.

## Stage 2 full paired matrix

Stage 2 uses the same M7 network/controller and frozen M5 thresholds. It does not fit or retune thresholds. The configured seed groups are calibration 801, validation 802, and final test 803/804. Calibration and validation contain one normal-GPS trip each; final test contains one normal-GPS control per seed and 24 protected/unprotected pairs. The three attacks each use 60 m and 180 m northward magnitudes (for drift, displacement caps), with durations 30 s and 90 s for offset/drift and 2 s and 10 s for jump. This is 52 SUMO trips per complete run.

The attack label interval is half-open `[onset, onset + duration)`. **Active-attack detection** counts an M5 alert only inside that interval. Alerts at the first restored GPS fix are separately classified as **post-attack alerts** and are not credited as detection or mitigation. Detection delay is reported only for an alert during the active interval. The test-set normal false-positive rate is alert count divided by eligible M5 fixes in the two normal-GPS test trips. Mitigation success requires a protected fallback plus destination arrival and either an unprotected arrival failure or a protected odometer distance at least 1 m shorter than its paired unprotected result.

Run a complete matrix and its independent repeat from the project root:

```powershell
python -m src.experiments.m7_matrix --config config/m7_energy_routing.yaml --run-id m7_full_02
python -m src.experiments.m7_matrix --config config/m7_energy_routing.yaml --run-id m7_full_03
python -m unittest discover -s tests -v
```

Each run writes to a new directory under `reports/m7/full_matrix/`. It contains per-run CSV/JSON, 24 paired comparisons, aggregate summaries by attack and condition, paired summaries by attack magnitude/duration, two PNG figures, and a run metadata file. Paired rows retain the seed and attack parameters, so seed-level outcomes are not hidden by averages.

### Stage 2 final-test results

The first complete final-test matrix has 48 attack runs (24 pairs) and two normal-GPS controls. All 50 final-test trips arrived; both calibration/validation normal trips also arrived. Battery telemetry was complete in all 52 runs. The measured test-set normal false-positive rate was 0/eligible fixes (0%).

| Attack | Active M5 detection | Post-attack M5 alert | Protected fallback | Mitigation success | Arrival rate |
|---|---:|---:|---:|---:|---:|
| Offset | 0/8 (0%) | 8/8 (100%) | 8/8 (100%) | 0/8 (0%) | 8/8 (100%) |
| Jump | 0/8 (0%) | 8/8 (100%) | 8/8 (100%) | 0/8 (0%) | 8/8 (100%) |
| Drift | 0/8 (0%) | 8/8 (100%) | 8/8 (100%) | 0/8 (0%) | 8/8 (100%) |

For all attack types, the alert occurred at attack recovery (offset/drift: 30 or 90 seconds after onset; jump: 2 or 10 seconds after onset), not while spoofing was active. The fallback therefore activated after the attack interval and did not improve any paired outcome. No protected/unprotected pair differed in destination arrival, odometer distance, travel time, energy consumption, or SOC change: all 24 paired mean deltas are exactly 0 for these metrics.

Across test runs, normal GPS averaged 1,372.63 m (sample SD 1.55), 113.5 s (SD 2.12), 182.17 Wh consumed (SD 1.46), 75.70 Wh regenerated (SD 3.33), and SOC change −0.002130. Offset arms each averaged 1,392.07 m (SD 36.02), 115.875 s (SD 4.73), 191.13 Wh consumed (SD 16.62), 82.71 Wh regenerated (SD 13.17), and SOC change −0.002168. Jump and drift arms each averaged 1,372.63 m (SD 1.17), 113.5 s (SD 1.60), 182.17 Wh consumed (SD 1.10), 75.70 Wh regenerated (SD 2.52), and SOC change −0.002130. Protected and unprotected means are identical within each attack type, including regeneration. These descriptive results do not support an energy-saving or mitigation claim.

GPS-driven decisions did alter some routes: the 180 m offset caused alternate-route execution in 2/8 runs per spoofed condition; other offset runs and jump runs sometimes changed the proposed TraCI route before returning to the direct route. Drift did not execute the alternate route at these settings. Actual executed edges are recorded per run; a proposed route change is not counted as a completed deviation unless those edges appear in SUMO telemetry.

### Reproducibility, validation, and limits

The independent run uses the same configuration and seeds under a new run ID. Deterministic per-run GPS, label, telemetry, summary, aggregate, paired comparison, and plot files are SHA-256 compared: 219 files matched byte-for-byte; only `run_metadata.json` is excluded because its run ID differs. Route endpoint/connectivity validation is run before each matrix. Duplicate pair-condition rows, incomplete pairs, missing runs, failed arrivals, and battery telemetry gaps are checked in the output audit. M7 calibration/validation trips do not supply detector parameters; M5 thresholds remain the M6 normal-calibrated values.

The matrix contains two final-test seeds, one EV, one network, no variable traffic demand, and four attack configurations per type. Its paired differences are descriptive and highly dependent on this simplified network/controller. The oracle-assisted fallback is not deployable GPS-only navigation. The detector's 100% post-attack alert rate does not mean it detected any attack in time: active-attack detection was 0%, and mitigation was 0%. No production-readiness, statistical-generalization, or energy-saving claim is supported.
