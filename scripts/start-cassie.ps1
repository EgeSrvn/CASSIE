$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Set-DotEnvValue {
    param(
        [string]$FilePath,
        [string]$Key,
        [string]$Value
    )

    if (-not (Test-Path $FilePath)) {
        return
    }

    $raw = Get-Content $FilePath -Raw
    $escapedKey = [regex]::Escape($Key)
    $replacementLine = "$Key=$Value"

    if ($raw -match "(?m)^$escapedKey=") {
        $updated = [regex]::Replace($raw, "(?m)^$escapedKey=.*$", $replacementLine)
    }
    else {
        $separator = if ($raw.EndsWith("`n") -or [string]::IsNullOrEmpty($raw)) { "" } else { "`r`n" }
        $updated = "$raw$separator$replacementLine`r`n"
    }

    Set-Content -Path $FilePath -Value $updated
}

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

function Ensure-MinikubeRunning {
    $null = Require-Command -Name "kubectl" -InstallHint "Install kubectl, for example with: choco install kubernetes-cli -y"
    $null = Require-Command -Name "minikube" -InstallHint (
        "Install Minikube, for example with one of:`n" +
        "  choco install minikube -y`n" +
        "  winget install Kubernetes.minikube"
    )

    $statusOutput = ""
    try {
        $statusOutput = (& minikube status 2>&1 | Out-String)
    }
    catch {
        $statusOutput = ($_.Exception.Message | Out-String)
    }

    if ($statusOutput -match "kubeconfig:\s+Misconfigured") {
        Write-Host "Detected stale Minikube kubeconfig. Running: minikube update-context"
        & minikube update-context | Out-Host
        $statusOutput = (& minikube status 2>&1 | Out-String)
    }

    if (
        ($statusOutput -match "host:\s+Stopped") -or
        ($statusOutput -match "kubelet:\s+Stopped") -or
        ($statusOutput -match "apiserver:\s+Stopped") -or
        ($statusOutput -match "minikube does not exist") -or
        ($statusOutput -match "Profile ""minikube"" not found") -or
        ($statusOutput -match "No such container:\s*minikube") -or
        ($statusOutput -match "unknown state") -or
        ($statusOutput -match "GUEST_STATUS")
    ) {
        Write-Host "Starting Minikube with the Docker driver ..."
        & minikube start --driver=docker | Out-Host
    }

    & minikube update-context | Out-Host
    & kubectl config use-context minikube | Out-Host
}

function Prepare-ContainerKubeconfig {
    $runtimeDir = Join-Path $root ".cassie\kube"
    $runtimeConfig = Join-Path $runtimeDir "config"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

    $flattenedConfig = & kubectl config view --raw --minify --flatten
    if (-not $flattenedConfig) {
        throw "Failed to generate a flattened kubeconfig for the backend container."
    }

    Set-Content -Path $runtimeConfig -Value $flattenedConfig

    $clusterServer = (& kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}').Trim()
    $serverPort = ""
    if ($clusterServer -match ":(\d+)$") {
        $serverPort = $Matches[1]
    }

    if ($serverPort) {
        $runtimeContents = Get-Content $runtimeConfig -Raw
        $runtimeContents = $runtimeContents -replace "server: https://(127\.0\.0\.1|localhost):\d+", "server: https://host.docker.internal:$serverPort"
        if ($runtimeContents -notmatch "tls-server-name:\s+localhost") {
            $runtimeContents = $runtimeContents -replace (
                "(?m)^(\s*)server: https://host\.docker\.internal:$serverPort\s*$",
                "`$1server: https://host.docker.internal:$serverPort`r`n`$1tls-server-name: localhost"
            )
        }
        Set-Content -Path $runtimeConfig -Value $runtimeContents
    }

    return ($runtimeDir -replace "\\", "/")
}

function Ensure-ToolImage {
    param(
        [string]$Image,
        [string]$Context
    )

    cmd /c "docker image inspect $Image >nul 2>nul"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Building tool image $Image ..."
        docker build -t $Image $Context
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to build tool image $Image."
        }
    }
}

function Load-ToolImagesIntoMinikube {
    param(
        [array]$ToolImages
    )

    foreach ($tool in $ToolImages) {
        Write-Host "Loading $($tool.Image) into Minikube ..."
        & minikube image load $tool.Image | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to load $($tool.Image) into Minikube."
        }
    }
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

$null = Require-Command -Name "docker" -InstallHint "Docker is required but was not found in PATH."

$useComposeV2 = Test-DockerComposeV2
if (-not $useComposeV2) {
    $null = Require-Command -Name "docker-compose" -InstallHint "Docker Compose is required but was not found."
}

Ensure-MinikubeRunning

if (-not $env:EXECUTION_BACKEND) {
    $env:EXECUTION_BACKEND = "kubernetes"
}

$minioApiPort = if ($env:MINIO_API_PORT) { $env:MINIO_API_PORT } else { "9010" }
$minioConsolePort = if ($env:MINIO_CONSOLE_PORT) { $env:MINIO_CONSOLE_PORT } else { "9011" }

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
$env:NO_PROXY = "localhost,127.0.0.1,host.docker.internal,kubernetes.docker.internal"
$env:no_proxy = $env:NO_PROXY
$env:KUBERNETES_MINIO_ENDPOINT = "http://host.docker.internal:$minioApiPort"
$env:KUBE_CONFIG_DIR = Prepare-ContainerKubeconfig

$minikubeLimits = (& docker inspect minikube --format "{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}" 2>$null)
if ($LASTEXITCODE -eq 0 -and $minikubeLimits) {
    $limitParts = $minikubeLimits.Trim().Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($limitParts.Count -eq 2) {
        $memoryBytes = [int64]$limitParts[0]
        $nanoCpus = [int64]$limitParts[1]
        if ($memoryBytes -gt 0) {
            $env:CASSIE_CLUSTER_MEMORY_MIB = [string][math]::Floor($memoryBytes / 1MB)
        }
        if ($nanoCpus -gt 0) {
            $env:CASSIE_CLUSTER_CPU_MILLIS = [string][math]::Floor($nanoCpus / 1000000)
        }
    }
}

Set-DotEnvValue -FilePath ".env" -Key "EXECUTION_BACKEND" -Value $env:EXECUTION_BACKEND
Set-DotEnvValue -FilePath ".env" -Key "KUBE_CONFIG_DIR" -Value $env:KUBE_CONFIG_DIR
Set-DotEnvValue -FilePath ".env" -Key "KUBERNETES_MINIO_ENDPOINT" -Value $env:KUBERNETES_MINIO_ENDPOINT
Set-DotEnvValue -FilePath ".env" -Key "KUBERNETES_NO_PROXY" -Value $env:NO_PROXY
if ($env:CASSIE_CLUSTER_MEMORY_MIB) {
    Set-DotEnvValue -FilePath ".env" -Key "CASSIE_CLUSTER_MEMORY_MIB" -Value $env:CASSIE_CLUSTER_MEMORY_MIB
}
if ($env:CASSIE_CLUSTER_CPU_MILLIS) {
    Set-DotEnvValue -FilePath ".env" -Key "CASSIE_CLUSTER_CPU_MILLIS" -Value $env:CASSIE_CLUSTER_CPU_MILLIS
}
Set-DotEnvValue -FilePath ".env" -Key "CASSIE_CLUSTER_STORAGE_RESERVE_MIB" -Value "2048"
Set-DotEnvValue -FilePath ".env" -Key "FASTQC_THREADS" -Value "auto"
Set-DotEnvValue -FilePath ".env" -Key "GENOMESCOPE2_THREADS" -Value "auto"
Set-DotEnvValue -FilePath ".env" -Key "SPADES_THREADS" -Value "auto"
Set-DotEnvValue -FilePath ".env" -Key "SPADES_MEMORY_GB" -Value "auto"
Set-DotEnvValue -FilePath ".env" -Key "SPADES_LOW_RESOURCE" -Value "auto"
Set-DotEnvValue -FilePath ".env" -Key "SPADES_KMERS" -Value "auto"
Set-DotEnvValue -FilePath ".env" -Key "SPADES_MEMORY_LIMIT" -Value "auto"
Set-DotEnvValue -FilePath ".env" -Key "QUAST_THREADS" -Value "auto"

$toolImages = @(
    @{ Image = "fastqc:0.12.1"; Context = "dockerized_tools/fastqc" },
    @{ Image = "spades:latest"; Context = "dockerized_tools/spades" },
    @{ Image = "quast:latest"; Context = "dockerized_tools/quast" },
    @{ Image = "genomescope2:latest"; Context = "dockerized_tools/genomescope2" }
)

foreach ($tool in $toolImages) {
    Ensure-ToolImage -Image $tool.Image -Context $tool.Context
}

Load-ToolImagesIntoMinikube -ToolImages $toolImages

if ($useComposeV2) {
    docker compose up --build -d --force-recreate --remove-orphans
}
else {
    docker-compose up --build -d --force-recreate --remove-orphans
}

Write-Host ""
Write-Host "CASSIE is starting."
Write-Host "Frontend:   http://localhost:3000"
Write-Host "Backend:    http://localhost:8000"
Write-Host "Docs:       http://localhost:8000/docs"
Write-Host "MinIO API:  http://localhost:$minioApiPort"
Write-Host "MinIO UI:   http://localhost:$minioConsolePort"
Write-Host "Backend:    $($env:EXECUTION_BACKEND) execution backend"
Write-Host "Kubeconfig: $($env:KUBE_CONFIG_DIR)"
Write-Host "K8s MinIO:  $($env:KUBERNETES_MINIO_ENDPOINT)"
