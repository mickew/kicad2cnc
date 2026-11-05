# KiCad to CNC

[![Release](https://github.com/mickew/kicad2cnc/actions/workflows/release.yml/badge.svg)](https://github.com/mickew/kicad2cnc/actions/workflows/release.yml)
[![Tests](https://github.com/mickew/kicad2cnc/actions/workflows/tests.yml/badge.svg)](https://github.com/mickew/kicad2cnc/actions/workflows/tests.yml)
[![Latest GitHub release version](https://img.shields.io/github/v/release/mickew/kicad2cnc?logo=semanticrelease&label=Release)](https://github.com/mickew/kicad2cnc/release/latest)
[![Latest GitHub release version, including prereleases](https://img.shields.io/github/v/release/mickew/kicad2cnc?logo=semanticrelease&include_prereleases&label=Prerelease)](https://github.com/mickew/kicad2cnc/releases)


IPC plugin for **KiCad 10.x**. Export selected Gerber layers and Excellon drills,
optionally converting them to isolation, outline, and drilling G-code using
pcb2gcode. It can produce per-tool GRBL-oriented `.nc` output, but does not
validate your particular controller, machine, or work setup. Double-sided
registration uses optional, manually positioned through-board holes; hole
clearance and the physical flip/alignment setup must be verified by the operator.

## Install on Windows

The KiCad plugin installer and release package currently target Windows. The
pcb2gcode converter has install options on other operating systems, but running
the KiCad plugin outside Windows has not been packaged or verified.

1. Install KiCad 10 and close the PCB Editor.
2. From this directory, run:

   ```powershell
   .\tools\install.ps1
   ```

   This copies only the plugin runtime files into your Documents directory under
   `KiCad\10.0\plugins\kicad2cnc`. Run it again after changing the source.
   For a custom KiCad documents location, pass `-PluginDirectory`.
3. Open KiCad and enable **Preferences > Preferences > Plugins > Enable API
   server**. Keep the default bundled Python interpreter.
4. Restart the PCB Editor and open a board. Allow time for KiCad to create the
   plugin's Python environment and install its requirements on first launch
   (requires internet access).
5. Click **KiCad to CNC** on the PCB Editor toolbar. The tooltip identifies the
   PCB-and-cutter icon. The action is also listed in the Plugins preferences.
   The export window uses the PCB-and-cutter icon; CNC settings uses a gear icon
   in its title bar where supported by the operating system.

The plugin never modifies or saves your PCB. Save your board in KiCad before exports:
KiCad 10's IPC API does not expose a dirty flag, so the dialog always displays a
save reminder rather than claiming that a saved file is up to date. A missing
file receives a stronger save warning. Enabled layers are not a claim that those
layers contain copper or geometry.

If the button is missing, check API enablement and the plugin's environment in
Plugins preferences. Right-click its action and select **Recreate Plugin
Environment** after dependency changes. KiCad 10.0.1+ reports plugin stderr in
the status-bar warning messages. Connection failures show an error dialog and
clear stale board information.

## Export Gerbers and drills

1. Save your board in the PCB Editor, then click **KiCad to CNC**.
2. Check the layers to export. The defaults are `F.Cu`, `B.Cu`, and `Edge.Cuts`
   when enabled. Uncheck `B.Cu` for a front-only board (or `F.Cu` for back-only).
   Other enabled layers can be selected for plain Gerber export. Enabled does
   not mean populated: the plugin does not infer a single-sided design.
3. Choose an output directory (default: `cnc` beside the PCB).
4. Leave **Export only, no G-code** checked. Click **Export** and confirm that the board has been saved.
   Export runs in the background; the dialog cannot close until it finishes.
5. The log shows the completed job directory, files, and CLI output.

Each export creates a new timestamped job folder, leaving earlier jobs untouched:

```text
cnc\<board>-<timestamp>-<unique-id>\
  gerbers\<board>-F_Cu.gbr
  gerbers\<board>-B_Cu.gbr
  gerbers\<board>-Edge_Cuts.gbr
  gerbers\<board>-job.gbrjob
  drill\<board>-PTH.drl
  drill\<board>-NPTH.drl
```

Only selected Gerber layers are produced; drills always include separate plated
and non-plated files (possibly empty when no holes exist). Gerbers and drills
both use the board's **drill/place origin**. Drill units are millimetres with
decimal coordinates; slots use route mode. Gerbers use X2 and six decimal places.
The CLI comes from the running editor's installation, not an arbitrary PATH entry.
Saved zone fills are exported as-is; refill zones in KiCad before saving.
KiCad uses custom layer names in Gerber filenames when configured (for example,
`top_layer` instead of `F_Cu`). Copper-side and board-outline validation uses X2
file-function metadata when the standard filename is absent; custom filenames
and the Gerber job file are preserved unchanged.

Failed or incomplete exports show an error and do not publish a partial job.
On Windows, temporary access/sharing errors when renaming the completed job
folder are retried for up to five seconds and recorded in the export log. If
publication still fails, close viewers or CNC senders using that directory,
check output-directory permissions, or select another output directory and
export again. Persistent permission errors are not bypassed.
If the saved PCB changes during export, the job is rejected. Do not edit the
board or project settings while exporting.

## Generate and review G-code (M3/M4)

**Do not treat generated files as ready to cut.** Simulate every file, run GRBL
check mode where available, and dry-run above the stock. Verify machine travel,
work coordinates, Z-zero, spindle direction, feeds, depths, tools, tabs, and
workholding first. No controller or physical machine has been tested.

1. Install pcb2gcode for your operating system:

   ```powershell
   .\tools\install-pcb2gcode.ps1
   ```

   On Windows, this downloads the
   [official 2.4.0 release](https://github.com/pcb2gcode/pcb2gcode/releases),
   verifies its SHA256, and extracts it under `%LOCALAPPDATA%\kicad2cnc\tools`.
   Retain the package's
   `.libs` directory next to its launcher. On Debian/Ubuntu, install with
   `sudo apt install pcb2gcode`; on macOS, install Homebrew and run
   `brew install pcb2gcode` (see the
   [upstream installation instructions](https://github.com/pcb2gcode/pcb2gcode#quick-installation)).
   Distribution packages can lag upstream, so confirm the executable runs and
   select it in CNC settings if it is not found on PATH.
   This project has been tested end-to-end with the native Windows 2.4.0 build;
   other builds are capability-checked but are not certified by these tests.
2. Open **CNC settings...**. Choose the executable if needed, select operations,
   and set tool diameters, depths, feeds, spindle RPM, safe/tool-change Z, and tabs.
   Hover over any setting or its label for an explanation, units and relevant
   safety guidance. Export-layer, directory and export-only controls also have tooltips.
   For double-sided registration, enable **Registration** and enter 2-4
   symmetric hole centers in the exported drill/place-origin coordinates.
   Set **Registration depth** separately from board drilling depth: use a negative
   Z value in mm from the PCB top surface, for example `-3.0`. Verify the depth
   needed for pin engagement and clearance below the board/into the spoilboard.
   The plugin does not check that this reaches through the PCB. Existing saved
   settings initially inherit their previous board-drill depth; subsequent changes
   to board-drill depth do not change the saved registration depth.
   Values use **mm, mm/min, RPM**; Z=0 is the PCB top surface and cuts are negative.
   Defaults are examples, not recommendations for your machine or material.
   Settings are saved alongside the board as `<board>.kicad2cnc.json`.
3. Keep the required Gerber layers selected:
   - Isolation: `F.Cu`, `B.Cu`, or both. Deselect empty/unwanted copper layers.
   - Outline: `Edge.Cuts`. Disable outline cutting for jobs without this layer.
   - Drilling: separate PTH/NPTH jobs, skipping explicitly reported empty files.
4. Uncheck **Export only, no G-code**, click **Export**, and confirm both save
   status and the GRBL setup warning. Logs stream during conversion.
5. Find the results in the new job's `gcode` directory:

   ```text
   gcode\
     cam\                         # Original pcb2gcode output; simulation/review only
       routing\front.ngc
       routing\back.ngc
       routing\outline.ngc
       drill-1-<board>-NPTH\drill.ngc
       drill-2-<board>-PTH\drill.ngc
       registration-input.drl        # only when registration is enabled
     grbl\
       01-registration-drill-2mm.nc   # only when enabled; first in the job
       NN-drill-npth-1p5mm.nc
       NN-drill-pth-0p8mm.nc
       NN-isolation-front-0p2mm.nc
       NN-isolation-back-0p2mm.nc
       NN-outline-1mm.nc
       README_job.txt
     REVIEW_BEFORE_MACHINING.txt
     conversion.log
   ```

   The names and count vary with board geometry, drill diameters, and selected
   operations. Registration files appear first when enabled. Each `.nc` file
   contains one tool operation; change tools and re-set/probe Z=0 against the
   PCB surface between files. Follow the generated
   `grbl\README_job.txt` machining order and do not assume there is an automatic
   tool change. Source `.ngc` files are retained under `cam\` and are not the
   recommended files to send to GRBL. Each CAM operation folder includes its
   input copies and generated `millproject` configuration for reproducibility.
   The optional **Mill-drill hole threshold** mills holes at or above the specified
   diameter using the outline cutter; 0 disables it. It must exceed the cutter's
   diameter. These jobs may contain `milldrill.ngc` instead of, or alongside,
   `drill.ngc`.

### Optional single-diameter drill alternative

In **CNC settings > Drill**, enable **Also generate one file for all board holes
using one drill size** and enter the **Single-diameter alternative: drill diameter**.
Drilling must also be enabled. This adds one `NN-drill-all-one-size-<diameter>mm.nc`
program alongside all normal outputs, combining board PTH and NPTH holes across
all original sizes, including holes normally handled by mill-drill. It uses the
normal drill depth, feed, spindle, and origin settings; B.Cu-only mirroring applies.
It is off by default and is saved with the board's CNC settings.

**Run this program instead of the normal board drill/mill-drill files, not as an
additional pass.** Every round hole is made with the selected bit, so the finished
hole diameters differ from the design. Straight oval slots are included, using
the selected diameter along the original slot centerline (so slot width and
overall length also change). KiCad's straight slot route blocks are translated
to equivalent G85 records in private CAM input copies; original Excellon exports
remain unchanged. Other routed geometries fail explicitly rather than being omitted.
Verify tool suitability, fit, clearances, and the complete toolpath.
Registration holes remain separate at their configured diameter. Header-only
drill exports are skipped; no combined program is produced if there are no board
holes. Original Gerber/Excellon exports and normal CNC tool sizes are unchanged.

For straight oval slots, the tested pcb2gcode build generates overlapping drill
plunges along the slot unless the mill-drill threshold selects that slot's tool
diameter for milling. Chain drilling is not continuous slot milling and can leave
scalloped edges; verify the generated positions and tool suitability. The
single-diameter alternative always uses drilling, not the mill-drill threshold.

### Optional bCNC manual tool-change programs

In **CNC settings > Common**, enable **Also generate bCNC programs with manual
tool changes (T/M6)**. This is off by default and saved with the board settings.
Choose **bCNC program contents > All operations** (the default) or **Drills only**.
Drills only includes board drilling, mill-drilling and enabled registration holes,
but excludes copper isolation and outlines from the combined bCNC programs.
Their individual programs are copied into `gcode\bcnc\` with a `separate-` filename
prefix, so this folder contains all programs needed for the generated job.
Run them separately following `README_bcnc.txt`, which lists their tools and
front/back setup order. Enable drilling or registration for drills-only output; if neither
produces holes, the job fails explicitly rather than producing an empty program.

Board drill/mill-drill operations are sorted by ascending **tool diameter** across
PTH and NPTH files, in both modes. Registration stays first for alignment; isolation
and outline retain their normal setup order. Equal diameters retain their original
order and still receive separate tool-change requests.

Existing per-tool GRBL files remain unchanged. Additional programs and a tool
list/setup guide are written to `gcode\bcnc\`:

- Front-only job: `01-front.nc`, containing registration, board drill/mill-drill,
  front isolation, and outline operations when enabled.
- B.Cu-only job: `01-back-only.nc`, with matching mirrored drill, isolation, and
  outline coordinates; machine B.Cu upward without flipping.
- Double-sided job: `01-front.nc` for registration, board drills and front
  isolation; `02-back.nc` for back isolation; `03-outline-front.nc` for outline
  cutting last. Programs without operations are omitted.

The folder also includes the machining-review warning. In **All operations**
mode, operations already covered by combined programs are not copied again.
In **Drills only** mode, combined drilling plus the copied isolation/outline
programs form the complete job. Original GRBL files remain unchanged; do not
run matching operations from both folders. Gerber/Excellon exports and raw CAM
sources remain in their original locations, as they are not programs to run in bCNC.

For double-sided work, stop between programs: use the verified Y-axis flip and
re-establish G54 for the back program, then **return to the front-side setup and
re-establish G54** before the outline program. A board flip is never handled as
an M6 tool change. The outline stays in its original front coordinate frame.

**Use bCNC programs instead of the corresponding separate tool files, not in addition.**
They include normal board drill/mill-drill sizes; the single-diameter drill
alternative is deliberately excluded to avoid drilling holes twice. Each
operation requests a distinct tool number and M6, including the first tool
and operations that happen to use the same diameter.

These files are **bCNC-only**, not directly GRBL-compatible. In bCNC's tool-change
settings select **Manual tool change (WCS)** or **Manual tool change (No Probe)**.
Do not select ignore/skip M6, send M6 to the controller, or TLO mode. G49 cancels
tool-length offsets in these programs. WCS probing must establish PCB-surface
G54 Z0 for each tool; No Probe requires manually setting that Z0 before resuming.
Verify bCNC's configured **machine-coordinate** tool-change/probe locations,
homing, probe settings and safe travel; the plugin's work-coordinate change Z
does not configure bCNC's macro locations.

The spindle is stopped before each M6 and started after it with the configured
spin-up dwell. Read `README_bcnc.txt`, check the listed tool diameters, inspect
bCNC's compiled macros, simulate and dry-run before cutting. bCNC may add its
own delays and movements. Actual sender/controller/probe hardware operation
has not been tested; bCNC policies are described in its
[tool-change implementation](https://github.com/vlachoudis/bCNC/blob/master/bCNC/CNC.py).

The converter receives `metric=true` **and** `metricoutput=true`, `zero-start=false`,
`nog81=true`, `nog64=true`, and `nog91-1=true`. It uses the exported drill/place
origin without independently recentering operations. pcb2gcode's drilling and
cutout operations start in the front-side coordinate frame. Back copper is mirrored
about **X=0**. Rotate the board 180 degrees about the **Y axis** to match that
transform; the former X-axis flip instruction was incorrect. Verify negative X/Y
travel and workholding.
When **only `B.Cu`** is selected (and `F.Cu` is not), M5 applies the same X
reflection to the drill, outline, and optional registration paths. Machine with
the B.Cu face upward; this single-sided setup needs no board flip, and registration
holes are optional. The work origin must use the reflected
coordinates; verify it and all paths before cutting. When both copper sides are
selected, the exporter retains the separate front/back workflows described by
the job guide.

The tested 2.4.0 build has no `nom6` option and emits tool-change commands, including
M6. M4 parses and splits every converter tool section, requires explicit tool
diameters and change blocks, then removes converter pauses and spindle commands
from each isolated file. Unsupported commands, conflicting units/coordinates,
unknown tool changes, and spindle-speed mismatches fail the whole export rather
than producing a partially accepted job. Source dwell commands are replaced by
the configured spindle spin-up/shutdown dwell values.
Drill-only converter invocations may warn that board dimensions are unknown;
front-side and absolute-origin settings are explicit, and integration tests verify
their hole positions against the source PCB. Review the log for all other warnings.
One intermittent native startup crash was observed during development; converter
failures are reported and no partial job is published.

The post-processor emits a GRBL v1.1 command subset, not a machine-specific post.
It assumes millimetres, G54, absolute XY, and spindle-on-clockwise (`M3`). Manually
change and touch off each tool. For double-sided alignment, registration holes are
optional and manually positioned. Enter 2-4 unique X,Y centers (mm), symmetric
about **X=0**, so the pattern is unchanged by the 180-degree Y-axis flip. A
registration operation is emitted before board drilling. The tool does not check
that holes are within the board outline or clear of copper, components, or clamps;
inspect those positions in KiCad and verify the fixture before machining.
Automatic location suggestions and fixture/fence design are not provided. The
physical two-sided setup remains the operator's responsibility.

Original Gerbers retain X2 attributes and custom filenames. Only the private CAM
input copies have non-geometric X2 metadata removed for the older Windows
Gerbv parser. Converter timeouts, missing output, or missing cutting moves reject
the entire job; successful Gerber-only jobs remain independent of pcb2gcode.

## Development and validation

The [Tests workflow](.github/workflows/tests.yml) runs the full suite on every
push and pull request, and can also be started manually from GitHub Actions.
It uses Windows, KiCad 10.0.7 (including its bundled Python), and pcb2gcode 2.4.0
to exercise the GUI, packaging, and real export/CAM integration tests. CI fails
on skipped tests as well as failures, so missing integration tools cannot pass
as a successful full test run.
The workflow measures Python line and branch coverage for `kicad2cnc`, displays
a summary on the workflow run, and uploads a **coverage-report** artifact with
HTML and Cobertura XML reports. Download and extract it, then open
`html/index.html` to inspect covered and missing code. Reports are also attempted
when tests fail. Coverage does not measure the external KiCad/pcb2gcode binaries.

KiCad's bundled Python includes wxPython but not a working Tkinter extension.
The plugin declares `wxPython` explicitly for its isolated environment. The
official IPC client distribution is **kicad-python**, imported as `kipy`.

```powershell
& "$env:LOCALAPPDATA\Programs\KiCad\10.0\bin\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

To generate the same coverage reports locally after installing the development
dependencies:

```powershell
.\.venv\Scripts\python.exe -m coverage run -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m coverage report
.\.venv\Scripts\python.exe -m coverage html
.\.venv\Scripts\python.exe -m coverage xml
Start-Process .\coverage-report\html\index.html
```

Generated coverage data and reports are ignored by Git. Local integration tests
may skip if external tools are missing; CI still requires no skipped tests.

For VS Code, select `.venv\Scripts\python.exe`, enable unittest and discover
`test_*.py` in `tests`. The `tests/__init__.py` package marker supports discovery
from the project root as used by VS Code's Python test adapter.

Tests use the real SDK types with mocked IPC replies and exercise the wx dialog,
including failed refreshes, export confirmation, worker errors, and closing.
The export tests also run the real CLI against a two-sided fixture with plated
and non-plated holes and a nonzero drill/place origin, check exact coordinates,
and compare output to KiCad's plotter/drill-writer reference (via its bundled
Python, for tests only). Set `KICAD_CLI` for a custom CLI installation; those
integration tests skip when the required tools are absent.
The manifest test uses the schema shipped with KiCad; set `KICAD_API_SCHEMA` if
KiCad is installed elsewhere. No PCB is saved or modified by the tests.
CAM integration tests use a real pcb2gcode installation (`PCB2GCODE` overrides
discovery). They check front/back extents, negative mirroring, multi-pass cut
depths, tab height, drill coordinates, metric output, and mill-drill selection.
Those are geometric checks, not a substitute for machine simulation or a physical
test cut.
GRBL golden files lock the expected front-isolation and back-only mirrored-outline
program text. To require the real KiCad CLI and pcb2gcode integrations (rather
than allowing unit-test skips), run:

```powershell
.\tools\test-integration.ps1
```

Set `KICAD_CLI` and/or `PCB2GCODE` to override the default Windows installations.
The runner fails immediately if either executable or the virtual-environment
Python is missing, then runs the real export and CAM integration test modules.
The tests use a temporary output directory and the checked-in demo board fixture.

### Build a KiCad PCM package

The packaging tool creates a runtime-only ZIP and schema-validated PCM v2
`metadata.json`. Supply the project's real license and the public URLs for the
project and versioned release; the tool deliberately does not guess those values:

```powershell
.\.venv\Scripts\python.exe .\tools\package.py `
  --version 1.0.0 `
  --author "Your name" `
  --license "SPDX-license-identifier" `
  --project-url "https://example.com/project" `
  --download-url "https://example.com/releases/kicad2cnc-1.0.0.zip"
```

The output is `dist\kicad2cnc-1.0.0.zip` plus `dist\metadata.json`. The ZIP
contains the IPC manifest, entrypoint, runtime package, icons, requirements,
and README; it excludes tests and development files. The metadata records the
archive SHA-256 and sizes and declares the IPC runtime and KiCad 10.0 minimum.
Existing output files are never overwritten. The package is currently marked
`testing` and Windows-only; PCM submission and controller certification are not
performed by this tool.

### Release from GitHub Actions

After the workflow is on the default branch, open **Actions > Package and release >
Run workflow**. Select the branch/revision to package and enter a numeric version
without `v`, the author display name, and the project's actual license. The
**prerelease** option is enabled by default.

The [release workflow](.github/workflows/release.yml) tests the package builder,
builds the ZIP and PCM metadata, and creates a GitHub Release tagged `v<version>`
at the selected commit. Project and download URLs are filled in automatically
for this repository. Both files are uploaded to a draft before it is published.
Non-prereleases are explicitly marked **Latest**; prereleases are not.
Existing releases are not overwritten; if upload or publication fails, inspect
any remaining draft before retrying.

This workflow only runs manually and uses GitHub's built-in token; no additional
secret is required. Run it against a revision whose full **Tests** workflow has
passed: the release workflow itself only runs the packaging tests. The PCM
metadata remains marked `testing`, even if GitHub's prerelease option is disabled.

For a live connection check, enable the API server and open a board, then run:

```powershell
.\.venv\Scripts\python.exe -c "from kipy import KiCad; from kicad2cnc.board_info import read_board_info; print(read_board_info(KiCad()))"
```

The toolbar launch is preferred: KiCad supplies the correct API socket and token
for that editor when several instances are running.

See [PLAN.md](PLAN.md) for subsequent milestones.
