# Bounded C2 research decisions

Protocol v2 frozen at bb7f480 before trials; corrected runtime baseline a079a28. Six changed synthetic snapshots, seeds7/19/41, all four variants, fresh process each:20s, one OS CPU, workers1,1GiB sampled native memory ceiling. Developer Windows10, not clean Windows11 or the jury reference machine. Independent reviewer exam was not read.

Old interrupted9s pilot (11 observations) is retained in pilot-9s-partial.json. It exposed the existing first-complete/minimum-free defect; its results are not silently replaced. V2 reuses its mathematical inputs openly; this is a regression comparison, not a hidden exam.

| Family | Seed | Variant | Area mm² | Full orders | Free originals | Locations | First complete ms | Native peak MiB | Process stop |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| dense | 7 | baseline | 5010600 | 11 | 5 | 6 | 2.89 | 133.41 | common_deadline |
| dense | 7 | N11_directed | 5010600 | 11 | 5 | 6 | 2.96 | 133.38 | process_finished |
| dense | 7 | N12_locations | 5010600 | 11 | 5 | 6 | 3.15 | 133.62 | common_deadline |
| dense | 7 | N14_components | 5010600 | 11 | 5 | 6 | 4.34 | 133.36 | process_finished |
| dense | 19 | N11_directed | 5019900 | 13 | 5 | 6 | 3.21 | 168.73 | common_deadline |
| dense | 19 | N12_locations | 5019900 | 13 | 5 | 6 | 2.83 | 166.68 | common_deadline |
| dense | 19 | N14_components | 5019900 | 13 | 5 | 6 | 2.77 | 166.63 | common_deadline |
| dense | 19 | baseline | 5019900 | 13 | 5 | 6 | 3.58 | 167.67 | common_deadline |
| dense | 41 | N12_locations | 5030300 | 11 | 5 | 6 | 2.95 | 166.64 | common_deadline |
| dense | 41 | N14_components | 5030300 | 11 | 5 | 6 | 2.85 | 168.43 | common_deadline |
| dense | 41 | baseline | 5030300 | 11 | 5 | 6 | 3.20 | 167.45 | common_deadline |
| dense | 41 | N11_directed | 5030300 | 11 | 5 | 6 | 3.73 | 166.18 | common_deadline |
| mixed | 7 | N11_directed | 4614000 | 13 | 5 | 6 | 2.05 | 152.98 | process_finished |
| mixed | 7 | N12_locations | 4587700 | 12 | 5 | 6 | 2.07 | 184.93 | common_deadline |
| mixed | 7 | N14_components | 4583200 | 12 | 5 | 6 | 1.93 | 157.77 | common_deadline |
| mixed | 7 | baseline | 4587700 | 12 | 5 | 6 | 1.92 | 150.46 | process_finished |
| mixed | 19 | N12_locations | 4582500 | 12 | 5 | 6 | 2.21 | 151.98 | process_finished |
| mixed | 19 | N14_components | 4570700 | 12 | 5 | 6 | 1.84 | 163.10 | process_finished |
| mixed | 19 | baseline | 4582500 | 12 | 5 | 6 | 1.71 | 152.10 | process_finished |
| mixed | 19 | N11_directed | 4582500 | 12 | 5 | 6 | 1.86 | 166.90 | process_finished |
| mixed | 41 | N14_components | 4572800 | 12 | 5 | 6 | 1.61 | 162.44 | common_deadline |
| mixed | 41 | baseline | 4570600 | 11 | 5 | 6 | 1.62 | 153.57 | common_deadline |
| mixed | 41 | N11_directed | 4570600 | 11 | 5 | 6 | 1.90 | 158.98 | common_deadline |
| mixed | 41 | N12_locations | 4570600 | 11 | 5 | 6 | 1.84 | 154.14 | process_finished |

## Decisions against unchanged preregistered thresholds

- N11_directed: **NO PROMOTION**. Area deltas in paired dense7/19/41,mixed7/19/41: `[0, 0, 0, 26300, 0, 0]` mm²; wins `{'dense': 0, 'mixed': 1}`; median delta 0mm²; common guards True.
- N12_locations: **NO PROMOTION**. Area deltas in paired dense7/19/41,mixed7/19/41: `[0, 0, 0, 0, 0, 0]` mm²; wins `{'dense': 0, 'mixed': 0}`; median delta 0mm²; common guards False.
- N14_components: **NO PROMOTION**. Area deltas in paired dense7/19/41,mixed7/19/41: `[0, 0, 0, -4500, -11800, 2200]` mm²; wins `{'dense': 0, 'mixed': 1}`; median delta 0mm²; common guards True.

N12 improved actual location count in 0/6 pairs (required>=3); actual location labels are not travel distance or human time savings. N11 directed moves were observed in 4/6 final diagnostic reports; a short budget can end before this phase, so no claim of benefit on unexercised cases. N14 retains one global master; the study does not license naive independent component merging.

All 24/24 selected complete incumbents independently passed the unchanged C2 geometry validator and requested free>=5. Only events at<=20s were selected; late final returns/diagnostics are recorded but cannot improve the selected score. Native OS PeakWorkingSet includes native memory; it is not tracemalloc or a universal total allocation bound. Other developer-host activity is not claimed absent. No pool optimum is a global optimum.

Full trial metrics, hashes, actual solver stop reasons and process stops are in comparison.json. Placement rows were independently validated during each trial but are not retained in that scalar report; rerun compare.py for a new measured run. No failed row/variant was removed. Experimental classes remain confined to compare.py; production still imports CuttingSolver.

## N03 / N13

N03 preserves ordinary candidate order. scarcity-comparison.json retains36 synthetic actual HTTP/service responses:11 warm exact jointly validated witnesses,18 negative no_proof cases, 6 tiny-budget limited cases and1 cold-import limited response. Warm HTTP p95=28.26ms; cold native startup=1044.15ms. Optional proved advice is enabled; global ordering is not promoted.

N13 is enabled only as a read-only validated geometric projection: minimum edge excess over5, axis-separation gap excess over3, and separate tempered whole-piece deviation tolerance±2. It changes neither placement nor tolerances and predicts no defect probability or human savings.

No600s heavy profile, contest-wide score, real demand forecast, clean-machine qualification or human measurement is claimed by this bounded study.
