# Zephyr Scale to Qase migration

Migrates test cases, folders, test plans, test cycles and executions from **Zephyr Scale Cloud** into [Qase](https://qase.io).

---

## 1. What this migrates

**Supported source:** Zephyr Scale **Cloud** only, via the public REST API at `https://api.zephyrscale.smartbear.com/v2`.

**Not supported:**

| Not supported | Why |
|---|---|
| Zephyr Scale **Server / Data Center** | Different API surface. Use the Zephyr Enterprise script, or contact us. |
| Zephyr **Squad** / **Essential** | Different product and a different API. Use `qase-zephyr-essential-migration`. |
| Zephyr **Enterprise** | Different product. Use `qase-zephyr-enterprise-migration`. |

**The source is read-only.** The migration never writes to Zephyr Scale or to Jira. Every call against them is a read, so a failed or repeated run cannot damage your source data.

**Jira is only ever contacted to download an attachment.** The script does not call Jira to resolve users, projects or issues. If your environment does not grant Jira access, leave the `jira` block empty and Jira-hosted attachments are skipped with a warning.

---

## 2. Coverage

| Zephyr Scale | Qase | Status | Notes |
|---|---|---|---|
| Project | Project | Full | Matched to an existing Qase project by title, otherwise created with a generated code. `projects.mapping` overrides the target. |
| Folder (`TEST_CASE`) | Suite | Full | Nesting is preserved. |
| Test case | Test case | Full | Title, objective, precondition, steps, priority, status, labels, custom fields. |
| Test step | Step | Full | Description, expected result and test data. Each field is capped at 1000 characters. |
| Test case attachment | Attachment | Full | Files uploaded through the Attachments tab. |
| Component | Tag | Degraded | Qase has no component field, so a component becomes a tag alongside the labels. |
| Label | Tag | Full | Capped at 10 tags per case, see limitations. |
| Custom field | Custom field | Partial | See limitations. |
| Test plan | Milestone | Partial | Name, description and status carry over. Runs are attached to the milestone when the Zephyr cycle is linked to that plan. `due_date` does not carry, see limitations. |
| Test cycle | Run | Full | Name, description, start time from `plannedStartDate`, end time from `plannedEndDate`, milestone from the cycle's linked test plan. Cycles with status `done` or `completed` are marked completed in Qase. |
| Test execution | Result | Full | Status, comment, execution time, elapsed time, attachments. |
| Inline image in rich text | none | **Not migrated** | See limitations. |
| Estimated time on a case | none | **Not migrated** | The Qase bulk case model has no `estimate` field. |
| Users | none | **Not migrated** | Every migrated case and run is attributed to `users.default`. |

---

## 3. Known limitations

Read this section before you run anything. These are the things that generate support email.

**Inline images in rich-text fields are not migrated.** Zephyr Scale serves images embedded in a description or a step from CloudFront, and CloudFront requires a browser-session Forge JWT cookie that the API token cannot obtain. The script replaces each one with a readable `[Image: filename.png]` note so the reference survives in the text, and reports it. **File attachments added through the Attachments tab are migrated normally**, this limitation applies only to images pasted into rich text.

**A run can carry only one milestone.** Each Zephyr Scale test plan becomes a Qase milestone, and a migrated run is attached to the milestone for the test plan its cycle is linked to. Zephyr allows a cycle to be linked to several test plans; Qase allows a run to belong to one milestone. Where a cycle links to more than one, the first is used and the rest are named in the migration report. Cycles linked to no test plan produce runs with no milestone.

**`due_date` on milestones is almost always empty.** Zephyr Scale accepts `plannedStartDate` and `plannedEndDate` when a test plan is created but does not return them on read. The script asks for `plannedEndDate` and uses it when present, which in practice it rarely is.

**Custom field support is partial.** Fields whose values are strings, numbers, dates or single-select map cleanly. Multi-select values are joined into a comma-separated string. Rich-text values are stripped to plain text. User-type fields are coerced to a string. Anything that cannot be mapped is skipped and reported.

**Silent caps are now reported, but they are still caps.** Titles are cut at 255 characters, each step field at 1000, and tags at 10 per case. Every cut produces a line in the migration report naming the case, so you can fix the source and re-migrate that project if it matters.

**Executions with status `in progress` or `not executed` are skipped.** They map to Qase statuses that would overwrite a real result with "untested", so the case is simply left untested in the run instead.

**`runs.created_after` is approximate, and errs on the side of keeping cycles.** Zephyr Scale publishes no creation timestamp on a test cycle, so the filter reads `createdOn` when your tenant happens to return it and otherwise falls back to `plannedStartDate`. A cycle carrying neither is **kept, not dropped**, because a filter must never silently discard data it cannot date. The migration report says how many cycles were kept that way, so you can see when the filter was wider than you asked for.

**Per-case estimated time is not migrated.** The Qase bulk case model has no field for it.

**Users are not migrated.** This script creates no Qase users and reads no user identities. Every migrated case, run and result is attributed to the single user in `users.default`.

---

## 4. Prerequisites

### Zephyr Scale access

1. In Jira, open `Apps > Zephyr Scale > API Access Tokens`.
2. Press **Create access token**, name it, and copy the value. It is shown once.
3. Put it in `config.json` as `zephyr.api_token`, or export it as `ZEPHYR_SCALE_API_TOKEN`.

The token inherits the permissions of the Jira user who created it. That user needs **Browse Projects** on every project you intend to migrate, and Zephyr Scale must be enabled on those projects.

### Qase access

1. Open `https://app.qase.io/user/api/token`.
2. Press **Create new token**, give it **read and write** access to projects, test cases, test runs and attachments.
3. Put it in `config.json` as `qase.api_token`, or export it as `QASE_API_TOKEN`.

The Qase user who owns the token needs a role that can create projects, or you must pre-create the target projects and list them in `projects.mapping`.

### Jira access (optional, attachments only)

Needed only if some attachments are stored in Jira rather than in Zephyr Scale.

1. Open `https://id.atlassian.com/manage-profile/security/api-tokens`.
2. Press **Create API token**, name it, and copy the value.
3. Put your Atlassian account email in `jira.email` and the token in `jira.api_token`.

Read access is sufficient. Leave both blank to disable Jira downloads entirely.

### Nothing needs to be created up front

This migration writes no source ids into custom fields, so there are no fields for you to create in Qase before running.

---

## 5. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
```

Python **3.11 or newer**.

---

## 6. Configure

Edit `config.json`. Every key below is read by the code, and every key the code reads is listed here.

### `qase`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `api_token` | Yes | none | Qase API token. Overridden by `QASE_API_TOKEN`. |
| `host` | No | `qase.io` | Your Qase host. Leave as `qase.io` on the public cloud. On a dedicated cluster set it to your own host, for example `acme.qase.io`, and the API URL is derived from it. |
| `ssl` | No | `true` | Use HTTPS. Leave `true`. |

### `zephyr`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `api_token` | Yes | none | Zephyr Scale API token. Overridden by `ZEPHYR_SCALE_API_TOKEN`. |
| `base_url` | No | `https://api.zephyrscale.smartbear.com/v2` | Zephyr Scale Cloud API root. Change only if SmartBear tells you to. |

### `jira`

Optional. Both keys or neither.

| Key | Required | Default | Purpose |
|---|---|---|---|
| `email` | No | none | Atlassian account email, used only to download Jira-hosted attachments. |
| `api_token` | No | none | Atlassian API token. Overridden by `JIRA_API_TOKEN`. |

### `projects`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `import_all` | No | `false` | `true` migrates every Zephyr Scale project on the tenant. |
| `import` | Yes unless `import_all` | `[]` | Jira project keys to migrate, for example `["ABC", "DEF"]`. |
| `exclude` | No | `[]` | Keys to skip. **Exclusion always wins over inclusion.** |
| `mapping` | No | `{}` | Send a Zephyr project into a specific existing Qase project, for example `{"ABC": "MYPROJ"}`. |

Leaving `import` empty with `import_all` false is an error, not a silent "migrate everything".

### `cases`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `priority_map` | No | `{}` | Override the priority mapping, for example `{"urgent": "critical"}`. Valid targets: `critical`, `high`, `normal`, `low`. |
| `status_map` | No | `{}` | Override the case status mapping, for example `{"in review": "draft"}`. Valid targets: `actual`, `draft`, `deprecated`. |

Built-in priorities: `highest`→`critical`, `high`→`high`, `normal`/`medium`→`normal`, `low`/`lowest`→`low`.
Built-in statuses: `approved`→`actual`, `draft`→`draft`, `deprecated`→`deprecated`.
Anything unmapped falls back (`normal` / `actual`) **and is reported**.

### `runs`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `created_after` | No | `0` | Epoch seconds. Cycles starting before this are skipped, dated from `createdOn` or `plannedStartDate`. `0` means all. Cycles with neither date are kept and reported, see limitations. |
| `status_map` | No | `{}` | Override the execution status mapping. Valid targets: `passed`, `failed`, `blocked`, `skipped`, `in_progress`, `untested`, `invalid`. |

Built-in: `pass`/`passed`→`passed`, `fail`/`failed`→`failed`, `blocked`→`blocked`, `skip`/`skipped`→`skipped`, `in progress`/`wip`→`in_progress`, `not executed`/`unexecuted`→`untested`.

### `users`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `default` | Yes | none | The Qase user who owns everything migrated. Accepts an **email address** or a numeric Qase user id. |

This script migrates no users. Every case, run and result is attributed to this one account.

### `logging`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `level` | No | `info` | `error`, `warn`, `info`, `verbose`, `debug`. Each level includes the ones above it. |
| `write_to_file` | No | `true` | Write a log file under `dir`. |
| `dir` | No | `./logs` | Where log files go. |

`error` and `warn` always reach the console regardless of level, so a run that drops data can never look clean in the terminal.

### `prefix`

| Key | Required | Default | Purpose |
|---|---|---|---|
| `prefix` | No | `zephyr-scale` | Prepended to log and statistics filenames, so parallel migrations do not overwrite each other's output. |

### Secrets in the environment

These override `config.json` and take precedence:

```bash
export QASE_API_TOKEN=...
export ZEPHYR_SCALE_API_TOKEN=...
export JIRA_API_TOKEN=...
```

---

## 7. Validate

```bash
python preflight.py            # or: python preflight.py path/to/config.json
```

Preflight is read-only. It writes nothing to Qase or Zephyr. Exit code `0` means every check passed, `1` means at least one failed.

A green run looks like this:

```
- Config -
  ✅ Config file ./config.json: parses OK
  ✅ qase.api_token (Qase API token)
  ✅ zephyr.api_token (Zephyr Scale API token ...)
  ✅ projects.import: 2 project key(s): ['ABC', 'DEF']

- Zephyr Scale -
  ✅ GET /projects: 7 Zephyr Scale project(s): ['ABC', 'DEF', ...]
  ✅ Project ABC: cases=412, cycles=23, executions=1877, plans=4
  ✅ Project DEF: cases=88, cycles=6, executions=210, plans=1

- Jira (optional) -
  ✅ Jira credentials: someone@company.com

- Qase -
  ✅ Qase auth (GET /v1/project): 12 project(s) in workspace
  ✅ users.default: resolves to Qase user id 4471

✅ Preflight passed, ready to run: python start.py
```

---

## 8. Run

```bash
python start.py                       # uses ./config.json
python start.py path/to/config.json
python start.py --dry-run             # reads everything, writes nothing
```

`--dry-run` runs the entire extraction and mapping pipeline and reports exactly what would be created, without writing to Qase. Unmapped statuses, truncations and attachment problems all surface, so it is the cheapest way to see what a real run will do. It is also available as `QASE_DRY_RUN=1`.

**Expected duration.** Dominated by attachment count, not case count.

| Data volume | Typical duration |
|---|---|
| Under 500 cases, few attachments | 2 to 5 minutes |
| 500 to 5,000 cases | 15 to 45 minutes |
| 5,000+ cases with attachments | 1 to 3 hours |

Qase requests are throttled to 250 per 12 seconds. That limit is built in and is not configurable.

---

## 9. What good output looks like

**Progress is printed per project, not per stage.** Each project prints one line as it starts, and the arrow becomes a green tick when the project list completes.

```
	↪ Importing projects [2/2]
	↪ Importing project: Payments [PAY]
	↪ Importing project: Billing [BIL]
```

Once a project starts there is no per-stage counter, so a large project can sit quiet for a long time while cases, steps and attachments are read. **It is not hung.** Set `logging.level` to `verbose` if you want to watch every request go past.

**Warnings and errors print in colour as they happen**, even at the default level, so a skipped item is visible while the run is still going rather than only in a file afterwards:

```
	! [10:14:02][warn] [PAY][Cases] PAY-T118: title truncated from 289 to 255 characters (Qase limit)
	! [10:14:19][warn] [PAY][Cases] Zephyr priority 'urgent' has no mapping, defaulting to 'normal'. Set cases.priority_map to control this.
	✗ [10:16:41][error] [PAY][Runs] Failed to create run 'Regression 4.2': HTTP 422
```

At the end, two blocks. First the counts, source against target:

```
------ Stats ------

{'projects': {'PAY': {'title': 'Payments',
                      'zephyr-scale': {'suites': 31, 'cases': 412, 'runs': 23, 'milestones': 4},
                      'qase':         {'suites': 31, 'cases': 412, 'runs': 23, 'milestones': 4}}},
 'attachments': {'zephyr-scale': 0, 'qase': 0},
 'custom_fields': {'zephyr-scale': 7, 'qase': 7}}
```

**`attachments` is always `0` in both columns.** Attachments are migrated, they are simply not counted. Verify them in Qase, not from this block.

Then the migration report, listing everything skipped or degraded, with the reason:

```
------ Migration report: 6 skipped/degraded item(s) ------

  [PAY] · 6 item(s)
    ! [Cases] PAY-T118: title truncated from 289 to 255 characters (Qase limit)
    ! [Cases] Zephyr priority 'urgent' has no mapping, defaulting to 'normal'. Set cases.priority_map to control this.
    ! [Cases] PAY-T204: 3 inline image(s) not migrated, kept as [Image: ...] notes: login.png, cart.png, checkout.png
    ! [Runs] Zephyr execution status 'deferred' has no mapping, treated as 'untested' so the result is skipped.
    ✗ [Runs] Failed to create run 'Regression 4.2': HTTP 422
```

`!` is a warning, something skipped or silently defaulted. `✗` is an error, something that failed outright. The report is capped on screen; the full list is always in the statistics files.

**A clean run says so explicitly:**

```
------ Migration report: no skipped or degraded items ------
```

That line is the one to look for. An empty report is not the same as no report, so the script always prints one.

Artifacts written afterwards:

- `logs/<prefix>_zephyr_scale_<timestamp>.log`, the full log at your configured level
- `stats/<prefix>_stats.json`, the counts plus the complete issue list
- `stats/<prefix>_stats.xlsx`, a **Comparison** sheet and a **Migration report** sheet

**Before you call the migration done:** compare the `zephyr-scale` and `qase` columns per entity, and read the migration report rather than only the counts. A run reporting 412 of 412 cases migrated, with 30 priorities silently defaulted and 5 titles truncated, looks identical in the counts to a perfect one. The report is the only place that difference shows.

## 10. Re-run and resume behaviour

**Stated bluntly: a second run creates duplicates.**

| Entity | On a second run |
|---|---|
| Projects | **Reused.** Matched by title, or by `projects.mapping`. |
| Custom fields | **Reused.** Matched by name. Custom fields are workspace-global in Qase. |
| Suites | **Duplicated.** |
| Test cases | **Duplicated.** |
| Milestones | **Duplicated.** |
| Runs and results | **Duplicated.** |

There is no resume, no delta mode and no state file. If a run fails halfway, the safest recovery is to delete the target Qase project and start again, or migrate into a fresh project via `projects.mapping`.

Use `--dry-run` first so the second run is the only real one you need.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401` from Zephyr Scale | Token revoked, or created on a different Jira site. | Regenerate at `Apps > Zephyr Scale > API Access Tokens`. |
| `401` or DNS failure from Qase | Wrong token, or the wrong `qase.host`. | Check `qase.api_token`. On a dedicated cluster, `qase.host` must be your own host (`acme.qase.io`), not `qase.io`. Preflight prints the API URL it resolved. |
| Preflight says a project is not found | The key is a Zephyr Scale project key, not a Jira project key, or Zephyr Scale is not enabled on it. | Use the Jira project key. Confirm the project appears in the `GET /projects` list preflight prints. |
| `0 test cases` for a project | Wrong project key, or the token's Jira user cannot browse it. | Give the user **Browse Projects**, or correct the key. |
| Cases created but not in suites | The folder was not migrated, so the case has no suite to land in. | Check the report for suite failures. Suites must migrate before cases; the order is enforced, so this usually means a folder API error. |
| Attachments missing | Jira-hosted and `jira.*` not set, or the file exceeds the Qase upload limit. | Set `jira.email` and `jira.api_token`. Oversize files are reported by name. |
| `[Image: name.png]` instead of an image | Expected. Inline rich-text images cannot be downloaded with an API token. | See limitations. Re-attach manually if the image matters. |
| `422` on bulk case create | A custom field exists in the workspace but is not scoped to the target project. | Open the field in Qase and add the project to its scope, then re-run. |
| `429` from Qase | Another tool is using the same token concurrently. | Run the migration alone. The built-in throttle assumes it has the token to itself. |
| Statistics XLSX never appears | `pandas` or `openpyxl` missing. | The run prints a warning and still writes the JSON. `pip install -r requirements.txt`. |

---

## 12. Getting help

Email **migrations@qase.io**.

Include:

1. The version, which is the first line of the log file and the last line the run prints.
2. The command you ran and the full console output.
3. Your `config.json` **with every token removed**.
4. The log file from `logs/` and the statistics files from `stats/`.
5. The Zephyr Scale project key and roughly how many cases, cycles and executions it holds.

Do not open a public GitHub issue for a migration problem, and do not paste tokens into email. For a security vulnerability, see [SECURITY.md](SECURITY.md).

**Delete `config.json`, `logs/` and `stats/` once your migration is complete.** They contain credentials and customer data.

Every release is listed in [CHANGELOG.md](CHANGELOG.md).
