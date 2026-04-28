$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-EnvValueOrDefault {
    param(
        [string]$Name,
        [string]$DefaultValue
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $DefaultValue
    }

    return $value
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

function Reset-MinikubeCluster {
    $minikubeCommand = Get-Command minikube -ErrorAction SilentlyContinue
    if (-not $minikubeCommand) {
        return
    }

    Write-Host "Removing existing Minikube clusters to avoid stale state ..."
    & minikube delete --all --purge | Out-Host

    $runtimeDir = Join-Path $root ".cassie\kube"
    if (Test-Path $runtimeDir) {
        Remove-Item -LiteralPath $runtimeDir -Recurse -Force
    }
}

function Ensure-MinikubeRunning {
    param(
        [string]$CpuCount,
        [string]$MemoryMb,
        [string]$DiskSize
    )

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

    $minikubeArgs = @(
        "start"
        "--driver=docker"
        "--cpus=$CpuCount"
        "--memory=${MemoryMb}mb"
        "--disk-size=$DiskSize"
    )

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
        Write-Host "Starting Minikube with the Docker driver ($CpuCount CPU, ${MemoryMb}MB RAM, disk $DiskSize) ..."
    }
    else {
        Write-Host "Ensuring Minikube is sized at $CpuCount CPU, ${MemoryMb}MB RAM, disk $DiskSize ..."
    }

    & minikube @minikubeArgs | Out-Host

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

    $rebuildImages = ($env:CASSIE_REBUILD_TOOL_IMAGES | ForEach-Object { $_.ToLowerInvariant() })
    $shouldRebuild = $rebuildImages -in @("1", "true", "yes")

    if ($shouldRebuild) {
        Write-Host "Rebuilding tool image $Image because CASSIE_REBUILD_TOOL_IMAGES=$env:CASSIE_REBUILD_TOOL_IMAGES ..."
        docker build -t $Image $Context
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to build tool image $Image."
        }
        return
    }

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

$null = Require-Command -Name "docker" -InstallHint "Docker is required but was not found in PATH."

$useComposeV2 = Test-DockerComposeV2
if (-not $useComposeV2) {
    $null = Require-Command -Name "docker-compose" -InstallHint "Docker Compose is required but was not found."
}

$env:CASSIE_MINIKUBE_CPUS = Get-EnvValueOrDefault -Name "CASSIE_MINIKUBE_CPUS" -DefaultValue "4"
$env:CASSIE_MINIKUBE_MEMORY = Get-EnvValueOrDefault -Name "CASSIE_MINIKUBE_MEMORY" -DefaultValue "7800"
$env:CASSIE_MINIKUBE_DISK_SIZE = Get-EnvValueOrDefault -Name "CASSIE_MINIKUBE_DISK_SIZE" -DefaultValue "15g"
$env:CASSIE_REBUILD_TOOL_IMAGES = Get-EnvValueOrDefault -Name "CASSIE_REBUILD_TOOL_IMAGES" -DefaultValue "0"

$env:EXECUTION_BACKEND = Get-EnvValueOrDefault -Name "EXECUTION_BACKEND" -DefaultValue "kubernetes"
$env:KUBERNETES_JOB_TIMEOUT_SECONDS = Get-EnvValueOrDefault -Name "KUBERNETES_JOB_TIMEOUT_SECONDS" -DefaultValue "0"

Reset-MinikubeCluster
Ensure-MinikubeRunning -CpuCount $env:CASSIE_MINIKUBE_CPUS -MemoryMb $env:CASSIE_MINIKUBE_MEMORY -DiskSize $env:CASSIE_MINIKUBE_DISK_SIZE

$minioApiPort = if ($env:MINIO_API_PORT) { $env:MINIO_API_PORT } else { "9010" }
$minioConsolePort = if ($env:MINIO_CONSOLE_PORT) { $env:MINIO_CONSOLE_PORT } else { "9011" }

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
$env:NO_PROXY = "localhost,127.0.0.1,host.docker.internal,kubernetes.docker.internal"
$env:no_proxy = $env:NO_PROXY
$env:KUBERNETES_NO_PROXY = $env:NO_PROXY
$env:KUBERNETES_MINIO_ENDPOINT = "http://host.docker.internal:$minioApiPort"
$env:KUBE_CONFIG_DIR = Prepare-ContainerKubeconfig
$env:CASSIE_CLUSTER_STORAGE_RESERVE_MIB = Get-EnvValueOrDefault -Name "CASSIE_CLUSTER_STORAGE_RESERVE_MIB" -DefaultValue "2048"
$env:FASTQC_THREADS = Get-EnvValueOrDefault -Name "FASTQC_THREADS" -DefaultValue "auto"
$env:GENOMESCOPE2_THREADS = Get-EnvValueOrDefault -Name "GENOMESCOPE2_THREADS" -DefaultValue "auto"
$env:SPADES_THREADS = Get-EnvValueOrDefault -Name "SPADES_THREADS" -DefaultValue "auto"
$env:SPADES_MEMORY_GB = Get-EnvValueOrDefault -Name "SPADES_MEMORY_GB" -DefaultValue "auto"
$env:SPADES_LOW_RESOURCE = Get-EnvValueOrDefault -Name "SPADES_LOW_RESOURCE" -DefaultValue "auto"
$env:SPADES_KMERS = Get-EnvValueOrDefault -Name "SPADES_KMERS" -DefaultValue "auto"
$env:SPADES_MEMORY_LIMIT = Get-EnvValueOrDefault -Name "SPADES_MEMORY_LIMIT" -DefaultValue "auto"
$env:METASPADES_THREADS = Get-EnvValueOrDefault -Name "METASPADES_THREADS" -DefaultValue "auto"
$env:METASPADES_MEMORY_GB = Get-EnvValueOrDefault -Name "METASPADES_MEMORY_GB" -DefaultValue "auto"
$env:HIFIASM_THREADS = Get-EnvValueOrDefault -Name "HIFIASM_THREADS" -DefaultValue "auto"
$env:HIFIASM_MEMORY_GB = Get-EnvValueOrDefault -Name "HIFIASM_MEMORY_GB" -DefaultValue "auto"
$env:VERKKO_THREADS = Get-EnvValueOrDefault -Name "VERKKO_THREADS" -DefaultValue "auto"
$env:VERKKO_MEMORY_GB = Get-EnvValueOrDefault -Name "VERKKO_MEMORY_GB" -DefaultValue "auto"
$env:LIFTOFF_THREADS = Get-EnvValueOrDefault -Name "LIFTOFF_THREADS" -DefaultValue "auto"
$env:CAT_THREADS = Get-EnvValueOrDefault -Name "CAT_THREADS" -DefaultValue "auto"
$env:CAT_MEMORY_GB = Get-EnvValueOrDefault -Name "CAT_MEMORY_GB" -DefaultValue "auto"
$env:BUSCO_THREADS = Get-EnvValueOrDefault -Name "BUSCO_THREADS" -DefaultValue "auto"
$env:BUSCO_MEMORY_GB = Get-EnvValueOrDefault -Name "BUSCO_MEMORY_GB" -DefaultValue "auto"
$env:MERQURY_THREADS = Get-EnvValueOrDefault -Name "MERQURY_THREADS" -DefaultValue "auto"
$env:MERQURY_MEMORY_GB = Get-EnvValueOrDefault -Name "MERQURY_MEMORY_GB" -DefaultValue "auto"
$env:QUAST_THREADS = Get-EnvValueOrDefault -Name "QUAST_THREADS" -DefaultValue "auto"

$toolImages = @(
    @{ Image = "fastqc:0.12.1"; Context = "dockerized_tools/fastqc" },
    @{ Image = "spades:latest"; Context = "dockerized_tools/spades" },
    @{ Image = "metaspades:latest"; Context = "dockerized_tools/metaspades" },
    @{ Image = "quast:latest"; Context = "dockerized_tools/quast" },
    @{ Image = "genomescope2:latest"; Context = "dockerized_tools/genomescope2" },
    @{ Image = "hifiasm:latest"; Context = "dockerized_tools/hifiasm" },
    @{ Image = "verkko:latest"; Context = "dockerized_tools/verkko" },
    @{ Image = "liftoff:latest"; Context = "dockerized_tools/liftoff" },
    @{ Image = "cat-tool:latest"; Context = "dockerized_tools/cat" },
    @{ Image = "busco:latest"; Context = "dockerized_tools/busco" },
    @{ Image = "merqury:latest"; Context = "dockerized_tools/merqury" }
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
Write-Host "Minikube:   $($env:CASSIE_MINIKUBE_CPUS) CPU, $($env:CASSIE_MINIKUBE_MEMORY)MB RAM, disk $($env:CASSIE_MINIKUBE_DISK_SIZE)"
