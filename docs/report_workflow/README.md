# Master's report PDF export workflow in VS Code

The default input is `SOUTHERN_UNIVERSITY_MASTERS_REPORT_WORKING_v004_ADVISOR_REVIEW_DRAFT.docx`. Earlier working copies, original reports, and archived copies remain unchanged.

## Requirements

- Windows, Python 3, Windows PowerShell, and installed desktop Microsoft Word.
- Run from your normal Windows desktop account where Word is available.
- No additional Python packages or software installation is required; Python invokes Word through PowerShell COM automation.

## Export v004

From the research repository root in the VS Code PowerShell terminal:

```powershell
python -B docs/report_workflow/export_report.py
```

From `docs/report_workflow` instead:

```powershell
python -B export_report.py
```

Each default export creates a unique timestamp-and-random-suffix PDF under `docs/report_workflow/output/`. The script prints its exact path, selected DOCX, page count, byte size, Word version, and source-checksum verification outcome.

To choose an unused output filename:

```powershell
python -B docs/report_workflow/export_report.py --output-name v004_advisor_review_02.pdf
```

## Select another DOCX version

Use `--input-docx`. Relative input paths are resolved against `docs/report_workflow/`, regardless of your terminal directory. Absolute paths are also accepted. Only existing `.docx` inputs are accepted.

```powershell
python -B docs/report_workflow/export_report.py --input-docx SOUTHERN_UNIVERSITY_MASTERS_REPORT_WORKING_v003_A4_FORMATTED.docx
```

This exports the selected version read-only; it does not change the default or modify that DOCX. The initial `SOUTHERN_UNIVERSITY_MASTERS_REPORT_WORKING.docx` is retained for history and is no longer the default input.

## Safety and limitations

- Existing PDFs are refused, including if another process creates the destination during export. Final output uses exclusive creation.
- Word first exports to a private temporary directory using its PDF SaveAs format. Only a successful output with a valid PDF header and matching Word/PDF page counts is published to `output/`.
- The selected DOCX is opened read-only and closed without saving. Its SHA-256 must remain unchanged before publication.
- Macros and automatic field/link updates at printing and link updates at opening are disabled for this Word instance; prior option values are restored afterward.
- This export does not explicitly update fields, the table of contents, or the figure list. V004 already contains updated navigation. After future report edits, updating navigation requires a separate authorized document-editing step; export alone does not validate page references.
- Pagination can depend on the Word version and installed fonts. V004 is expected to export to 34 pages in the verified environment. Inspect new PDFs before distribution.
- If Word automation fails, the script stops and reports the error without retrying, using another converter, or publishing a final PDF.
- Run one export at a time and save/close interactive edits to the selected DOCX first. Only the automation instance is closed; unrelated Word processes are not terminated.
- The workflow does not run experiments, change research data, modify archived files, or perform Git operations.
