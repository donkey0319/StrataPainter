# Memory, history and canonical rasters (T10)

Settings > Memory and history exposes estimated live/peak texture use, retained
history bytes and configurable texture/history/step limits. Applying smaller
history limits releases older steps. Allocation is checked before creating each
texture. Budget failures preserve pixels/history/resolution where applicable;
viewport failure restores an active stroke and leaves controls usable. Applying
a usable budget resumes preview. Undo allocation failure retains its entry.

Paint channels allocate on demand; read-only compositor lookup uses transparent
defaults. Four-channel strokes allocate/snapshot only those four channels.
Compact MRT variants preserve existing shader math. A GPU reduction computes
changed bounds, reads only its final 1x1 result and retains cropped snapshots.
Undo/redo patch exact integer pixel regions. No-op strokes add no history; a
compaction allocation failure can retain the existing full snapshot as fallback.
Polygon fill also allocates/snapshots only enabled channels.

History includes deleted layers, masks, bake/environment snapshots and cropped
paint data. Explicit release and collection update texture accounting. Purpose
labels identify authored channels, strokes, scratch and history. Estimates count
base-level GPU.texture allocations; depth, buffers, mip levels, shader objects,
driver overhead and dedicated residency are excluded. Evaluation records CPU
submission timings/pass counts; the profiling script synchronizes GPU execution.
Project close/history eviction release owned resources. Existing incremental
evaluation below an edited root is retained, and shared paint edits invalidate
all owning sets. Each set owns its composited output buffers.

Shared rasters retain one authored `raster_res`; each set evaluates that source
at its own resolution. Resizing one set preserves a shared source. Painting
through either instance updates the same source and both outputs. Shared masks
and paint effects follow that canonical size. Independent duplication resamples
to the target set. Higher-resolution evaluation is honestly resampling; journal
replay remains T12.

**Cross-resolution canonical raster projects require format v5.** Ordinary projects
remain v3; ordinary independent mask-paint projects remain v4. v1–v4 remain
readable. Legacy archive validation still rejects unsupported cross-resolution
arrays without v5 metadata. Previous runtime guard tests now assert successful
canonical sharing/per-set evaluation; frozen fixture assertions were unchanged.

## Measured qualification

Windows CPython 3.13, RTX 4050 Laptop GPU, driver-reported 6141 MiB VRAM. Fresh
process per source/resolution, same two-triangle plane, four channels, 10px brush,
five samples/stroke, seven strokes and two undo steps. Timings include stroke plus
composite and ctx.finish. One cold sample and six warm samples; full data is in
`.artifacts/memory-t10-profile/*.json`. T00 used the preserved cefb609 source archive
on the same GPU. These small workloads are not general asset performance promises.

| Size | Source | Estimated peak MiB | Warm p50 ms | Warm p95 ms |
|---|---|---:|---:|---:|
| 2048 | T00 | 1604.8 | 36.9 | 38.1 |
| 2048 | T10 | 1033.4 | 38.1 | 41.7 |
| 4096 | T00 | 6416.8 | 1049.9 | 1744.4 |
| 4096 | T10 | 4131.5 | 124.6 | 131.2 |

2K reduces memory with a small latency cost. 4K reduces both substantially;
paging/driver behavior likely contributes to T00's result (an inference, not
measured residency). Both return to the same fixed viewport/utility baseline of
786456 estimated bytes after close; UV-only lifecycle checks return to 24 bytes.
Default product limits on this setup are 5120 MiB textures, 1536 MiB history and
24 steps. Measured 4K peak leaves about 988 MiB inside that texture budget and
about 1 GiB outside it for excluded allocations. Smaller GPUs need lower settings;
complex projects may exceed the budget and should fail with an actionable message.

`tests/memory_check.py --gpu .artifacts/memory-t10-final`: 9/9 CPU/GPU scenarios pass.
`tests/memory_ui_check.py .artifacts/memory-ui-t10-final`: 7/7 real UI assertions pass;
screenshot reviewed. Final regression passes 11 UV, 7 brush, 14 channel, 14 material,
27 transaction, 13 persistence and 6 effect scenarios; frozen settings/all 16 maps
and portable v3 roundtrip pass. Feature suite remains 101/102 with only known
low-flow accumulation failure. Logs `.artifacts/t10-final-*.log`.

Single agent; earlier changes preserved; no commit/release. No new dependency.
CPU checks added to CI; remote execution and other GPUs unqualified. ModernGL
Uniform.array_length was checked against official documentation before sparse
shader use. T11 is next; T12 should use this canonical/checkpoint storage model.


T20 adds a non-reserving compound budget check before initial stroke target,
snapshot and buffer allocation. A late buffer-budget failure now rejects before
publishing empty lazy paint channels. The default budget is unchanged; admission
does not claim to predict untracked driver memory or later dynamic resource loads.
The new failure reproducer and ten memory cases pass. Core 4K and custom-scalar
4K profiles have different measured working sets; the latter cannot start its
stroke within the default 5 GiB limit in this fixture and reports that boundary
explicitly. Detailed distributions and ownership/OS-memory distinctions are in
VALIDATION.md.
