# Plan: KiCad → CNC G-code Extension ("kicad2cnc")

A KiCad 10 plugin that, from the open PCB, exports Gerber + Excellon drill files and
converts copper routing (isolation milling), Edge.Cuts (board outline), and drills
into GRBL-compatible G-code — with double-sided board support.

---

## 1. Key constraints (researched, KiCad 10 reality)

| Fact | Consequence |
|---|---|
| IPC API in KiCad 9/10 has **no plot/export support** (added in KiCad 11) | Gerber/drill export must shell out to `kicad-cli` |
| SWIG `pcbnew` API is **deprecated, removed in KiCad 11** | Do not build on SWIG; use the IPC API (`kicad-python` / kipy) |
| IPC API in KiCad 9/10 requires a **running KiCad GUI** with the API server enabled | Plugin runs as an external process launched from the PCB Editor toolbar |
| `kicad-cli pcb export gerbers` / `pcb export drill` cover everything needed | Reliable, scriptable export path that survives into KiCad 11 |
| `pcb2gcode` v3.1.0 is actively maintained; does isolation, outline (with bridges/tabs), drill, back-side mirroring | Wrap it as conversion backend instead of writing a custom converter |
| GRBL lacks canned cycles (G81) and M6 tool change | Use `--nog81`; `--nom6` only where supported. M4 splits output per tool |
| pcb2gcode does **not** generate alignment holes for double-sided work | M5 adds optional manually positioned, through-board registration holes; fixture alignment remains operator-verified |

**Decision: wrap pcb2gcode.** A custom Gerber→G-code converter means writing a
RS-274X parser, polygon offsetting (Voronoi/isolation geometry), arc handling, and
tab generation — months of work pcb2gcode already does well. The plugin's value is
integration, configuration UX, and GRBL post-processing.

## 2. Architecture

```
KiCad 10 PCB Editor (GUI, API server enabled)
   │  toolbar button (IPC API plugin, runtime: python)
   ▼
kicad2cnc plugin process
   ├── kipy (kicad-python): read board info ── board path, Edge.Cuts sanity check,
   │                                            copper layers in use, origin
   ├── step 1: subprocess → kicad-cli pcb export gerbers  (F.Cu, B.Cu, Edge.Cuts)
   ├── step 2: subprocess → kicad-cli pcb export drill    (Excellon, PTH/NPTH)
   ├── step 3: generate `millproject` config + subprocess → pcb2gcode
   │             → front.ngc, back.ngc, outline.ngc, drill.ngc
   └── step 4: GRBL post-processor (Python)
                 → validated per-tool .nc files + job summary (README_job.txt)
```

- **Plugin type:** IPC API plugin, `plugin.json` (schema `go.kicad.org/api/schemas/v1`),
  `runtime.type = "python"` so KiCad auto-creates a venv and installs
  `kicad-python` (imported as `kipy`) and its dependencies from `requirements.txt`.
- **GUI:** a small wxPython dialog (KiCad 10's bundled Python lacks working Tk support)
  with tabs: *Export*, *Isolation*, *Drill*, *Outline*, *Post/GRBL*. Persist settings
  per-project in `<project>.kicad2cnc.json` next to the board file.
- **Tool discovery:** locate `kicad-cli` relative to the running KiCad install
  (e.g. `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`, or from `PATH`);
  locate `pcb2gcode` from `PATH` or a user-configured path; clear error dialogs
  with download links when missing.

## 3. Repository layout

```
kicad2cnc/
├── plugin.json                  # IPC plugin manifest (identifier, actions, runtime)
├── requirements.txt             # kipy, (tkinter is stdlib)
├── icons/light.png, dark.png
├── kicad2cnc/
│   ├── __main__.py              # entrypoint; connects to KiCad via KICAD_API_SOCKET
│   ├── board_info.py            # kipy queries: board path, layers, outline checks
│   ├── export.py                # kicad-cli gerber + drill invocation
│   ├── gcode.py                 # millproject generation + pcb2gcode invocation
│   ├── post_grbl.py             # G-code post-processing / dialect cleanup
│   ├── settings.py              # dataclasses + JSON persistence (per project)
│   ├── tools.py                 # kicad-cli / pcb2gcode discovery & version checks
│   └── ui/dialog.py             # settings dialog + progress / log pane
├── tests/                       # pytest: unit + golden-file tests
│   └── fixtures/demo.kicad_pcb  # small test board (incl. double-sided variant)
├── pcm/metadata.json            # PCM package metadata (schema v2, runtime: "ipc")
└── README.md
```

## 4. Milestones

### M1 — Skeleton & KiCad integration (the "hello world" plugin)
**Status:** Implemented and verified on KiCad 10.0.7, including an actual toolbar
launch and live board/layer display. Thirteen automated tests cover board info,
manifest validation, dialog errors, and dialog shutdown. See README.md for installation.

- `plugin.json` with one action, toolbar button appears in PCB Editor.
- Entrypoint connects via kipy, reads board filename + enabled layers, shows dialog.
- Always show a save reminder (KiCad 10 IPC has no dirty-state query), with a
  stronger warning if no saved file exists. kicad-cli will read the file on disk.
- **Done when:** button opens a dialog showing correct board info on KiCad 10.

### M2 — Gerber & Excellon export (also satisfies "plain export only" scope)
**Status:** Implemented and installed. Verified on KiCad 10.0.7 with a live
dialog/background export, Gerber viewer loading, and 28 passing tests. Tests check
nonzero-origin copper/outline/hole coordinates and compare Gerber/Excellon
geometry against KiCad's plotter and drill writer with matching settings.

- `kicad-cli pcb export gerbers --layers F.Cu,B.Cu,Edge.Cuts -o <outdir>`
  (one file per layer; users select their populated sides because enabled layers
  alone do not identify single-sided designs). Use `--use-drill-file-origin`
  so Gerbers and drills share coordinates.
- `kicad-cli pcb export drill --excellon-units mm --excellon-separate-th
  --drill-origin plot -o <outdir>`.
- Output directory selector; "export only, no G-code" checkbox.
  Until M3, export-only is locked on. Each run publishes a separate job folder;
  errors never publish partial jobs or overwrite previous exports.
- **Done when:** output loads cleanly in KiCad's Gerber viewer; files match a
  File→Plot reference export.

### M3 — G-code generation via pcb2gcode
**Status:** Implemented and installed. Verified with native pcb2gcode 2.4.0,
the custom-named pic_programmer demo, and a live KiCad 10.0.7 background conversion.
All 52 tests pass, including metric output, mirrored copper extents, drill
coordinates, cut depths, tabs, mill-drill selection, UI controls, and failures.
Machine simulation and physical machining remain user validation steps; M4 is
responsible for post-processing the retained CAM source into per-tool GRBL-oriented
files; neither output has been validated on a physical machine.

Implementation targets native Windows pcb2gcode 2.4.0 (the latest official Windows
binary). Newer Linux releases exist; the executable is configurable and checked
for required capabilities. This build lacks `--nom6`; original CAM files are
retained for review, while M4 post-processes them into separate GRBL-oriented
per-tool files. CNC settings are persisted beside the PCB. Both metric input and
metric output are forced.

- Generate a `millproject` file from dialog settings; run pcb2gcode per side:
  - *Isolation:* `--front/--back`, `--mill-diameters`, `--milling-overlap`,
    `--isolation-width` (or `--voronoi`), `--zwork`, `--mill-feed/-speed`.
  - *Outline:* `--outline` (Edge.Cuts gerber), `--cutter-diameter`, `--zcut`,
    `--cut-infeed` multi-pass, `--bridges/--bridgesnum/--zbridges` (tabs).
  - *Drill:* `--drill`, `--zdrill`, `--drill-feed/-speed`,
    `--milldrill --min-milldrill-hole-diameter` for holes > largest drill bit.
  - Baseline: `--nog81 --nog64 --nog91-1 --metric --metricoutput`,
    `--nom6` when supported.
- Stream pcb2gcode stdout/stderr into the dialog log pane; fail loudly on nonzero exit.
- **Done when:** demo board produces the source CAM files with expected coordinates,
  feeds, depths, and dimensions; the original `.ngc` files are retained for review.

### M4 — GRBL post-processor
**Status:** Implemented and installed for KiCad 10. The full suite passes (56
tests), including live KiCad CLI and native pcb2gcode 2.4.0 integration. The
reported `pic_programmer` board produces 16 individual `.nc` tool files; their
final G/M words pass the allowlist and they contain no tool-change commands.
Each tool operation becomes an ordered `.nc` file and `gcode/grbl/README_job.txt`
records its tool and manual setup. Output enforces an allowlisted GRBL v1.1 subset,
mm/absolute modes, spindle control, dwell settings, and retract/stop sequences.
Unknown commands, mismatched spindle speeds, conflicting coordinate modes, and
missing tool metadata fail the complete staged job. Original converter files are
retained under `gcode/cam/` for inspection and simulation.

- A manual tool-change/Z-zero workflow is required between files; GRBL M6 is not
  emitted. Back copper is mirrored about X=0; M5 adds an optional manually
  positioned through-board registration operation.
- **Done when:** tests confirm one tool per output, safe header/footer, command
  allowlisting, and actual converter integration on drill, isolation, outline,
  and mill-drill examples. No controller/hardware validation is claimed.

### M5 — Double-sided support
**Status:** Implemented for manual through-board registration-hole coordinates and
per-tool drilling output. Coordinate symmetry is validated against the existing
pcb2gcode back-side X mirror. The actual fixture, hole clearances, and physical
two-sided alignment are not validated.

- pcb2gcode mirrors back copper about absolute X=0. The matching 180-degree
  physical rotation is about the Y axis (X changes sign; Y does not).
- Optional registration operation accepts 2-4 manual X,Y coordinates in the
  exported drill/place-origin frame and requires the hole pattern to be symmetric
  about X=0. A separate registration tool file is ordered before board drills.
- When only B.Cu is selected, M5 mirrors drill, outline, and registration output
  about X=0 to match pcb2gcode's mirrored back-copper toolpath. This supports a
  single-sided B.Cu-up setup without flipping the board or requiring registration
  holes; the reflected work origin must still be verified.
- Automatic location suggestions are deferred. Edge bounds alone cannot confirm
  clearance from the actual board contour, copper, components, or clamps; fixture
  design and physical alignment remain the operator's responsibility.
- Job guide: registration drill → board drills → front isolation → verified
  Y-axis flip and re-zero → back isolation → outline last.
- **Done when:** tests verify coordinate parsing/symmetry and actual Excellon/CAM
  conversion; physical alignment still requires user validation.

### M6 — Polish, tests, packaging
**Status:** Implemented and locally verified for tests and package generation.
Added GRBL golden files for front isolation and the B.Cu-only mirrored outline,
plus `tools/test-integration.ps1` to require and run the real KiCad CLI and
pcb2gcode fixture tests without silently skipping missing tools. The PCM v2
builder creates a runtime ZIP and validates generated `metadata.json` against
KiCad's installed schema, including the archive hash and size. Release metadata
requires the project owner to supply the authoritative license, author, homepage,
and versioned download URL; no public PCM submission has been made. Windows is
the only declared package platform and machine/controller validation remains
outside this milestone.

- Golden-file tests lock stable GRBL output, including arc reflection in B.Cu-only
  outline mode.
- `tools/test-integration.ps1` requires KiCad CLI and pcb2gcode and runs the
  real fixture export/CAM tests.
- `tools/package.py` builds a versioned plugin ZIP and PCM schema-v2 metadata
  (`runtime: ipc`, identifier `com.github.mickew.kicad2cnc`); release-specific
  author/license/project/download details are explicit inputs.
- README documents Windows plugin install, pcb2gcode install options, GRBL safety,
  the integration runner, and package creation. No UI screenshots are included.
- **Done when:** unit tests pass; real-tool integration runner passes on the
  installed Windows tools; generated package metadata validates and its recorded
  archive hash/size match the ZIP.

## 5. Settings surface (initial)

| Group | Settings (defaults) |
|---|---|
| Export | output dir (`<project>/cnc/`), export-only mode, layers auto-detected |
| Isolation | tool Ø (0.1–0.2 mm V-bit effective), passes/overlap (50 %), extra isolation width, Z depth (−0.05 mm), feed (120 mm/min), spindle RPM |
| Drill | Z depth, feed, available drill-bit set, mill-drill threshold |
| Outline | cutter Ø (1–2 mm), total depth (board + 0.2 mm), infeed per pass (0.5 mm), tabs: count/thickness |
| Post/GRBL | safe/change Z, spindle RPM + spin-up/down dwell, fixed per-tool file split |
| Double-sided | optional manual registration holes (count, Ø, symmetric positions) |

## 6. Risks & mitigations

- **pcb2gcode not installed** → detect at startup; show per-OS install help
  (Windows release zip, `apt install pcb2gcode`, `brew install pcb2gcode`).
  Optionally bundle the Windows binary later (license: GPLv3 — plugin must be
  GPL-compatible, which PCM requires anyway).
- **kicad-cli output drift between 10.x point releases** → pin on `--help` probing
  and version check at startup; golden-file tests.
- **KiCad 11 migration** → export layer is isolated in `export.py`; swap the
  `kicad-cli` subprocess for kipy's native `board.export_gerbers()/export_drill()`
  when 11 becomes the minimum. SWIG is never used, so nothing breaks.
- **Coordinate origin mismatches** (plot origin vs absolute) → always use
  `--drill-origin plot` + consistent plot origin; verify with a fixture board test
  asserting hole coordinates match pad positions.
- **GRBL arc quirks (G2/G3 on some controllers)** → post-processor option to
  linearize arcs (`G2/G3` → `G1` segments) as a fallback.

## 7. Suggested order of work

1. M1 skeleton (1–2 days) — proves the IPC plugin plumbing.
2. M2 export (1 day) — immediately useful on its own.
3. M3 pcb2gcode wrap (2–3 days) — core value.
4. M4 GRBL post (2 days) — generates validated, manually sequenced GRBL files.
5. M5 double-sided (2–3 days) — registration holes are the tricky bit.
6. M6 tests + PCM packaging (2 days).
