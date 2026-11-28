# Post-integration: additive contract and ownership

Base: origin/main5648852d64189ffd7269c277002f6fbc40c8039a; verified runtime3f83310.
The original R01–R66/T01–T67 and case/spec/official validators remain unchanged.
The user authorized N01–N19 and independent subagents in separate worktrees.

## Ownership

- Root: common architecture/ports/composition/main/migration graph/contracts generation, sales bridge, N08/N09/N15, functional frontend, integration/release. Visual assets follow the supplied Cloud Design archive; no competing redesign.
- Platform: core/jobs.py, core/domain_jobs.py, core/models.py if needed, modules/platform/**, contracts/platform.py and new contracts/labor.py, new platform tests, POST_PLATFORM status. N02/N05/N06.
- Algorithms: modules/cutting/**, contracts/cutting.py, cutting tests/new experimental evidence and POST_ALGORITHMS status. N01/N03/N10; controlled N11/N12/N14 and N13 decision.
- Intelligence (second wave): modules/intelligence/**, contracts/intelligence.py, providers/gateway and intelligence tests/status. N04/N07/N19/N17 decision, bounded live trial. It must agree parent checkpoint hooks with Platform before changing batch callbacks.
- Independent reviewer: tests/post_review/**, scripts/post_review_*.py, independent review/status docs. Freeze exam/oracle before seeing candidates; no product implementation in this role.

No agent edits another worktree. No parallel changes to shared DTO, lock, generated schemas or migration graph. Each implementation publishes concrete DTOs before dependent UI work. Root reviews/amends these contracts and regenerates OpenAPI/TS from Python DTOs after merge.

## N02: run budget and accepted rows

RunRequest adds optional total_budget_seconds and export_reserve_seconds; absent values preserve existing behavior.
Persist UTC expiry and budget configuration. Reconstruct process-local monotonic deadlines after restart; never reuse a previous process's monotonic timestamp.
First produce a complete validated bundle, then spend remaining improvement budget. Preserve previously accepted exports.
Accepted AI rows pass validation and persistence in the parent coordinator; child events carry an attempt/generation fence.
Reuse identity includes dataset/input ID and text, exact KB, prompt/tools schema, verifier, selected model and nonsecret config; inventory-dependent answers also bind exact relevant inventory context.
Coordinator preloads compatible accepted rows into the worker snapshot; output provenance distinguishes model/deterministic/fallback/reuse. Late old worker events cannot change current results. Partial rows never become complete answers.csv.

## N05: labor study

Canonical DTO file contracts/labor.py, existing LaborStudy/U07 remains the export target.
POST/GET /labor-studies; GET /labor-studies/{id}. Study: dataset_id/name/protocol/start_definition/end_definition/observer/version.
POST /labor-studies/{id}/measurements starts a record with pair_id/task_id/task_input_ref/input_hash/operator/method(manual|app)/planned_order(manual_first|app_first).
POST /labor-studies/{id}/measurements/{measurement_id}/{pause|resume|finish|attest} uses dataset_id, expected_version, operator, note and Idempotency-Key.
Finish adds result_ref/error_count/rework_seconds; attest adds active_seconds and explicit human_confirmed=true.
Elapsed and human-attested active time stay separate; rework is a descriptive subset, not added twice. Interrupted measurements need explicit human review. Events remain append-only.
GET /labor-studies/{id}/export returns existing LaborStudy objects plus pairing evidence; final export requires at least ten distinct complete human-attested pairs of identical task/input hash. Retain negative manual-minus-app savings. UI cannot manufacture human confirmation.

## N06: workflow queue

GET /workflow/queue?dataset_id returns dataset_id, items and counts. Item: subject_type,subject_id,version,reason_code,responsible_role,next_action,route_hint,summary.
Read-only projection from canonical order/basket/reminder/fact state. No second business state or automatic workflow transition. UI links to existing correction actions.

## N01/N03/N10/N13: cutting domain

Root derives eligible original IDs from current real buyer registry, canonical remnants and >=3 actual BuyerMatches.
C2 N01 helper receives canonical input, validated baseline, eligible set and bounded budget; client-supplied IDs never establish evidence.
If five eligible originals are already free, retain baseline without solving. If total eligible<5, return evidence shortage. Otherwise bounded alternate solve with area floor and eligible-use cap; lower-area option remains separate with exact delta and explicit selection.
N03 explanations bind current known unfinished parts, quantities, reservations, exclusions and joint geometry. No unknown demand forecast; ordinary selection remains the time-limit fallback. Reorder only after preregistered comparison.
GET /plans/{id}/new-requirements?dataset_id derives NEW material/dimensions/quantity/area/part IDs/reasons from the current valid plan. Unknown reasons stay unknown. No invented purchased sheets or purchase price.
N13 may expose geometric edge/gap slack as a read-only aid; contest5mm/3mm tolerances remain identical and no defect probability is inferred.

## Root projections

N08: allowed aggregate comparison by product group/channel/client type with sample sizes, denominators, completeness and small-group warnings; Russian questions resolve only to an allowlist, never arbitrary SQL. Preserve organizer M1–M5 definitions.
N09: versioned piece-label/pick-list snapshots contain identity/material/dimensions/location/version/check state; no secret or mutation capability in QR. Old tag lookup resolves current canonical record and warns about changed version; existing server version checks govern mutations.
N15: result passport exposes input hashes/code/config/time/validated improvement history/stop reason. Unknown/global gaps remain unknown; pool optimum is not global optimum.

## Acceptance

N01–N19 have a separate matrix with implemented/connected/verified/SHA/evidence/limits. Every promoted candidate has boundary/failure tests and an independent final review.
Preserve original tested EXE/ZIP. New exports and release paths are versioned; no overwrite of user final materials. Fresh locked checks, real API/browser/native/relocation/backup/recovery, changed-input exports and exact official validators precede publication.
Live model accuracy is distinct from deterministic/cache/fallback; prepaid trial needs explicit authorized endpoint/model, conservative token cap and no automatic paid fallback.
