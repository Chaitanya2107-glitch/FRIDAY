# Native installed-app catalog

The transparency fix was completed and committed first (`689b48e`). This change
separates favourites from launch authority: installed apps are searchable whether
or not they are pinned, including when the Python bridge is offline.

## Discovery and authority

- Current-user and common Start Menu Programs folders, obtained with Windows
  known-folder APIs. Recursion accepts `.lnk` files, skips uninstaller shortcuts
  and reparse points, and bounds traversal depth/count. Original shortcuts retain
  their installer-configured arguments and working directory.
- HKCU/HKLM App Paths, both 32-bit and 64-bit registry views. Only existing local
  absolute `.exe` paths are accepted; registry values containing arguments are
  rejected. Environment expansion uses a Windows API, never a shell.
- AppsFolder COM enumeration for packaged Store apps. Friendly names and AUMIDs
  are read from Shell metadata. Activation uses IApplicationActivationManager,
  with no user-supplied process arguments.

The catalog lives in memory and refreshes on startup, every five minutes, and
from Rescan apps. Scanning occurs on a separate COM-initialized thread, outside
the catalog lock; readers use the previous snapshot until replacement. Icons
are extracted lazily into an in-memory PNG cache. No disk/PATH search, PowerShell
discovery, telemetry, app-index uploads or extra persistent index file is used.

Each target has a stable opaque ID derived from its normalized launch identity.
The UI receives IDs, friendly names and source labels; executable paths and
Store activation details stay native. `launch(kind:"app", id)` must resolve that
ID in the current native catalog. An arbitrary typed path/command can never
become a launch target. Missing entries fail with No app found / Rescan apps.

## Search, favourites and recent history

`open <name>` resolves natively before any Python request. Bare names suggest
native app matches; exact names or explicitly selected suggestions launch by ID.
Known plugin/assistant command prefixes retain priority. Selecting then completing
with Tab preserves the selected ID, including when display names are duplicated.
Native suggestions render as soon as available, independently of bridge latency.

The config schema remains v1 with additive fields:

- An indexed favourite stores `{id,name,app_id,visible,path:""}`. `app_id` must
  be an opaque `app-<32 hex digits>` identifier. It is revalidated against the
  current catalog on launch. Rename/reorder/hide do not affect search authority.
- Manual favourites retain `{id,name,path,visible}` with a local `.exe`/`.lnk`.
- `recent_apps` stores at most 100 `{id,last_used,count}` records in the same
  config file. Launch success updates it through locked atomic saves; metadata
  conflicts never misreport an already completed launch as wholly failed.

Exact matches outrank prefixes, words, substrings, subsequences and edit-distance
matches. Bounded recency bonuses prefer recently used similar matches without
allowing them to outrank a better text-match band. Settings and suggestion rows
pin/unpin by app ID. Favourites remain drag-reorderable with keyboard alternatives.

## Initial validation

Local metadata checks found all three sources (193 Start Menu shortcut records,
124 App Paths records before de-duplication, 60 Store app records), with no scan
warnings. Start Menu and Store icon extraction returned PNG data. Regular Rust
tests cover path parsing, bounded traversal, stable IDs, fuzzy/recency ranking and
rejection of non-indexed launch IDs. An explicit ignored test reads real local
metadata without launching apps:

```powershell
cargo test --manifest-path island/src-tauri/Cargo.toml --offline live_installed_app_metadata -- --ignored --nocapture
```

This development is authorized by the user's installed-app launching request;
no release/publication or existing FRIDAY startup change is authorized or performed.
