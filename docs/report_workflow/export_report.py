"""Export the isolated working DOCX with installed Word; never save the DOCX."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid


WORKFLOW_DIR = Path(__file__).resolve().parent
WORKING_DOCX = WORKFLOW_DIR / "SOUTHERN_UNIVERSITY_MASTERS_REPORT_WORKING_v004_ADVISOR_REVIEW_DRAFT.docx"
OUTPUT_DIR = WORKFLOW_DIR / "output"

# Use the installed Windows PowerShell COM bridge: no pywin32 dependency.
# Field/TOC update methods are deliberately absent. Word still paginates for PDF.
WORD_EXPORT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$reportWord = $null
$reportDocument = $null
$reportSettingsCaptured = $false
try {
    $reportWord = New-Object -ComObject Word.Application
    $reportWord.Visible = $false
    $reportWord.DisplayAlerts = 0
    $reportWord.AutomationSecurity = 3
    $reportFieldsAtPrint = $reportWord.Options.UpdateFieldsAtPrint
    $reportLinksAtPrint = $reportWord.Options.UpdateLinksAtPrint
    $reportLinksAtOpen = $reportWord.Options.UpdateLinksAtOpen
    $reportSettingsCaptured = $true
    $reportWord.Options.UpdateFieldsAtPrint = $false
    $reportWord.Options.UpdateLinksAtPrint = $false
    $reportWord.Options.UpdateLinksAtOpen = $false

    if (Test-Path -LiteralPath $env:REPORT_EXPORT_TEMP_PDF) {
        throw 'Temporary PDF destination already exists; export refused.'
    }
    # ConfirmConversions=false, ReadOnly=true, AddToRecentFiles=false.
    $reportDocument = $reportWord.Documents.Open(
        $env:REPORT_EXPORT_WORKING_DOCX, $false, $true, $false
    )
    if ($null -eq $reportDocument) {
        throw 'Word automation did not return an opened document.'
    }
    $reportPageCount = $reportDocument.ComputeStatistics(2)
    # Explicit types avoid PowerShell COM argument conversion errors in Word 2010.
    [string]$reportPdfPath = $env:REPORT_EXPORT_TEMP_PDF
    [int]$reportPdfFormat = 17
    $reportDocument.SaveAs([ref]$reportPdfPath, [ref]$reportPdfFormat)
    if (-not (Test-Path -LiteralPath $env:REPORT_EXPORT_TEMP_PDF -PathType Leaf)) {
        throw 'Word returned without producing a PDF.'
    }
    @{ pages = [int]$reportPageCount; word_version = [string]$reportWord.Version } |
        ConvertTo-Json -Compress | Write-Output
} finally {
    try {
        if ($null -ne $reportDocument) { $reportDocument.Close(0) }
    } finally {
        if ($null -ne $reportWord) {
            try {
                if ($reportSettingsCaptured) {
                    $reportWord.Options.UpdateFieldsAtPrint = $reportFieldsAtPrint
                    $reportWord.Options.UpdateLinksAtPrint = $reportLinksAtPrint
                    $reportWord.Options.UpdateLinksAtOpen = $reportLinksAtOpen
                }
            } finally { $reportWord.Quit() }
        }
    }
}
"""


def sha256(path: Path) -> str:
    """Return a raw-byte digest to verify the working DOCX was not saved."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def destination(name: str | None) -> Path:
    """Choose a PDF leaf name inside output, refusing existing destinations."""
    if name is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"masters_report_{stamp}_{uuid.uuid4().hex[:8]}.pdf"
    if (
        not name
        or Path(name).name != name
        or any(character in name for character in '\\/:*?"<>|')
        or not name.lower().endswith(".pdf")
    ):
        raise ValueError("--output-name must be a simple .pdf filename, without a path.")
    target = OUTPUT_DIR / name
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {target}")
    return target


def export_pdf(target: Path, source: Path = WORKING_DOCX) -> dict[str, object]:
    """Run Word once, verify its output, and publish using exclusive creation."""
    if os.name != "nt":
        raise RuntimeError("This workflow requires Windows and installed Microsoft Word.")
    powershell = shutil.which("powershell.exe")
    if not powershell:
        raise RuntimeError("Windows PowerShell (powershell.exe) was not found.")
    source = source.resolve()
    if source.suffix.lower() != ".docx":
        raise ValueError("--input-docx must select a .docx file.")
    if not source.is_file():
        raise FileNotFoundError(f"Working copy not found: {source}")
    if not OUTPUT_DIR.is_dir():
        raise FileNotFoundError(f"Output directory not found: {OUTPUT_DIR}")
    before = sha256(source)
    with tempfile.TemporaryDirectory(prefix="masters_report_export_") as scratch:
        temporary_pdf = Path(scratch) / "export.pdf"
        environment = os.environ.copy()
        environment["REPORT_EXPORT_WORKING_DOCX"] = str(source)
        environment["REPORT_EXPORT_TEMP_PDF"] = str(temporary_pdf)
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", WORD_EXPORT],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if sha256(source) != before:
            raise RuntimeError("Working DOCX checksum changed; PDF publication stopped.")
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "No error details returned."
            raise RuntimeError(f"Microsoft Word automation failed; no retry was attempted.\n{detail}")
        try:
            metadata = json.loads(result.stdout.strip().lstrip("\ufeff"))
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Word automation output: {result.stdout!r}") from exc
        data = temporary_pdf.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise RuntimeError("Word output does not have a PDF header.")
        # Word's ordinary PDF export uses one /Type /Page dictionary per page.
        pdf_pages = len(re.findall(rb"/Type\s*/Page\b", data))
        word_pages = int(metadata["pages"])
        if not word_pages or pdf_pages != word_pages:
            raise RuntimeError(
                f"Page-count verification failed: Word={word_pages}, PDF={pdf_pages}."
            )
        # Exclusive mode guarantees an existing PDF is never overwritten, even
        # if another process creates the requested name after the initial check.
        with target.open("xb") as output:
            output.write(data)
        return {
            "source_docx": str(source),
            "pdf": str(target),
            "pages": pdf_pages,
            "bytes": len(data),
            "word_version": metadata["word_version"],
            "working_docx_unchanged": True,
            "fields_or_contents_explicitly_updated": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-name", help="Optional unused PDF filename inside output/.")
    parser.add_argument(
        "--input-docx",
        type=Path,
        help="Alternative DOCX; relative paths are resolved inside report_workflow/.",
    )
    args = parser.parse_args()
    try:
        target = destination(args.output_name)
        source = args.input_docx or WORKING_DOCX
        if not source.is_absolute():
            source = WORKFLOW_DIR / source
        details = export_pdf(target, source)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(details, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
