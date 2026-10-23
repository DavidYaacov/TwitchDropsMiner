# October 2026 Twitch compatibility migration

Implemented on the Docker branch on 2026-10-23, starting from
`a4407518bc843b61f73cd463102bcf2afcbc4570`. This document describes the
commit introducing this file so future upstream migrations can identify
behavior that must survive conflict resolution.

## Sources and scope

| Source | Behavior adapted here |
| --- | --- |
| [Asrus21 PR #1](https://github.com/Asrus21/TwitchDropsMiner/pull/1), head `5f90c0acaddc0d0b3c59dbabd6a3e4d6e01a702c` | Client fallback, persisted client selection, saved-token client adoption, channel-based campaign discovery, website channel URLs, and account-specific channel checks. |
| [Asrus21 PR #2](https://github.com/Asrus21/TwitchDropsMiner/pull/2), head `641c2b3dec28c627fdb328f480cb601b13d9afdd` | Quoted `cast("JsonType", ...)` avoids the post-login runtime `NameError` from a type-checking-only import. |
| [Asrus21 PR #4](https://github.com/Asrus21/TwitchDropsMiner/pull/4), head `35ccc94dadb8ebf0f4e98de772b64849d888c410` | Missing drop metadata defaults, subscription/non-watch drop filtering, partial channel batch recovery, and discovery diagnostics. Adapted to bounded discovery instead of copying its scanner dependencies. |
| [Upstream channel.py at f693b0c](https://github.com/DevilXD/TwitchDropsMiner/blob/f693b0ca41301ac2282f3978713479efebe0490e/channel.py) | Activate playlist watching and HEAD every media chunk instead of the fork's active Spade path. Retain the fork's empty-list/error handling. |

[Asrus21 PR #3](https://github.com/Asrus21/TwitchDropsMiner/pull/3) global
scanning, its 30-minute cache, game-wide channel inference, and
`drops_games.json` are not included. There is no new persistent cache to migrate.

[Upstream PR #1202](https://github.com/DevilXD/TwitchDropsMiner/pull/1202)
expiry prioritization is deferred. Existing expiry and claim behavior remains.
If adopted later, port game selection, active-campaign selection, deadline
triggers, and shutdown/reload cleanup together. Preserve shared-channel
`get_active_campaigns()`. Test future starts and the optimistic five-minute
allowance; the proposal prefers at least one finishable drop, not an entire
campaign's rewards.

## Integration map

- `constants.py`: client-name lookup and discovery limits.
- `settings.py`: new keys and defaults through the existing settings serializer.
- `twitch.py`: login fallback, token adoption, discovery, inventory resilience,
  and one shared batch query/check path for directory and ACL channels.
- `channel.py`: website URLs, stream-update checks, and active playlist watching.
- `web_gui.py`: reports the selected client and discovery setting in `/api/state`.
- `test_compatibility.py`: isolated regression tests. Existing web tests retain
  coverage for reconnect/revoke, removed campaigns, and shared-channel mining.

Do not replace the Docker web GUI with upstream desktop GUI code, or remove
the fork's multiple-active-campaign behavior when resolving upstream conflicts.
No runtime dependencies or Python version requirement were added.

## Settings and data

All runtime data stays under `TDM_DATA_DIR` (`/app/data` in Docker). Existing
cookies and settings do not need to be deleted or manually converted.

| Key | New-install default | Migration behavior |
| --- | --- | --- |
| `client_type` | `SMARTBOX` | Existing files gain the default. Try the saved client first, then SMARTBOX, MOBILE_WEB, ANDROID_APP, WEB without duplicates. Save accepted selection; a valid saved token adopts its issuing client. Unknown names reset to SMARTBOX. |
| `campaign_discovery` | `true` | Existing files gain the default. File-configured; web settings saves preserve it. |
| `available_drops_check` | `true` | Existing explicit values, including `false`, survive. Discovery also enables checks, so both flags must be false to disable them. |

The two new keys appear in `/api/state` but have no new dashboard controls.
Stop the application before manually editing its settings file. Continue using
the project's serializer for existing sets, URLs, and priority modes.

Valid tokens are reused across known clients and cookie hosts. Validation server
errors do not erase cookies; invalid tokens trigger device login. Client changes
update the session User-Agent and refresh the device ID for a different site.
Device-code responses are validated before their fields are used.

## Discovery, channel checks, and limits

Discovery searches priority games and games already present in the inventory:
at most 25 games and 30 live channels per game, using the existing GQL limiter
and batches of 20 channel queries. On an empty account, add the desired game's
Twitch name to the priority list and refresh. This is not a complete global
campaign catalogue. Excluded games are filtered out.

Discovered campaigns are limited to channels that actually reported them.
Known inventory progress is not overwritten. Explicit known link status is
preserved; when no link status is available, account-specific availability is
used as the eligibility signal, as in PR #1. Link game accounts normally and
confirm server-side progress before relying on unattended mining.

Missing drop names/start dates use campaign metadata; end dates must come from
the drop or campaign. No expiry is invented. Invalid dates, subscription-only
and non-watch drops are removed. Dependent drops with missing or cyclic
prerequisites are also removed. A malformed campaign does not discard other
campaigns. Reloading clears stale campaign lookup entries.

Failed channel batches leave other answers usable. Unanswered channels remain
unknown rather than becoming explicit negatives. When at least one channel in
a batch check reports campaigns, successful empty responses disqualify their
channels. If every channel returns empty or fails, batch checks retain current
eligibility and warn, preserving PR #1's fallback. Individual stream updates
honor explicit empty responses; failed responses retain fallback eligibility.

`Campaign discovery:` appears in logs; `Drops scan:` also appears in dashboard
activity. Counts cover newly discovered campaigns, channels asked/answered,
answers with drops, and skipped data. Skipped counts are observations, not
necessarily unique campaign IDs. File logging still requires `--log`; Docker's
default `-vv` sends diagnostics to `docker logs`.

## Validation

Use Python 3.13 with `requirements-dev.txt` installed:

```powershell
python -B -m unittest -v test_compatibility test_twitch test_web_gui test_web_debug
python -m ruff check --no-cache .
python -B main.py --version
```

The implementation was checked with Python 3.13.16. Tests use synthetic Twitch
responses, isolated temporary settings/cookies, and a local HTTP server. They
cover fallback/polling, restored and expired tokens, client/header switching,
settings reload, partial batches, inventory preservation, malformed metadata,
prerequisite filtering, channel updates, and playlist failures.

Docker is unavailable in the implementation environment: image build, Linux
volume ownership, container SIGTERM/recreation, and live authenticated Twitch
progress require the deployment checks below. An HTTP health check or a local
countdown is not proof that Twitch credited watch time.

## Rollout and rollback

1. Record the running image ID/digest, effective Compose configuration, and
   actual volume mounted at `/app/data`. Keep the old image locally.
2. Stop the miner gracefully. Back up the entire data directory, including
   cookies, settings, and any `.new` recovery files, outside the repository.
   Clone it into a separate canary volume; never run two miners for the account.
3. Build the reviewed commit explicitly:

   ```powershell
   docker build --build-arg TDM_COMMIT_SHA=<commit> -t twitchdropsminer:compat-<commit> .
   ```

4. Start that image against the copied volume on localhost port 18080. Keep
   non-root `app` ownership and `/app/data`. Check dashboard startup, saved login,
   discovery diagnostics, priority/exclusion behavior, and channel rotation.
   If needed, override the command with `python main.py -vv --log`.
5. Observe Twitch-confirmed progress for 10-15 minutes without competing account
   viewing. Stop and recreate the canary to verify saved client/session/settings.
   Verify SIGTERM completes and the volume remains writable by `app`.
6. Promote via an external Compose override selecting the exact image and
   `pull_policy: never`, or an immutable registry digest. The repository's
   Compose file uses a published `latest` image with `pull_policy: always`;
   `docker compose up` alone does not build this source checkout.
7. To roll back, stop the candidate, retain its data for diagnosis, and start the
   recorded old image against a separate volume restored from the pre-rollout
   snapshot. Restore ownership to `app`. Avoid `docker compose down --volumes`.

The old settings loader removes unknown keys, so retain the original snapshot.
Restoring cookies cannot undo Twitch-side token revocation; using reconnect
during testing can require a fresh login after rollback.
