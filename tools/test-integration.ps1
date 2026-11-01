[CmdletBinding()]
param(
    [string]$Python = (Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'),
    [string]$KicadCli = $env:KICAD_CLI,
    [string]$Pcb2gcode = $env:PCB2GCODE
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $KicadCli) {
    $KicadCli = Join-Path $env:LOCALAPPDATA 'Programs\KiCad\10.0\bin\kicad-cli.exe'
}
if (-not $Pcb2gcode) {
    $Pcb2gcode = Join-Path $env:LOCALAPPDATA 'kicad2cnc\tools\pcb2gcode-2.4.0\pcb2gcode-2.4.0\pcb2gcode.exe'
}
foreach ($required in @(
    @{ Name = 'Python'; Path = $Python },
    @{ Name = 'KiCad CLI'; Path = $KicadCli },
    @{ Name = 'pcb2gcode'; Path = $Pcb2gcode }
)) {
    if (-not (Test-Path -LiteralPath $required.Path -PathType Leaf)) {
        throw "$($required.Name) executable not found: $($required.Path)"
    }
}

$env:KICAD_CLI = (Resolve-Path -LiteralPath $KicadCli).Path
$env:PCB2GCODE = (Resolve-Path -LiteralPath $Pcb2gcode).Path
Push-Location $root
try {
    foreach ($testFile in @('test_export.py', 'test_gcode.py')) {
        Write-Output "Running real-tool integration coverage in $testFile"
        & $Python -m unittest discover -s tests -p $testFile -v
        if ($LASTEXITCODE -ne 0) {
            throw "Integration tests failed in $testFile (exit $LASTEXITCODE)."
        }
    }
}
finally {
    Pop-Location
}
