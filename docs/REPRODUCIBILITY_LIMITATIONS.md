# Reproducibility limitations and evidence inspection

## Scope and status

This documentation correction records the read-only audit of `main` at commit `3f6439c004dc144dd7b1580cae76d2cf5a40220e` on November 13, 2026. M0-M9 research is complete through M9 Stage 2; no new experiment, metric, or scientific conclusion is introduced here. The approved appendix wording below has been integrated into the companion DOCX and regenerated PDF, both verified at 36 pages. The title remains pending advisor approval.

| Category | What is available or blocked |
|---|---|
| Committed and inspectable evidence | Source modules, eight experiment configurations, tests, SUMO network/route inputs, milestone methods, result tables, predictions, figures, and the report. Coverage varies by milestone; this does not mean all historical inputs are tracked. |
| Potentially regenerable experiments | Simulation/observation/detection workflows have implementations and documented seeds/settings. Execution requires a compatible environment, necessary inputs, unused output IDs, and satisfied preservation checks. Regeneration has not been verified from a clean clone. |
| Historical runs not independently reproducible from a clean clone | Initial M1/M2 inputs, additional M4/M5 CSV inputs, external M3 verification evidence, and historical M9 preservation prerequisites are absent from Git. M9 also has a baseline checksum blocker even in the audited local workspace. |
| Unresolved preservation provenance | Exactly 509 M8 files match HEAD but not the frozen M9 baseline. The cause and chronology of these historical-byte differences remain unresolved. |

Historical successful tests and repeatability comparisons in the methods documents describe their recorded execution environment. They are not evidence that the published checkpoint now passes every prerequisite on a clean clone.

## Missing inputs

At the audited commit, `data/raw/`, `data/processed/`, and `data/attacks/` contain only tracked `.gitkeep` files. The following inputs exist locally but are absent from Git. Listing names here does not publish or copy their contents.

Previously disclosed M1/M2 files:

- `data/raw/truth_ev_001_20261104T073118.622118Z.csv`
- `data/raw/truth_ev_001_20261104T073118.622118Z_metadata.yaml`
- `data/processed/gps_normal_ev_001_20261104T073118.622118Z.csv`

Additional distinct CSV inputs referenced by the M4/M5 sections of `config/experiment_config.yaml`:

- `data/raw/truth_ev_001_20261105T035334.847823Z.csv`
- `data/processed/gps_normal_ev_001_20261105T035334.847823Z.csv`
- `data/raw/truth_ev_001_20261106T041622.998504Z.csv`
- `data/attacks/m3_git_demo_01/gps_offset_ev_001_20261106T041622.998504Z.csv`
- `data/attacks/m3_git_demo_01/gps_offset_ev_001_20261106T041622.998504Z_labels.csv`
- `data/attacks/m3_git_demo_01/gps_jump_ev_001_20261106T041622.998504Z.csv`
- `data/attacks/m3_git_demo_01/gps_jump_ev_001_20261106T041622.998504Z_labels.csv`
- `data/attacks/m3_git_demo_01/gps_drift_ev_001_20261106T041622.998504Z.csv`
- `data/attacks/m3_git_demo_01/gps_drift_ev_001_20261106T041622.998504Z_labels.csv`

These are confirmed configured dependencies, not an exhaustive inventory of every historical local artifact. A newly generated trip with a different timestamp does not automatically satisfy references to these historical files or their hashes.

Unique M3 final-verification evidence remains in the older parent project at `reports/m3/m3_final_verification/` and `data/attacks/m3_final_verification/`. The [evidence inventory](../reports/final_project/final_evidence_inventory.md) uses `external_historical_root_project/` as a provenance prefix; it is not a packaged directory in this repository. M6 historical metadata also contains references using that prefix. Four referenced parent network/route files matched their nested counterparts byte-for-byte during the audit, but this does not make all external evidence available in a clone.

## M9 preservation prerequisites and M8 provenance

The final evaluator reads `reports/m9/m9_stage1_validation_01/protected_before.json`, excludes `TASKS.md`, hashes the remaining paths as raw bytes, and rejects missing files or mismatches before evaluation. See `src/experiments/m9_final_evaluation.py` and the hashing helper in `src/experiments/m9_error_analysis.py`.

The manifest contains 4,553 entries, of which 4,552 are checked after that exclusion. All checked files existed in the audited local workspace. However, 1,061 baseline entries are absent from the tracked checkpoint:

| Baseline path group | Files absent from Git |
|---|---:|
| `reports/m6/` | 853 |
| `data/raw/` | 142 |
| `reports/m7/` | 41 |
| `data/attacks/` | 15 |
| `results/figures/` | 9 |
| `data/processed/` | 1 |
| **Total** | **1,061** |

These counts overlap the input dependencies above; do not add them as disjoint datasets. Some preservation prerequisites are historical smoke, partial, or plotting artifacts rather than direct final-evaluation inputs. The guard nevertheless requires their presence and expected hashes. In particular, it references local material under `reports/m7/full_matrix/m7_full_01/` as well as ignored artifacts.

The committed manifest is the exact filename/checksum inventory. To list its untracked prerequisites without creating files or running experiments, execute this read-only snippet from the repository root:

```powershell
@'
import json
import subprocess

tracked = set(subprocess.check_output(
    ["git", "ls-tree", "-r", "--name-only", "HEAD"], text=True
).splitlines())
baseline = json.loads(subprocess.check_output([
    "git", "show",
    "HEAD:reports/m9/m9_stage1_validation_01/protected_before.json",
]))
for name in sorted(set(baseline) - tracked - {"TASKS.md"}):
    print(name)
'@ | python -B -
```

The local baseline comparison found exactly 509 mismatches, all in M8: 434 YAML and 75 XML files. These same 509 files appeared in the older local uncommitted-file inventory and now match HEAD byte-for-byte; their HEAD bytes also fail the frozen baseline hashes. Available reflogs show no event that establishes how their working-tree differences disappeared. Reflogs do not record ordinary file edits or every restoration action.

These are **unresolved historical-byte discrepancies, not demonstrated changes to numerical research findings**. No causal explanation is established. The older M9 methods statement that preservation checks passed describes the historical execution, not the current checkpoint's ability to pass that guard. The current local final-evaluation command would reject the baseline mismatch; a clean clone additionally lacks the 1,061 prerequisites. No manifest, checksum, or guard was changed or bypassed for this correction.

## Line endings and raw-byte hashes

The audited Windows Git installation has `core.autocrlf=true`; no tracked `.gitattributes` or repository-local `.git/info/attributes` was present. Sampled M7/M9 CSVs had no explicit `text`, `eol`, or `filter` attributes. This is an environment observation, not a requested Git setting.

The audit identified 2,894 files outside M6 with index LF and working-tree CRLF and otherwise identical bytes: 534 M7 files (394 CSV, 140 JSON), 2,353 M9 files (1,431 CSV, 3 JSON, 312 XML, 607 YAML), and seven other files. The seven are `docs/FINAL_PROJECT_SUMMARY_M0_M9.md`, `docs/ORIGINAL_USER_PLAN.txt`, `results/m0/run_metadata.yaml`, `sumo/network/m0.net.xml`, `sumo/network/m3.net.xml`, `sumo/network/m7.net.xml`, and `sumo/simulation/m0.sumocfg`.

SHA-256 over raw file bytes changes when newline bytes change, even if parsed CSV/JSON/YAML/XML content is unchanged. Git object identity and filesystem SHA-256 are different checks. Other tracked text files may also be exposed to conversion under a different checkout policy. The preservation helpers use raw-byte hashes, so a content-equivalent checkout need not reproduce historical digests. This newline issue does not establish the cause of the separate 509 M8 discrepancies. No newline normalization or Git configuration change was performed.

## Inspecting existing findings without executing experiments

Use the [final evidence inventory](../reports/final_project/final_evidence_inventory.md) and the milestone methods under `docs/`. Inspect these tracked result locations:

| Milestone | Evidence location |
|---|---|
| M0-M2 | `TASKS.md` historical verification, configuration/network sources, and `reports/m2/` metrics/figures; historical raw inputs are incomplete in Git. |
| M3 | `reports/m3/m3_git_demo_01/` metrics/figures; distinct final-verification evidence remains external as disclosed above. |
| M4/M5 | `reports/m4/m4_final_02/` and `reports/m5/m5_final_02/`: summaries, per-scenario metrics, predictions, and figures. |
| M6 | `reports/m6/m6_full_02/` and `reports/m6/m6_full_03/`. |
| M7 | `reports/m7/full_matrix/m7_full_02/` and `reports/m7/full_matrix/m7_full_03/`: paired comparisons, aggregate results, per-run results, and figures. |
| M8 | `reports/m8/stage2b/m8_stage2b_final_02/`: `observation_summary.csv`, `event_summary.csv`, `condition_summary.csv`, and `trip_metrics.csv`. |
| M9 | Corrected canonical `reports/m9/m9_stage2_final_03/` and `reports/m9/m9_stage2_final_04/`: `normal_false_positive_metrics.csv`, `attack_event_summary.csv`, `trip_metrics.csv`, `prediction_coverage.csv`, and overlap/ledger evidence. |

[M9 methods](M9_DETECTOR_ERROR_ANALYSIS.md#reproducibility-preservation-and-limits) explicitly designate `_03/_04` as canonical after reporting-aggregation corrections. `_01/_02` remain historical audit runs; do not replace them, overwrite them, or cite them as the corrected final summaries. The methods record unchanged predictions, labels, thresholds, and policies across that reporting correction.

For committed bytes independent of local path edits or checkout newlines, use read-only commands such as:

```powershell
git show HEAD:reports/m9/m9_stage2_final_03/normal_false_positive_metrics.csv
git show HEAD:reports/m9/m9_stage2_final_03/attack_event_summary.csv
git ls-tree -r --name-only HEAD -- reports/m9/m9_stage2_final_03
git ls-files --eol -- reports/m7 reports/m9
```

Read metrics with their eligibility denominators, trip/profile/seed grouping, and method definitions. Inspecting tables and predictions does not independently validate every historical computation. The documentation audit did not rerun experiments or tests; some tests generate simulation artifacts.

## Conditions for future regeneration

The recorded local environment includes Python 3.14.6, SUMO/TraCI 1.28.0, PyYAML 6.0.3, and Matplotlib 3.11.2. SUMO, `netconvert`, and `netgenerate` were available. The README gives installation/verification guidance; only dashboard requirements have a tracked requirements file, and the core environment has no central lock manifest.

A future reproduction needs compatible software, authorized access to missing inputs, resolution of historical preservation prerequisites, and fresh output IDs. Do not substitute new data for historical inputs silently, edit manifests to suppress discrepancies, or treat a successful new run as proof of historical byte identity. M6-M8 generation workflows may be regenerable with their supplied inputs and environment, but clean-clone execution was not tested here. M9 remains blocked by the documented preservation checks. Further work on packaging or preservation policy requires a separate decision; no such implementation is part of this correction.

## Master's report Appendix B wording — integrated

The M0-M9 checkpoint provides inspectable source code, configurations, methods, and substantial result tables, predictions, and figures, but it is not a self-contained package for independently reproducing every historical experiment from a clean clone. In addition to the three previously listed local-only M1/M2 inputs, nine distinct CSV inputs referenced by the M4/M5 configuration are absent from Git. Unique M3 final-verification evidence remains in the external historical project. Exact input names and evidence locations are documented in `docs/REPRODUCIBILITY_LIMITATIONS.md`.

The frozen M9 preservation manifest references 1,061 files absent from Git. Although all preservation prerequisites were present in the audited local workspace, 509 M8 files (434 YAML and 75 XML) differed from the manifest's raw-byte SHA-256 values while matching the committed checkpoint. These are unresolved historical-byte discrepancies, not demonstrated changes to numerical research findings. Available local Git evidence does not establish their cause or the disappearance of the earlier working-tree differences. The present M9 final evaluator would reject these mismatches; historical successful preservation checks should not be interpreted as current clean-clone reproducibility.

Windows Git newline conversion can also change filesystem SHA-256 values without changing parsed experimental content. Raw-byte preservation therefore requires compatible file representation as well as matching scientific inputs. This issue does not explain the 509 M8 discrepancies without further evidence. No results, preservation manifests, checksums, or Git settings were changed to resolve either limitation.

The corrected canonical M9 final results are in `reports/m9/m9_stage2_final_03/` and `reports/m9/m9_stage2_final_04/`; earlier `_01/_02` runs remain audit history. Researchers can inspect the committed summaries, per-trip metrics, predictions, and figures through the evidence inventory even where historical reproduction is blocked. Future regeneration requires the documented environment and inputs, satisfied preservation prerequisites, and new output IDs. No experiment or test was rerun for this documentation correction.

## Decisions still requiring review

- Advisor and institutional review of the updated report, including the title and expanded reproducibility disclosure.
- Whether and how missing inputs and external evidence may be distributed in a separate authorized archive.
- How to preserve the historical M9 baseline while enabling future reproduction; the provenance of the 509 M8 discrepancies remains unresolved.
- The future environment/newline policy for comparing raw-byte hashes, without retroactively changing historical evidence.
