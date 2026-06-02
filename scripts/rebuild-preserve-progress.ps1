param(
  [string]$BackupRoot = "backups",
  [ValidateSet("metadata", "results")]
  [string]$BackupMode = "metadata",
  [switch]$SkipBackup,
  [switch]$AllowMultipleResultsArchives
)

$ErrorActionPreference = "Stop"

$compose = @("-f", "docker-compose.yml", "-f", "docker-compose.remote.yml")
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path (Get-Location) $BackupRoot
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

Write-Host "==> Using docker compose files: docker-compose.yml + docker-compose.remote.yml"
Write-Host "==> This script uses 'up -d --build' only. It never runs 'down -v'."
Write-Host "==> Backup mode: $BackupMode"

if (-not $SkipBackup) {
  Write-Host "==> Snapshotting current compose config"
  docker compose @compose config | Out-File -Encoding utf8 (Join-Path $backupDir "compose-$stamp.yml")
  git rev-parse HEAD | Out-File -Encoding ascii (Join-Path $backupDir "git-$stamp.txt")

  Write-Host "==> Dumping Postgres metadata"
  docker compose @compose exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=plain' `
    | Out-File -Encoding utf8 (Join-Path $backupDir "postgres-$stamp.sql")

  if ($BackupMode -eq "results") {
    $existingResultsArchives = @(Get-ChildItem -Path $backupDir -Filter "results-*.tgz" -File -ErrorAction SilentlyContinue)
    if ($existingResultsArchives.Count -gt 0 -and -not $AllowMultipleResultsArchives) {
      $existingNames = ($existingResultsArchives | Select-Object -First 5 -ExpandProperty Name) -join ", "
      throw "Existing results archive(s) already found in ${BackupRoot}: $existingNames. Refusing to create another large archive by default. Move/delete the old archive, choose another -BackupRoot, or rerun with -AllowMultipleResultsArchives."
    }

    $resultsSizeMbRaw = docker compose @compose exec -T api sh -lc "du -sm /data/results 2>/dev/null | awk '{print `$1}'"
    $resultsSizeMb = [int64]($resultsSizeMbRaw.Trim())
    $drive = Get-PSDrive -Name ((Get-Location).Path.Substring(0,1))
    $freeMb = [int64]($drive.Free / 1MB)
    $requiredMb = [int64]($resultsSizeMb * 1.10 + 1024)

    Write-Host "==> /data/results size: ${resultsSizeMb} MB; free on backup drive: ${freeMb} MB"
    if ($freeMb -lt $requiredMb) {
      throw "Not enough free space for results archive. Need about ${requiredMb} MB. Rerun with -BackupMode metadata, or free space / choose another -BackupRoot."
    }

    Write-Host "==> Stopping app/worker/frontend before volume archive"
    docker compose @compose stop api worker frontend

    $backupMount = "${backupDir}:/backup"
    Write-Host "==> Archiving /data/results to $BackupRoot/results-$stamp.tgz"
    docker compose @compose run --rm --no-deps -v $backupMount --entrypoint sh api `
      -lc "tar -C /data/results -czf /backup/results-$stamp.tgz ."
  } else {
    Write-Host "==> Skipping /data/results archive to avoid duplicating large BAM/checkpoint files"
  }
}

Write-Host "==> Rebuilding and starting containers without deleting volumes"
docker compose @compose up -d --build

Write-Host "==> Done. Results volume was preserved."
