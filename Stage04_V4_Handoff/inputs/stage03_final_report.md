# Stage 03 final release: retain S4 + T1

**Release decision.** Use projected Separate sentence ends plus S4's additional punctuation cuts (minimum distance 12), retain the original Vietnamese segments with T1 number handling, and leave official alignment and semantic decisions to Stage 04. This is ready for full-corpus **source-preserving preprocessing**, with explicitly unmatched Han regions. It is not evidence for releasing a fully mapped or semantically verified corpus. No full-corpus live alignment was run.

## Matched density experiment

Cap_01 Han 001–002, same 905 original code points, same 12 Vietnamese segments, same T1 and downstream mapper. Availability is recall of *interior reference endpoints* in the generated segments; the final reference edge is excluded. Exact compares whole mapped Han spans for the same VI ID. Agreed **boundaries** (9) and agreed **pairs** (8) have different denominators.

| Method | Segments | Available CG / DS / agreed boundaries | Downstream exact CG / DS / agreed pairs | Mean IoU CG / DS | Mapped Han coverage | Unresolved rows |
|---|---:|---:|---:|---:|---:|---:|
| S4 | 40 | 8/11 · 10/11 · 8/9 | **5/12 · 7/12 · 5/8** | .922 / .923 | 92.8% | 0 |
| S5 | 49 | 8/11 · 10/11 · 8/9 | 2/12 · 3/12 · 2/8 | .817 / .819 | 86.7% | 0 |
| S6 | 63 | 8/11 · 10/11 · 8/9 | 2/12 · 2/12 · 2/8 | .759 / .753 | 75.4% | 0 |
| S7 | 70 | 8/11 · 10/11 · 8/9 | 2/12 · 2/12 · 2/8 | .761 / .754 | 73.5% | 0 |
| S8 | 164 | 9/11 · **11/11 · 9/9** | 2/12 · 2/12 · 2/8 | .465 / .462 | 36.4% | 2 |
| S9 | 202 | 9/11 · 10/11 · 8/9 | 2/12 · 2/12 · 2/8 | .414 / .405 | 22.1% | 2 |

**Excess density degraded downstream agreement on this benchmark.** S8 supplied all DS reference boundaries but recovered only two exact DS pairs. Extra available cuts did not ensure the downstream API used them. S9 kept mandatory Separate ends in addition to its five-character grid, explaining why some segments are shorter than five. Original text reconstruction remained exact for every variant. Protected-interior conflicts are logged; preserving an original API boundary takes precedence over protection. See [density and fresh cases](segmentation_density_comparison.xlsx) and [availability, precision, recall, F1 and missing offsets](boundary_availability.xlsx).

## Context size and fresh windows

**Recommend an initial context of 10 original VI segments around a valid page anchor.** Select the corresponding Han pages from the mapping, not by matching segment counts. Ten was the smallest tested size that matched the larger contexts on the common five Silver IDs (`PILOT-005` through `009`). With S4, 5 VI segments gave 0/5 CG and 0/5 DS exact and mean IoU .432/.399; 10, 15, 20 and 30 each gave 1/5 CG, 3/5 DS and .901/.905. Only one of the five common pairs has agreed boundaries, so that subset cannot establish a general optimum. The tested Han regions also expand with mapped context (2, 2, 3, 4, 4 pages respectively). This recommendation concerns Stage 04 evaluation; the Stage 03 handoff retains all mapped VI candidates. The [window-size workbook](window_size_comparison.xlsx) distinguishes all eligible references from common references.

S4 and S5 were frozen after Silver development, with S9 retained as a stress control. Four fresh two-page windows were then evaluated: Cap_01 021–022 and 040–041; Cap_02 020–021 and 035–036. These used identical page-anchored contexts across methods (47, 116, 55 and 50 VI IDs respectively), **not** a second independent validation of the 10-segment size. S4 completed 4/4, S5 3/4 and S9 4/4. On Cap_01 040–041, S5 returned application error `000500`; S9 succeeded but had 42 unresolved rows versus 15 for S4. Conversely S9 achieved full mapped coverage on Cap_02 020–021. There was no monotonic increase in API failures with density: all six density configurations and all ten size comparisons returned success, including the most fragmented control. Four fresh windows and one attempt per novel payload do not establish failure probabilities. No independent fresh semantic labels were available; these are reliability and mapping comparisons only.

## Corpus audit and handoff

The [coarse audit](coarse_alignment_audit.xlsx) inventories 145 Han pages in 73 paired/single windows. The 20 entirely unsupported two-page windows are Cap_02 053–092. Cap_02 052 is also unsupported, despite sharing a window with partially supported 051. Stage 02 currently supplies anchored T1 text through the **right half** of 051. The left half starts Quyển VI. The local 445-page `Phu_bien_tap_luc_2007.pdf` has Quyển VI beginning at PDF page 405 and continuing to 439; page 440 opens the afterword. The referenced `VIET_0405-0439.xlsx` is absent from the working tree, although the anchors JSON contains a `Cap_02_VI` section. Thus for 052–087 there is translation material but no current processed VI workbook/mapping for it. Han 088–089 are afterword candidates without verified page matches. Han 090 resembles the opening of Book V; 091–092 contain only `R16061` and `01` in the OCR. Retain these as unverified source, not `MISSING` translations. No page has been established to lack a translation in every source.

**Stage 04 contract:**

- `han_segments.jsonl`: one record per selected S4 segment, stable `id_zh`, `window`, `method`, `text_original`, NFC/whitespace-normalized `text_zh`, page endpoints, `global_raw_span`, `normalized_source_spans`, `source[]` and window-level `mapping_status`. Spans are zero-based Unicode code points, end exclusive; `file_span` indexes the UTF-8-SIG-decoded file without newline conversion. Source slices, in order, reconstruct `text_original`. `global_raw_span` indexes concatenated trimmed page bodies in Cap_01 then Cap_02 order. The release sample contains Silver and fresh windows, not the entire corpus.
- `stage04/<Cap>/S4/NNNN-segments.csv`: UTF-8-SIG, `id_zh,text_zh,han_page_start,han_page_end,global_raw_start,global_raw_end`. Files are keyed by start page; a segment can cross a page boundary.
- `window_context.jsonl`: each window's ordered VI IDs, original text, submitted `text_t1`, normalized-to-original spans, workbook row and VI page endpoints, and page-mapping evidence. T1 retains one original VI segment per submitted line. No splitting at thousands separators or decimal punctuation. Verified thousands groupings may change spelling but not value. Alignment evaluation uses newline-delimited Han and VI, existing index-and-text resolution and whitespace-only continuous aggregation. A mapped group or high score does not set a label.
- Production `prepare` emits source-linked inputs and preserves unmatched context. Failed/unavailable Separate results return a nonzero status and keep the source pages in the production context log for retry. `evaluate` alone invokes Alignment. Stage 04 owns official merging, window reconciliation, local refinement, semantic review and labels.

## Evidence and limits

The [metrics file](metrics.json) records 33 new requests, cache provenance, timing, coverage and group types. `cases/` contains inputs/mappings, projected segments and results; `cache/` and `requests.jsonl` retain raw live responses, with exact-payload reused artifacts referenced instead of duplicated. The [review workbook](semantic_review.xlsx) has 497 distinct source-linked predictions including unresolved rows, with repeated occurrences retained under each record. Verified positive: 0; verified negative: 0; unknown: 497. A semantic-positive rate cannot be estimated. The observed loss with excess splitting is a downstream reference-agreement result, not a claim that S4 has proven semantic superiority. Stage 03 optimization is closed for this round.
