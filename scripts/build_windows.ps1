$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Windows x64 runner required' }
uv sync --locked --all-groups
if ($LASTEXITCODE) { throw 'uv sync failed' }
pnpm install --frozen-lockfile
if ($LASTEXITCODE) { throw 'pnpm install failed' }
pnpm build
if ($LASTEXITCODE) { throw 'web build failed' }
uv run pyinstaller --noconfirm packaging/GlassFlow.spec
if ($LASTEXITCODE) { throw 'PyInstaller failed' }
& ./dist/GlassFlow/GlassFlowDiagnostics.exe --smoke-native-worker
if ($LASTEXITCODE) { throw 'Frozen native worker failed' }
