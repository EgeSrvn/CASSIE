$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Require-Command {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Name is required but was not found in PATH.`n$InstallHint"
    }

    return $command.Source
}

function Test-DockerComposeV2 {
    cmd /c "docker compose version >nul 2>nul"
    return ($LASTEXITCODE -eq 0)
}

if (Test-DockerComposeV2) {
    docker compose down
}
else {
    $null = Require-Command -Name "docker-compose" -InstallHint "Docker Compose is required but was not found."
    docker-compose down
}

$minikubeCommand = Get-Command minikube -ErrorAction SilentlyContinue
if ($minikubeCommand) {
    Write-Host "Deleting Minikube clusters ..."
    & minikube delete --all --purge | Out-Host
}

$runtimeDir = Join-Path $root ".cassie\kube"
if (Test-Path $runtimeDir) {
    Remove-Item -LiteralPath $runtimeDir -Recurse -Force
}
