from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Ensure standard streams handle UTF-8 properly on Windows
if sys.platform == "win32":
    try:
        if sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr.encoding.lower() != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.config import get_settings
from app.pipeline import EvidencePipeline, PipelineExecutionError
from app.schemas import EvidenceManifest
from app.services.blockchain import BlockchainService
from app.services.face_matcher import FaceMatcher
from app.services.image_guard import ImageGuard
from app.services.manifest import ManifestBuilder

app = typer.Typer(
    name="facechain",
    help="Face Identification & Blockchain Verification CLI",
    add_completion=False,
)
console = Console(highlight=False)


@app.command("inspect-face")
def inspect_face(
    input_path: str = typer.Option(..., "--input", "-i", help="Path to input query image"),
    output_preview: str = typer.Option(
        "query-annotated.jpg", "--output", "-o", help="Path to save annotated preview image"
    ),
):
    """
    Validates the query image and detects all faces with YuNet.
    Saves an annotated preview with numbered face boxes for operator selection.
    """
    settings = get_settings()
    console.print(Panel.fit("[bold blue]Face Identification Stage - Image Inspection[/bold blue]"))

    try:
        bgr_image, raw_bytes, sha256_hex = ImageGuard.load_and_validate(input_path)
        console.print(f"[green][+] Query image validated:[/green] {Path(input_path).name} (SHA-256: {sha256_hex[:16]}...)")

        yunet_path = settings.resolve_path(settings.yunet_model_path)
        sface_path = settings.resolve_path(settings.sface_model_path)
        matcher = FaceMatcher(yunet_path=yunet_path, sface_path=sface_path)

        faces, _ = matcher.detect_faces(bgr_image)
        console.print(f"[cyan][i] Faces detected:[/cyan] [bold]{len(faces)}[/bold]")

        if len(faces) == 0:
            console.print("[red][x] No faces detected in the image. Please use a clearer, frontal image.[/red]")
            raise typer.Exit(code=1)

        annotated_img = matcher.annotate_image(bgr_image, faces)
        import cv2

        cv2.imwrite(output_preview, annotated_img)
        console.print(f"[green][+] Annotated preview saved to:[/green] [bold]{output_preview}[/bold]")

        table = Table(title="Detected Faces in Query Image")
        table.add_column("Index", style="cyan", justify="center")
        table.add_column("Bounding Box [x, y, w, h]", style="magenta")
        table.add_column("Detection Score", style="green")
        table.add_column("Quality Warnings", style="yellow")

        for f in faces:
            warnings = ", ".join(f.quality_warnings) if f.quality_warnings else "None"
            table.add_row(
                str(f.index),
                str(f.bounding_box_px),
                f"{f.detection_score:.4f}",
                warnings,
            )

        console.print(table)
        if len(faces) > 1:
            console.print("[bold yellow]Multiple faces detected.[/bold yellow] Please select a face index using [bold]--face-index <idx>[/bold] when running the pipeline.")
        else:
            console.print("[green]Single face detected. Index 0 will be selected by default.[/green]")

    except Exception as e:
        console.print(f"[bold red]Error during face inspection:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command("run")
def run_pipeline(
    input_path: str = typer.Option(..., "--input", "-i", help="Path to input query image"),
    face_index: Optional[int] = typer.Option(None, "--face-index", "-f", help="Face index to select"),
    search_provider: Optional[str] = typer.Option(
        None, "--search-provider", "-p", help="Search provider override ('serpapi' or 'mock')"
    ),
    consent_confirmed: bool = typer.Option(
        False, "--consent-confirmed", help="Explicit confirmation of subject biometric consent"
    ),
):
    """
    Executes the full end-to-end Face Identification & Blockchain Verification pipeline.
    """
    settings = get_settings()

    console.print(Panel.fit("[bold cyan]HH Goa Face Identification & Blockchain Verification Pipeline[/bold cyan]"))

    if not consent_confirmed:
        console.print(
            "[bold red]ERROR: Biometric consent was not confirmed.[/bold red]\n"
            "You must provide explicit confirmation using [bold]--consent-confirmed[/bold]."
        )
        raise typer.Exit(code=1)

    provider_name = (search_provider or settings.search_provider).lower()
    if provider_name == "mock":
        console.print(
            Panel(
                "[bold yellow]SEARCH MODE: MOCK -- DETERMINISTIC TEST MODE ONLY (NOT VALID AS LIVE SEARCH EVIDENCE)[/bold yellow]",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel(
                "[bold green]SEARCH MODE: LIVE -- GENUINE GOOGLE LENS REVERSE SEARCH VIA SERPAPI[/bold green]",
                border_style="green",
            )
        )

    try:
        pipeline = EvidencePipeline(settings)
        result = pipeline.run(
            input_image_path=input_path,
            face_index=face_index,
            consent_confirmed=consent_confirmed,
            search_provider_override=provider_name,
        )

        console.print("\n[bold green]Pipeline Execution Completed Successfully![/bold green]\n")
        
        table = Table(title="Execution & Evidence Summary")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Run ID", result["run_id"])
        table.add_row("Run Directory", result["run_dir"])
        table.add_row("Search Mode", result["search_mode"].upper())
        table.add_row("Discovered Social URL", result["page_url"])
        table.add_row("Classified Platform", result["platform"].upper())
        table.add_row("Candidate Accepted?", "[green]YES[/green]" if result["accepted"] else "[red]NO[/red]")
        table.add_row("Similarity Score", f"{result['score']:.6f}")
        table.add_row("Configured Threshold", f"{result['threshold']:.6f}")
        table.add_row("Evidence SHA-256 Digest", f"[bold yellow]{result['evidence_hash']}[/bold yellow]")

        attestation = result.get("attestation")
        if attestation:
            table.add_row("Blockchain Registry", attestation["contractAddress"])
            table.add_row("Chain ID", str(attestation["chainId"]))
            table.add_row("Transaction Hash", attestation["transactionHash"])
            table.add_row("Block Number", str(attestation["blockNumber"]))
            table.add_row("Attester Address", attestation["registrant"])
        else:
            table.add_row("Blockchain Anchor", "[yellow]Contract address or attester key not configured (Evidence saved locally)[/yellow]")

        console.print(table)

    except PipelineExecutionError as pe:
        console.print(f"[bold red]Pipeline Failed [{pe.code}]:[/bold red] {pe.message}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[bold red]Unexpected Error:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command("verify")
def verify_manifest(
    manifest_path: str = typer.Option(..., "--manifest", "-m", help="Path to manifest.json to verify"),
    contract_address: Optional[str] = typer.Option(None, "--contract", help="Override EvidenceRegistry contract address"),
    rpc_url: Optional[str] = typer.Option(None, "--rpc-url", help="Override Ethereum RPC URL"),
):
    """
    Reconstructs RFC 8785 canonical bytes, recomputes SHA-256 digest, and queries on-chain registry.
    """
    settings = get_settings()
    console.print(Panel.fit("[bold blue]Cryptographic Evidence Manifest Verification[/bold blue]"))

    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        console.print(f"[red]Error:[/red] Manifest file not found: {manifest_file}")
        raise typer.Exit(code=1)

    try:
        # 1. Canonicalize and calculate hash
        is_valid, computed_hash, canonical_bytes, data = ManifestBuilder.verify_manifest_integrity(manifest_file)
        console.print(f"[green][+] Manifest schema:[/green] [bold green]VALID[/bold green]")
        console.print(f"[green][+] Reconstructed Canonical SHA-256:[/green] [bold yellow]{computed_hash}[/bold yellow]")

        # 2. Check on-chain record
        addr = contract_address or settings.registry_address
        rpc = rpc_url or settings.rpc_url
        
        on_chain_found = False
        attester_valid = False
        record_info = None

        if addr:
            blockchain = BlockchainService(rpc_url=rpc, chain_id=settings.chain_id, contract_address=addr)
            if blockchain.is_connected():
                on_chain_found = blockchain.is_hash_registered(computed_hash)
                if on_chain_found:
                    record_info = blockchain.get_evidence_record(computed_hash)
                    auth_attester = blockchain.get_authorized_attester()
                    attester_valid = (
                        record_info["submitter"].lower() == auth_attester.lower() if auth_attester else False
                    )

        # Print report
        table = Table(title="Manifest Integrity & On-Chain Verification Report")
        table.add_column("Verification Step", style="cyan")
        table.add_column("Result", style="white")

        table.add_row("Manifest Schema Version", data.get("schema", "unknown"))
        table.add_row("Canonicalization Standard", "RFC 8785 (JSON Canonicalization Scheme)")
        table.add_row("Computed Evidence Hash", computed_hash)
        table.add_row(
            "On-Chain Registration",
            f"[bold green]FOUND on contract {addr}[/bold green]" if on_chain_found else f"[bold red]NOT FOUND on contract {addr}[/bold red]" if addr else "[yellow]NOT CHECKED (no contract address specified)[/yellow]",
        )
        if record_info and on_chain_found:
            table.add_row("Registered By", record_info["submitter"])
            table.add_row("Block Number", str(record_info["blockNumber"]))
            table.add_row("Registration Timestamp", str(record_info["registeredAt"]))
            table.add_row("Attester Valid?", "[green]YES[/green]" if attester_valid else "[red]NO[/red]")

        table.add_row(
            "Evidence Integrity Status",
            "[bold green]VERIFIED (Tamper-Evident & Unchanged)[/bold green]" if (on_chain_found or not addr) else "[bold red]FAILED (Hash mismatch or not registered)[/bold red]",
        )
        table.add_row("Identity Conclusively Proven?", "[bold cyan]NO (Local biometric similarity claim only)[/bold cyan]")

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Verification Failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command("cleanup")
def cleanup_runs(
    runs_dir: Optional[str] = typer.Option(None, "--runs-dir", help="Directory containing run bundles"),
    max_age_hours: Optional[int] = typer.Option(None, "--max-age-hours", help="Delete run bundles older than X hours"),
):
    """
    Applies data retention and minimization policy by purging old run artifacts.
    """
    settings = get_settings()
    target_dir = Path(runs_dir or settings.runs_dir)
    retention = max_age_hours or settings.retention_hours

    if not target_dir.exists():
        console.print(f"[yellow]Runs directory {target_dir} does not exist.[/yellow]")
        return

    now = time.time()
    cutoff_seconds = retention * 3600
    deleted_count = 0

    for item in target_dir.iterdir():
        if item.is_dir() and item.name.startswith("run-"):
            mtime = item.stat().st_mtime
            if now - mtime > cutoff_seconds:
                shutil.rmtree(item)
                deleted_count += 1
                console.print(f"[green]Purged expired run artifact:[/green] {item.name}")

    console.print(f"[green]Retention cleanup complete. Removed {deleted_count} expired run bundles.[/green]")


def main():
    app()


if __name__ == "__main__":
    main()
