# Post-integration actual HTTP evidence

Current changed-input local acceptance: **PASS**, [http-new-inputs-final](http-new-inputs-final/README.md),
runtime `4ee5812a65157acd7aa504df3d994497f608e29a`. This includes root55049e4, Intelligence efbf8de,
and terminal dependency fix f090a75. The runtime tree stayed immutable during spawn/parent verification.

Historical [http-new-inputs](http-new-inputs/README.md) is explicitly **blocked before the unknown-SKU fix**;
its original downloaded bytes and defect response are retained. [Dependency replay witness](dependency-replay-before-fix.json)
records17 real failed card dependencies before the separate minimal coordinator fix. Historical failures are not presented as passes.

Scope: actual fresh uvicorn/TCP/SQLite, changed source inputs, original organizer validator, byte downloads,
budget/partial failure/API cancellation, durable accepted rows and host restart. This evidence does not accept
live AI accuracy, human labor measurements, clean Windows, physical scanner, browser or packaged EXE; root owns those checks.
