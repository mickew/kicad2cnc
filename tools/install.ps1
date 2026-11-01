[CmdletBinding()]
param(
    [string]$PluginDirectory = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'KiCad\10.0\plugins')
)

$ErrorActionPreference = 'Stop'
$source = Split-Path $PSScriptRoot -Parent
$target = Join-Path $PluginDirectory 'kicad2cnc'
$manifest = Join-Path $target 'plugin.json'
if (Test-Path $target) {
    if (-not (Test-Path $manifest)) {
        throw "Refusing to overwrite an unrelated directory: $target"
    }
    $existing = Get-Content $manifest -Raw | ConvertFrom-Json
    if ($existing.identifier -ne 'com.github.mickew.kicad2cnc') {
        throw "Refusing to overwrite a different plugin: $target"
    }
}
New-Item $target -ItemType Directory -Force | Out-Null
foreach ($name in @('plugin.json', 'requirements.txt', 'launch.py', 'kicad2cnc', 'icons')) {
    Copy-Item (Join-Path $source $name) $target -Recurse -Force
}
Write-Output "Installed KiCad to CNC in $target"
Write-Output 'Enable the API server in Preferences > Preferences > Plugins, then restart the PCB Editor.'
