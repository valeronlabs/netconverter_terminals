# NetConverter CLI installer for Windows (PowerShell 5.1+ or PowerShell 7).
#
#   irm https://netconverter.ai/install.ps1 | iex
#
# With options (IT/MDM):
#   & ([scriptblock]::Create((irm https://netconverter.ai/install.ps1))) -Yes -Workspace D:\configs
# or, through `iex`, set $env:NETCONVERTER_INSTALL_YES=1, $env:NETCONVERTER_INSTALL_NO_CONNECT=1,
# $env:NETCONVERTER_INSTALL_WORKSPACE='D:\configs' first.
#
# Installs uv (if missing) and `netconverter-cli` from PyPI, falling back to the
# latest GitHub release wheel after checking its SHA-256. Then signs you in and
# connects your AI assistants to a workspace folder. Safe to run again: each step
# skips what is already done. It never asks for, prints or stores a secret.
param(
    [switch]$Yes,
    [switch]$NoConnect,
    [string]$Workspace,
    [switch]$Help
)

function Install-NetConverter {
    param([bool]$Yes, [bool]$NoConnect, [string]$Workspace)

    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is much faster without it
    if ($PSVersionTable.PSEdition -ne 'Core') {  # Windows PowerShell 5.1 may default to TLS 1.0
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    }

    $Package = 'netconverter-cli'
    $Repo = 'valeronlabs/netconverter_terminals'
    $Python = '3.12'
    if (-not $Workspace) { $Workspace = Join-Path $HOME 'migrations' }
    if ($Workspace -like '~*') { $Workspace = Join-Path $HOME $Workspace.Substring(1).TrimStart('\', '/') }

    function Say([string]$Text) { Write-Host '==> ' -NoNewline -ForegroundColor Cyan; Write-Host $Text }
    function Warn([string]$Text) { Write-Warning $Text }
    # Windows PowerShell 5.1 turns a native command's redirected stderr into a terminating
    # error under 'Stop'; run the commands whose stderr is discarded under 'Continue'.
    function Quiet([scriptblock]$Block) {
        $saved = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & $Block 2>$null } finally { $ErrorActionPreference = $saved }
    }
    $Interactive = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected

    # -- 1. uv ------------------------------------------------------------

    foreach ($dir in @((Join-Path $HOME '.local\bin'), (Join-Path $HOME '.cargo\bin'))) {
        if (($env:Path -split [IO.Path]::PathSeparator) -notcontains $dir) {
            $env:Path = $dir + [IO.Path]::PathSeparator + $env:Path
        }
    }
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Say ("uv {0} is already installed" -f ((uv --version) -split ' ')[1])
    } else {
        Say 'Installing uv (https://docs.astral.sh/uv)'
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw 'uv was installed but is not on PATH; open a new PowerShell window and run this again'
        }
    }

    # -- 2. netconverter-cli ----------------------------------------------

    # A copy installed from a wheel file stays on it unless replaced; --force moves it to PyPI.
    $flags = @('--quiet', '--python', $Python, '--upgrade')
    $receipt = Join-Path (Join-Path (uv tool dir).Trim() $Package) 'uv-receipt.toml'
    if ((Test-Path $receipt) -and (Select-String -Path $receipt -Quiet `
            -Pattern '^requirements = .*(path|url|git|directory|editable) = ')) {
        $flags += '--force'
    }
    Say "Installing $Package from PyPI"
    uv tool install @flags $Package
    if ($LASTEXITCODE -ne 0) {
        Warn 'PyPI install failed; using the latest GitHub release instead'
        $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
        $tag = [string]$release.tag_name
        if ($tag -notmatch '^v\d+\.\d+\.\d+$') { throw "could not find the latest release of $Repo" }
        $wheel = "netconverter_cli-$($tag.Substring(1))-py3-none-any.whl"
        $base = "https://github.com/$Repo/releases/download/$tag"
        $tmp = Join-Path ([IO.Path]::GetTempPath()) ("netconverter-install-" + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $tmp | Out-Null
        try {
            Say "Downloading $wheel and SHA256SUMS from the $tag release"
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$wheel" -OutFile (Join-Path $tmp $wheel)
            Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS" -OutFile (Join-Path $tmp 'SHA256SUMS')
            $want = $null
            foreach ($line in Get-Content (Join-Path $tmp 'SHA256SUMS')) {
                $parts = $line.Trim() -split '\s+'
                if ($parts.Count -eq 2 -and $parts[1].TrimStart('*') -eq $wheel) { $want = $parts[0].ToLower() }
            }
            if (-not $want) { throw "SHA256SUMS has no entry for $wheel" }
            $got = (Get-FileHash -Algorithm SHA256 (Join-Path $tmp $wheel)).Hash.ToLower()
            if ($got -ne $want) { throw "checksum mismatch for $wheel; nothing was installed" }
            Say "SHA-256 verified: $wheel"
            uv tool install --quiet --python $Python --force (Join-Path $tmp $wheel)
            if ($LASTEXITCODE -ne 0) { throw 'uv tool install failed' }
        } finally {
            Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
        }
    }
    Quiet { uv tool update-shell } | Out-Null

    $bin = (uv tool dir --bin).Trim()
    $nc = @('netconverter.exe', 'netconverter') | ForEach-Object { Join-Path $bin $_ } |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $nc) { throw "netconverter was not found in $bin" }
    $version = Quiet { & $nc --version }
    if ($LASTEXITCODE -ne 0 -or -not $version) { $version = 'netconverter is installed' }
    Say $version

    # -- 3. sign in -------------------------------------------------------

    if ((Quiet { & $nc whoami } | Out-String) -match '"signed_in": true') {
        Say 'Already signed in to NetConverter'
    } elseif ($Interactive) {
        Say 'Signing in to NetConverter (your browser opens)'
        & $nc login --clerk
        if ($LASTEXITCODE -ne 0) { Warn 'sign-in did not finish; run: netconverter login --clerk' }
    } else {
        Warn 'no interactive session for sign-in; each user runs: netconverter login --clerk'
    }

    # -- 4. workspace and assistants ---------------------------------------

    New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
    Say "Workspace: $Workspace"

    if (-not $NoConnect) {
        if ($Yes) {
            Say 'Connecting every AI assistant found on this computer'
            & $nc --workspace $Workspace connect --all --yes
        } elseif ($Interactive) {
            Say 'Connecting AI assistants (each change is shown before it is made)'
            & $nc --workspace $Workspace connect --all
        } else {
            Warn "no interactive session to confirm changes; run: netconverter --workspace `"$Workspace`" connect --all"
        }
    }

    Write-Host ''
    Write-Host 'NetConverter CLI is ready.'
    Write-Host "  - Put the configurations you want to work on in $Workspace"
    Write-Host '  - Fully quit and reopen each AI assistant, then ask: "What NetConverter tools do you have?"'
    Write-Host '  - Open a new PowerShell window if `netconverter` is not found yet'
    Write-Host '  - netconverter update keeps it current'
}

if ($Help) {
    Write-Host 'NetConverter CLI installer'
    Write-Host ''
    Write-Host 'Usage: install.ps1 [-Yes] [-NoConnect] [-Workspace PATH]'
    Write-Host ''
    Write-Host '  -Yes             never prompt (IT/MDM); sign-in is skipped without an interactive session'
    Write-Host '  -NoConnect       install and sign in only; do not connect AI assistants'
    Write-Host '  -Workspace PATH  folder your AI may hand to NetConverter (default: ~\migrations)'
    return
}

# `irm | iex` cannot pass parameters, so the same options are read from the environment.
# The function throws instead of calling `exit`, which would close the user's window.
Install-NetConverter `
    -Yes ($Yes.IsPresent -or $env:NETCONVERTER_INSTALL_YES -eq '1') `
    -NoConnect ($NoConnect.IsPresent -or $env:NETCONVERTER_INSTALL_NO_CONNECT -eq '1') `
    -Workspace $(if ($Workspace) { $Workspace } else { $env:NETCONVERTER_INSTALL_WORKSPACE })
