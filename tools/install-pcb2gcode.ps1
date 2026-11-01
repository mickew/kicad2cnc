[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$directory = Join-Path $env:LOCALAPPDATA 'kicad2cnc\tools\pcb2gcode-2.4.0'
New-Item $directory -ItemType Directory -Force | Out-Null
$archive = Join-Path $directory 'pcb2gcode-windows-2.4.0.zip'
Invoke-WebRequest 'https://github.com/pcb2gcode/pcb2gcode/releases/download/v2.4.0/pcb2gcode-windows-2.4.0.zip' -OutFile $archive
$expected = '1EA54F8F3B12A890F609FB83C540F8CAE473EC919FA0F6345CFA20AE5FB8333E'
if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne $expected) {
    throw 'The downloaded pcb2gcode archive does not match the tested package.'
}
Expand-Archive -LiteralPath $archive -DestinationPath $directory -Force
$executable = Join-Path $directory 'pcb2gcode-2.4.0\pcb2gcode.exe'
& $executable --version
if ($LASTEXITCODE -ne 0) { throw 'pcb2gcode could not run.' }
Write-Output "Installed official Windows pcb2gcode: $executable"
