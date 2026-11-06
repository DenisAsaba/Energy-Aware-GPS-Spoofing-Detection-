# M4: GPS spoofing detection and evaluation

## Objective and detector status

M4 evaluates a deterministic position-residual threshold against one existing
M2 normal-GPS trip and the M3 offset, jump, and drift datasets. The detector
computes

`r_t = sqrt((gps_x_m - x_m)^2 + (gps_y_m - y_m)^2)`

and predicts attack when `r_t > threshold_m`. A residual exactly equal to the
threshold is classified as normal. Coordinates and residuals are meters in
SUMO's local road X/Y frame; time is in seconds.

This is an **oracle-assisted offline research baseline**. It reads simulation
ground-truth `x_m/y_m` to calculate residuals and calibrate its threshold, so it
is not a GPS-only or deployable detector. The prediction function accepts only
truth and GPS paths; attack labels are loaded later by the evaluator. Prediction
CSVs do not contain labels. Ground truth, GPS, labels, predictions, and
evaluation metrics remain separate files.

## Calibration and data split

The fixed threshold is calibrated from M2 normal-GPS residuals only. The
chronologically ordered M2 records are divided at the configured
`calibration_fraction` (0.5): the first 39 of 79 matched records calibrate the
threshold, and the remaining 40 measure normal false alarms. The configured
`normal_quantile` is 0.95; NumPy's linear-interpolation `quantile` is used. The
threshold is then fixed for all attack evaluation. M3 attack labels and final
attack metrics never select or tune it.

With the configured files, the threshold is **6.999907 m**. This split is
chronological within one trip, not a held-out-trip validation: the repository
currently provides only one M2 baseline trip and one attack trip per class.
The result is a baseline demonstration, not a generalization estimate.

## Inputs, matching, and outputs

Configuration is in `config/experiment_config.yaml` under `m4`. M2 and M3
inputs are selected explicitly there from their existing ignored output files.
Every residual and label join uses the existing exact `(time_s, vehicle_id)`
key convention. GPS without matching truth is excluded from residual
predictions and reported; labels without a prediction and predictions without
a label are counted separately and excluded from confusion metrics.

Normal predictions are written for all matched M2 observations, with a
`calibration` or `evaluation` split marker. Only the 40-record normal
evaluation suffix contributes to the normal confusion metrics and normal
time-series panel. Offset, jump,
and drift use all their matched records, including inactive pre/post-attack
records. Route deviation is intentionally excluded because it is a physical
trip on a different route with its own truth.

Each run uses a new output ID and refuses to overwrite an existing run folder:

```powershell
python -m src.detection.gps_spoofing --config config/experiment_config.yaml --run-id m4_reproduction_01
python -m unittest discover -s tests -v
```

The verified example outputs are `reports/m4/m4_final_01/` and
`reports/m4/m4_final_02/`; their 13 non-run-metadata artifacts are byte-identical.
The configured output is `reports/m4/<run-id>/` and contains four
per-observation prediction CSVs, four per-scenario metric JSON files, a
combined `summary.csv`, a run metadata record and config snapshot, plus:

- `confusion_matrices.png`: one confusion matrix each for normal, offset,
  jump, and drift.
- `attack_scores.png`: precision, recall, and F1 comparison for the three
  attacks.
- `residuals_labels_predictions.png`: residual, threshold, offline attack
  label, and detector prediction over time for normal and each attack.

All visualizations and metrics are generated from the same keyed prediction
records. The normal label is synthesized as zero only in the evaluator; no
normal labels are written into GPS or prediction inputs.

## Metrics

For binary labels, TP/FP/TN/FN have their standard definitions. Precision is
`TP/(TP+FP)`, recall is `TP/(TP+FN)`, F1 is the harmonic mean of precision and
recall, false-positive rate is `FP/(FP+TN)`, and accuracy is
`(TP+TN)/(TP+FP+TN+FN)`. Any undefined ratio caused by a zero denominator is
reported as `0.0`; no observations also yields accuracy `0.0`. Detection delay
is the first active-label sample classified as attack, minus the first
active-label sample time. A missed attack has null delay.

## Verified results

Results below were generated with the configured threshold and existing
M2/M3 data. All scenarios had zero unmatched GPS/truth records and zero
unmatched prediction/label records.

| Scenario | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Accuracy | Delay (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal M2 holdout | 0 | 2 | 38 | 0 | 0.0000 | 0.0000 | 0.0000 | 0.0500 | 0.9500 | — |
| Offset | 30 | 3 | 46 | 0 | 0.9091 | 1.0000 | 0.9524 | 0.0612 | 0.9620 | 0 |
| Jump | 5 | 4 | 70 | 0 | 0.5556 | 1.0000 | 0.7143 | 0.0541 | 0.9494 | 0 |
| Drift | 27 | 3 | 46 | 3 | 0.9000 | 0.9000 | 0.9000 | 0.0612 | 0.9241 | 2 |

The normal evaluation uses 40 records after 39 calibration records. The attack
scenarios each use 79 records and their configured active intervals. These
figures describe the existing deterministic synthetic trips only. The
oracle-assisted residual has direct access to true position, and the three
attack patterns have different intensities and active durations; this is not a
comparison of deployable detection systems or held-out-trip performance.

## Limitations

- Ground truth is privileged information required by this residual detector.
- Only one trip is available for normal calibration and each attack scenario;
  a trip-level generalization claim is not supported.
- The threshold is a configured normal-only quantile, not optimized on attack
  test labels. The small calibration sample makes it sensitive to individual
  normal errors.
- M2's independent Gaussian coordinate noise and SUMO's artificial metric map
  do not reproduce receiver-level GNSS behavior.
- Route deviation, motion consistency, temporal filters, machine learning,
  route selection, and energy causality are outside M4.
