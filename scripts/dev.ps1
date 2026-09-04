param(
    [Parameter(Mandatory = $false, Position = 0)]
    [ValidateSet("setup", "test", "lint", "format", "typecheck", "golden", "check", "migrate", "run")]
    [string]$Command = "check"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $ProjectRoot ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot ".uv-python"

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
        "test" { Invoke-Uv @("run", "pytest") }
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
        "check" {
            Invoke-Uv @("run", "ruff", "check", "src", "tests")
            Invoke-Uv @("run", "ruff", "format", "--check", "src", "tests")
            Invoke-Uv @("run", "mypy")
            Invoke-Uv @("run", "python", "tests/golden/validate.py")
            Invoke-Uv @("run", "pytest")
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
}
