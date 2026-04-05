$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

if (-not $env:KUBE_CONFIG_DIR) {
    $kubeDir = Join-Path $env:USERPROFILE ".kube"
    if (Test-Path (Join-Path $kubeDir "config")) {
        $env:KUBE_CONFIG_DIR = ($kubeDir -replace "\\", "/")
    }
}

if (-not $env:EXECUTION_BACKEND) {
    $env:EXECUTION_BACKEND = "kubernetes"
}

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
$env:NO_PROXY = "localhost,127.0.0.1,host.docker.internal,kubernetes.docker.internal"
$env:no_proxy = $env:NO_PROXY

$toolBuilds = @(
    @{ Name = "fastqc"; Context = "dockerized_tools/fastqc" },
    @{ Name = "spades"; Context = "dockerized_tools/spades" },
    @{ Name = "quast"; Context = "dockerized_tools/quast" },
    @{ Name = "genomescope2"; Context = "dockerized_tools/genomescope2" }
)

foreach ($tool in $toolBuilds) {
    $imageExists = docker image ls --format "{{.Repository}}:{{.Tag}}" | Select-String -SimpleMatch "$($tool.Name):latest"
    if (-not $imageExists) {
        Write-Host "Building tool image $($tool.Name):latest ..."
        docker build -t "$($tool.Name):latest" $tool.Context
    }
}

docker compose up --build -d --force-recreate --remove-orphans

Write-Host ""
Write-Host "CASSIE is starting."
Write-Host "Frontend: http://localhost:3000"
Write-Host "Backend:  http://localhost:8000"
Write-Host "Docs:     http://localhost:8000/docs"
Write-Host "MinIO API: http://localhost:9010"
Write-Host "MinIO:    http://localhost:9011"
Write-Host ""
Write-Host "CASSIE is configured to run jobs on Kubernetes."
