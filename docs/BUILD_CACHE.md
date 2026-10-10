# Shared build results

Set `WOLF_SHARED_CACHE` to one absolute directory for every checkout and stage
on the same host. The development runners in the size workspace default to
that workspace's `.shared-cache`. A runner copied elsewhere should keep the
same setting. `WOLF_JOBS` still limits build workers.

The cache contains immutable step records, SHA-256 output blobs, the compiled
host helper, and B1, HLZ, LZ16 and LZSA1 encoder results. Palette fits, sprite
layouts and audio packs use the same step result store. Existing stage records
and blobs are imported automatically; they are checked before reuse.

A command finds candidate records, then checks the reachable code, input
contents, missing files, directory listings, environment, profile fields and
memory-map values recorded by the existing tracer. A command match alone is
never a hit. Missing or damaged output blobs cause a rebuild. Output files are
restored with APFS clones when available, otherwise copies. Audio report paths
and receipt hashes are rebound to the destination stage and source checkout;
its binary audio files are unchanged.

Writers publish blobs first and complete manifests last, through atomic rename.
Each manifest has its own content-derived filename. There is no mutable shared
JSON index. An OS advisory lock covers one command or codec input; a waiting
builder checks for the completed result again. A killed writer releases its
lock. Builds never remove shared results. Traces, file-stat memoization and
output ownership records remain private to each stage.

`WOLF_SHARED_CACHE=0` disables sharing. `WOLF_STEP_CACHE=0` also disables step
reuse; set both to zero when measuring an uncached build. A shared cache can be
removed when no builds are using it. The next build computes its results again.

Run `python3 tools/test_shared_cache.py` for the focused cache correctness tests.

Prepared music packs use one traced conversion per song. A song's capsule
contains its recipe, prepared instrument inputs and licensed IMF bytes. Pack
validation and provenance run outside that conversion, so another song or an
unrelated build helper cannot invalidate it. Actual file reads, reached code
and accessed profile values still determine reuse. Shared results restore
into each stage's own `.song-cache`; converted banks never share writable
work directories. Source receipts are refreshed for the current build.

`WOLF_JOBS` also limits song conversion. Independent fits may take unused
song slots, but nested work cannot exceed that budget. Native arithmetic and
bounded reuse within one conversion speed empty-cache builds too.

Python code keys ignore comments and docstrings, including nested docstrings.
Compiler source fingerprints use the same rule; parsed profile TOML is keyed
by its values. Ordinary reads of source files as data still count every byte.
The interpreter's zip-import probe does not make its entry script a data input.

Step record format 3 rejects older records once, so the first build after this
update can rebuild existing results. Later documentation-only edits reuse the
new records. Run `python3 tools/test_comment_keys.py` to check this boundary.
