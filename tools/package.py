import argparse
import hashlib
import importlib.resources
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = ("plugin.json", "requirements.txt", "launch.py", "README.md", "icons", "kicad2cnc")


def _package_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for item in PACKAGE_FILES:
        path = ROOT / item
        if not path.exists():
            raise FileNotFoundError(f"Required package input is missing: {path}")
        if path.is_file():
            files.append(path)
        else:
            files.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file() and "__pycache__" not in child.parts and child.suffix != ".pyc"
            )
    return tuple(files)


def _metadata(args: argparse.Namespace, archive: Path, files: tuple[Path, ...]) -> dict[str, object]:
    archive_bytes = archive.read_bytes()
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    schema_path = importlib.resources.files("kipy").joinpath(
        "packaging", "schemas", "pcm.v2.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    metadata: dict[str, object] = {
        "name": "KiCad to CNC",
        "description": "Export PCB Gerbers and drills, then generate per-tool GRBL-oriented CNC files.",
        "description_full": (
            "An IPC plugin for KiCad 10 that exports Gerber and Excellon files and can "
            "use pcb2gcode to generate per-tool GRBL-oriented CNC output. "
            "Machine compatibility and physical setup must be verified by the operator."
        ),
        "identifier": manifest["identifier"],
        "type": "plugin",
        "author": {"name": args.author, "contact": {}},
        "license": args.license,
        "resources": {"Homepage": args.project_url},
        "tags": ["pcb", "cnc", "gerber"],
        "versions": [{
            "version": args.version,
            "download_url": args.download_url,
            "download_sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "download_size": len(archive_bytes),
            "install_size": sum(path.stat().st_size for path in files),
            "status": "testing",
            "platforms": ["windows"],
            "runtime": "ipc",
            "kicad_version": "10.0",
        }],
    }
    jsonschema.Draft7Validator(schema).validate(metadata)
    return metadata


def build_package(args: argparse.Namespace) -> tuple[Path, Path]:
    files = _package_files()
    output_directory = args.output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    archive_path = output_directory / f"kicad2cnc-{args.version}.zip"
    metadata_path = output_directory / "metadata.json"
    existing = [path for path in (archive_path, metadata_path) if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite package output: " + ", ".join(str(path) for path in existing)
        )

    with tempfile.TemporaryDirectory(prefix=".kicad2cnc-package-", dir=output_directory) as temporary:
        temporary_directory = Path(temporary)
        staged_archive = temporary_directory / archive_path.name
        with zipfile.ZipFile(staged_archive, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(ROOT).as_posix())
        metadata = _metadata(args, staged_archive, files)
        staged_metadata = temporary_directory / metadata_path.name
        staged_metadata.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        published: list[Path] = []
        try:
            for staged, destination in (
                (staged_archive, archive_path),
                (staged_metadata, metadata_path),
            ):
                with staged.open("rb") as source, destination.open("xb") as target:
                    published.append(destination)
                    shutil.copyfileobj(source, target)
        except OSError:
            for path in published:
                path.unlink(missing_ok=True)
            raise
    return archive_path, metadata_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a KiCad PCM v2 package; supply authoritative project metadata."
    )
    parser.add_argument("--version", required=True, help="Package version, e.g. 1.0.0")
    parser.add_argument("--author", required=True, help="Author name as it should appear in PCM")
    parser.add_argument("--license", required=True, help="Exact SPDX identifier or project license name")
    parser.add_argument("--project-url", required=True, help="Public project/homepage URL")
    parser.add_argument("--download-url", required=True, help="Direct public URL for this version's ZIP")
    parser.add_argument(
        "--output-directory", type=Path, default=ROOT / "dist",
        help="Output directory (default: dist)",
    )
    args = parser.parse_args(argv)
    try:
        archive, metadata = build_package(args)
    except (OSError, ValueError, jsonschema.ValidationError) as error:
        print(f"Package creation failed: {error}", file=sys.stderr)
        return 1
    print(f"Package: {archive}")
    print(f"PCM metadata: {metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
