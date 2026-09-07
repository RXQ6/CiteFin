param(
    [Parameter(Mandatory = $false, Position = 0)]
    [ValidateSet("setup", "test", "lint", "format", "typecheck", "golden", "check", "migrate", "prepare-f004-review", "verify-feature", "run")]
    [string]$Command = "check",
    [Parameter(Mandatory = $false)]
    [ValidateSet("F001", "F002", "F003", "F004", "F005", "F006", "F007", "F008")]
    [string]$Feature
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $ProjectRoot ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot ".uv-python"
$PytestTemp = Join-Path $ProjectRoot ("tmp\pytest-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $PytestTemp -Force | Out-Null

function Invoke-Uv {
    param([string[]]$Arguments)

    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Push-Location $ProjectRoot
try {
    switch ($Command) {
        "setup" { Invoke-Uv @("sync", "--frozen") }
        "test" { Invoke-Uv @("run", "pytest", "--basetemp", $PytestTemp, "-p", "no:cacheprovider") }
        "lint" {
            Invoke-Uv @("run", "ruff", "check", "src", "tests")
            Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
        }
        "format" {
            Invoke-Uv @("run", "ruff", "check", "--fix", "src", "tests")
            Invoke-Uv @("run", "ruff", "format", "src", "tests")
        }
        "typecheck" { Invoke-Uv @("run", "mypy") }
        "golden" { Invoke-Uv @("run", "python", "tests/golden/validate.py") }
        "migrate" { Invoke-Uv @("run", "alembic", "upgrade", "head") }
        "prepare-f004-review" { Invoke-Uv @("run", "python", "scripts/prepare_f004_review.py") }
        "verify-feature" {
            if ($Feature -eq "F005") {
                Invoke-Uv @("run", "ruff", "check", "src", "tests")
                Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
                Invoke-Uv @("run", "mypy")
                Invoke-Uv @("run", "python", "tests/golden/validate.py")
                Invoke-Uv @("run", "pytest", "--basetemp", $PytestTemp, "-p", "no:cacheprovider")
                Invoke-Uv @("run", "python", "scripts/verify_f005.py")
            } elseif ($Feature -eq "F006") {
                Invoke-Uv @("run", "ruff", "check", "src", "tests")
                Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
                Invoke-Uv @("run", "mypy")
                Invoke-Uv @("run", "python", "tests/golden/validate.py")
                Invoke-Uv @("run", "pytest", "--basetemp", $PytestTemp, "-p", "no:cacheprovider")
                Invoke-Uv @("run", "python", "scripts/verify_f006.py")
            } elseif ($Feature -eq "F007") {
                Invoke-Uv @("run", "ruff", "check", "src", "tests")
                Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
                Invoke-Uv @("run", "mypy")
                Invoke-Uv @("run", "python", "tests/golden/validate.py")
                Invoke-Uv @("run", "pytest", "--basetemp", $PytestTemp, "-p", "no:cacheprovider")
                Invoke-Uv @("run", "python", "scripts/verify_f007.py")
            } elseif ($Feature -eq "F008") {
                Invoke-Uv @("run", "ruff", "check", "src", "tests")
                Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
                Invoke-Uv @("run", "mypy")
                Invoke-Uv @("run", "python", "tests/golden/validate.py")
                Invoke-Uv @("run", "pytest", "--basetemp", $PytestTemp, "-p", "no:cacheprovider")
                Invoke-Uv @("run", "python", "scripts/verify_f008.py")
            } elseif ($Feature -in @("F001", "F002", "F003")) {
                Invoke-Uv @("run", "ruff", "check", "src", "tests")
                Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
                Invoke-Uv @("run", "mypy")
                Invoke-Uv @("run", "python", "tests/golden/validate.py")
                Invoke-Uv @("run", "pytest", "--basetemp", $PytestTemp, "-p", "no:cacheprovider")
            } else {
                throw "No executable verifier is registered for $Feature"
            }
        }
        "check" {
            Invoke-Uv @("run", "ruff", "check", "src", "tests")
            Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
            Invoke-Uv @("run", "mypy")
            Invoke-Uv @("run", "python", "tests/golden/validate.py")
            Invoke-Uv @("run", "pytest", "--basetemp", $PytestTemp, "-p", "no:cacheprovider")
        }
        "run" {
            Invoke-Uv @(
                "run", "uvicorn", "citefin.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"
            )
        }
    }
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $PytestTemp) {
        Remove-Item -LiteralPath $PytestTemp -Recurse -Force
    }
}
