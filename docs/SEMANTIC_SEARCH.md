# Offline semantic search

`plugins/semantic_search` indexes only folders you explicitly select. No roots
are selected by default. It uses SQLite FTS5 and local ONNX embeddings, merges
keyword/vector ranks using reciprocal rank fusion (constant 60), boosts exact
filenames, and returns up to five distinct files with their best chunk.

Install dependencies with FRIDAY's Python environment:

```powershell
venv/Scripts/python.exe -m pip install -r plugins/semantic_search/requirements.txt
```

The normal root requirements also include FastEmbed. Plugin loading never runs
pip or downloads a model. Restart a backend predating this feature once to load
the private command routing; later plugin changes use normal discovery/reload.
Rebuild/restart Island to load the new snippet renderer.

## Try it

Enter these in FRIDAY's command bar, chat, voice, or Island:

```text
prepare search model
index folder "C:\Users\you\Documents\Notes"
list indexed folders
show index size
find the pdf about thermodynamics
search my notes for heat engine efficiency
what did my notes say about entropy
find transactions type:slides
find quantum folder:"Physics" this month
find thermodynamics in the Physics folder from last week
open result 2
show more search results
pause indexing
resume indexing
reindex
stop indexing folder "C:\Users\you\Documents\Notes"
delete search index
confirm delete search index
```

Commands use whole-string regexes and FRIDAY's existing wake-word/politeness
normalization. Spoken result numbers one through five work. While this plugin
is enabled, these search phrases use its selected roots, replacing the legacy
file/Chrome matcher for those phrases. Disable the plugin to use that matcher.

The first index/search use prepares the model in the background. `prepare search
model` explicitly prepares or retries it. A model card explains the one-time
download; the backend console shows the download library's file/byte progress.
Indexing cards show phase/counts/folder at most once a second and a completion
card reports counts and elapsed time. Indexing and model preparation never run
on the event loop. If weights are unavailable offline, FRIDAY says so plainly;
extraction and keyword search continue. Retry preparation after connecting once.

Results print as text with filename, folder, page/slide, approximately
200-character snippet, and RRF score (a ranking score, not a probability).
Island initially shows three results and a **Show more** chip for the remaining
two. Choose **Result N actions** to see **Open file**, **Open containing folder**,
and **Copy path**. Result references expire after ten minutes. File actions
recheck roots, exclusions and existence, and accept opaque references rather
than client-supplied paths. Other plugins' text sources have no file actions.

## Storage and settings

Everything persistent belongs to `%APPDATA%\FRIDAY\plugins\semantic_search\`
(or the external absolute `FRIDAY_USER_DATA` root). The database is
`index.sqlite3`, weights are in `models/`, and settings are in `settings.json`.
Neither document text nor weights are stored in this repository. The index is
local plaintext; it uses the same OS account protection as your documents.

Settings keys are optional; preserve unrelated keys when editing settings:

| Key | Default | Meaning |
| --- | --- | --- |
| `indexed_roots` | `[]` | Absolute paths, normally managed through commands. |
| `include_code` | `false` | Include `.py`, `.js`, `.java`, `.c`, `.cpp`. |
| `max_file_mb` | `25` | Positive maximum file size in MiB. |
| `indexing_paused` | `false` | Persisted pause; resume with the command. |
| `embedding_backend` | `"fastembed"` | Or `"sentence_transformers"` for the optional fallback. |
| `model_name` | `"BAAI/bge-small-en-v1.5"` | A supported FastEmbed model; the fallback defaults to `sentence-transformers/all-MiniLM-L6-v2`. |
| `local_model_folder` | `""` | Absolute folder with already downloaded model assets. No download is attempted for this folder. |

After editing model/settings options, use `reload plugins`. A backend/name/local
folder change invalidates vectors while retaining keyword text; missing vectors
are filled during reindex. For FastEmbed, the local folder must contain the
ONNX/tokenizer/config assets in that model's expected layout. Copy the complete
cached snapshot, not just a single `.onnx` file. The optional sentence-transformers
backend uses an exported SentenceTransformer model folder. No `trust_remote_code`
is enabled. The fallback requires `sentence-transformers` (already a legacy
FRIDAY dependency); it is unnecessary on the tested Python 3.12 environment.

FastEmbed 0.9.1 and ONNX Runtime 1.30.0 were installed and exercised on Windows
AMD64 / Python 3.12.8: BGE-small produces 384-dimensional float32 vectors.
Inference always uses local assets; only explicit/background preparation may
download weights. See [FastEmbed's constructor contract](https://github.com/qdrant/fastembed/blob/main/fastembed/text/text_embedding.py).

## Indexing rules

- Read `.txt`, `.md`, `.rst`, first 200 lines of `.csv`, `.pdf` with `pypdf`,
  `.docx` with python-docx, and `.pptx` with python-pptx. Unsupported formats,
  including images, are skipped. PDF pages and presentation slides are retained.
- Chunk each page/slide/text into approximately 250 words with 40 words overlap.
  Offsets are character offsets within that page/slide/text.
- Empty/scanned PDFs are stored as `needs OCR`, counted in status/completion,
  and never sent for OCR. Damaged/encrypted files are recorded as errors.
- Skip `node_modules`, `.git`, `venv`, `__pycache__`, AppData, Windows, Program
  Files, hidden folders/files, links/junctions, `.nosearch` trees, oversize files,
  and secret-looking names (`.env`, `.pem`, `.key`, `id_rsa`, `.kdbx`, password,
  credential/secret patterns and Office lock files). Explicit roots also undergo
  these checks. A newly created `.nosearch` purges that tree on the next pass.
- Office archives expanding beyond 100 MiB or 10,000 entries are treated as
  unreadable, to bound malformed/compressed input expansion.
- Unchanged mtime/size avoids both hashing and extraction. Changed stamps trigger
  SHA-256; identical content only updates stamps. Deletions remove FTS and vectors.
- Each file's chunks/FTS replacement commits atomically. A persisted `pending`
  status and missing embeddings are retried after restart, including external-only
  indexes with no selected folders. Transient extraction errors are retried without
  rehashing unchanged files. External sources are
  independent of filesystem cleanup. The vector matrix loads lazily in memory.
- The managed background thread uses Windows below-normal thread priority and
  sleeps between files/batches, resting for three times measured thread CPU time
  to target approximately 25% of one core. This is a duty-cycle target, not a hard
  CPU quota; library initialization and native worker overhead can differ.
- Startup resumes selected roots; subsequent scans run on demand and every 15
  minutes after activity events indicate the user is idle. Unknown activity is
  treated as active. No watchdog dependency is added.

Type filters: `type:pdf`, `type:slides`, `type:notes`, `type:code`, and natural
phrases such as `the pdf about ...`. Notes includes plain text, markdown, rst,
csv and docx. Folder filters match substrings. **Last week** means the preceding
Monday-to-Monday calendar week; **this month** starts on the local month's first
day. Date filtering uses file modification time, not creation time.

`delete search index` asks for confirmation, valid for one minute. Confirming
clears text, vectors and selected roots in the worker, vacuums the database and
truncates its WAL. It keeps your original documents and downloaded model cache.
`cancel delete search index` cancels the question. This does not promise forensic
erasure of filesystem backups or storage-device snapshots.

## Other plugins

```python
search = api.get_service('semantic_search')  # Look up at use time, after reloads.
if search is not None:
    search.index_text('lecture:2026-11-06', 'A local transcript...', {
        'title': 'Lecture 7', 'folder': 'Lectures', 'type': 'notes',
        'modified_at': 1793923200,  # optional Unix seconds
        # 'page': 3 or 'slide': 3 are optional positive integers
    })
    hits = search.search('thermal reservoirs', filters={'type': 'notes'}, k=5)
```

`index_text(source_id, text, metadata)` upserts one external source and schedules
embedding. It returns source ID and chunk count. `search(query, filters, k)` is
synchronous, local-only, returns JSON-safe result dictionaries, and never downloads.
It loads an already cached model on a cold API call and falls back to keywords if
the model is missing or busy; it never queues behind an active download.
Filters also accept `modified_after`/`modified_before` Unix timestamps. `k` is
1–100. Consumers own their threads/UI and must keep returned snippets private.

Documents/query text never enter plugin events or logs. Bus cards contain only
safe filenames/counts and opaque references. Island loads snippets through the
authenticated loopback results route with caching disabled, keeping them out of
event history. Chat/voice dispatch before legacy AI context, return `private`,
skip conversation history and TTS, and refuse remote requests. This preserves
offline operation even when FRIDAY's normal provider is a cloud service.

## Tests

```powershell
venv/Scripts/python.exe -B -m pytest tests/semantic_search -q
venv/Scripts/python.exe -B -m pytest tests/semantic_search -q -m "not slow"
venv/Scripts/python.exe -B -m pytest tests -q
Set-Location island
npm.cmd test
npm.cmd run build
```

The fast suite uses deterministic fake vectors and temporary files. The corpus
has 20 synthetic documents across all supported document formats. The evaluation
list contains 15 queries, including three without matching vocabulary. Real-model
evaluation is marked `slow`, never downloads, blocks network connections, and
automatically skips when this plugin's cached/local model is unavailable.
