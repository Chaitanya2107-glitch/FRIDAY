# Clear mode and Spotify status

The owner reported confusing gaming-mode replies, a fixed Connect Spotify quick action despite
an existing connection, and no current-mode indicator in the tray.

- Mode changes lead with the resulting mode, even when switching from another mode.
- Repeating an active mode is idempotent: no off/on messages, repeated steps or app closures.
- A mode that was enabled remains reported as on when its optional setup steps fail; setup failure
  is stated separately.
- Named questions such as `is gaming mode on` and `gaming mode status` read state without changing it.
- No explicit mode means Normal mode. Corrupt or unavailable state means unknown, rather than Normal.
- `GET /api/v1/system/status` returns typed mode and Spotify saved-connection
  status. It makes no model or Spotify API calls, exposes no credentials and changes no settings.
- Tray menu and tooltip display the selected mode. Quick actions display Spotify's connection with connect/disconnect
  controls appropriate to that connection. Connected means FRIDAY has a saved OAuth login; it does
  not claim that Spotify is currently playing or that the saved login has been verified online.
- Poll status with the existing five-second tray loop and refresh immediately after a tray command.
  Offline/read failures clear prior connection/mode claims and show Status unavailable.

Validation covers mode repeat/switch/setup failure, named status questions,
dynamic menu labels/tooltips, quick-action refresh, offline/failed reads and token-free API responses.
The real saved Spotify connection was read without altering it and was connected.
