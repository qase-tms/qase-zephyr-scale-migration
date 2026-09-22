# Security Policy

## Reporting a vulnerability

**Do not open a public issue or discussion, and do not email a vulnerability report to the general migrations address.**

Report privately through GitHub's private vulnerability reporting on this repository: **Security > Report a vulnerability**. This creates a private advisory visible only to the maintainers.

Please include the affected version or commit, what an attacker could achieve, and the steps to reproduce.

We will acknowledge the report and keep you updated until it is resolved.

## What this tool handles

This script reads from Zephyr Scale Cloud and writes into Qase. Understanding what it touches will help you judge whether something is a vulnerability.

**Credentials.** Three, all read from `config.json` or from the environment:

| Credential | Needs | Used for |
|---|---|---|
| Zephyr Scale API token | Read | Everything read out of Zephyr Scale |
| Qase API token | Read and write | Everything written into Qase |
| Jira email + API token | Read, optional | Downloading an attachment that is hosted in Jira rather than in Zephyr |

They are held in memory for the duration of the run. **No credential is written to a log file or printed at any level**, including `debug`.

**Known limitation: attachment downloads are not host-scoped.** An attachment URL returned by Zephyr Scale can point at the Zephyr API host, at your Jira site, or at SmartBear's CloudFront CDN. For every attachment the downloader tries, in order: the Zephyr token as an `Authorization` header, the same token as a `jwt` cookie, then Jira Basic auth if configured. It does not check the URL host first, so the Zephyr token can be sent to a Jira or CloudFront host, and Jira credentials can be sent to a Zephyr or CloudFront host.

All three are hosts you already trust with this data, and every request is a `GET` over HTTPS, so the practical exposure is low. It is still wider than it needs to be, and scoping each credential to its own host is a known improvement we have not made. If your threat model does not allow the Zephyr token to reach your Atlassian tenant, leave `jira.email` and `jira.api_token` blank and migrate attachments manually.

**Source systems are read-only.** Every call against Zephyr Scale and Jira is a `GET`. The migration has no code path that writes, updates or deletes anything in either system, so a failed or repeated run cannot damage your source data.

**Jira access is limited to downloading attachments.** The script does not call Jira to resolve users, projects or issues. Leave `jira.email` and `jira.api_token` blank and Jira-hosted attachments are skipped with a warning; nothing else changes.

**No user data is read or created in Qase.** This script migrates no users and has no SCIM client. It reads the Qase user list once, only to resolve `users.default` when you give it an email address instead of a numeric id. Every migrated case, run and result is attributed to that single account.

**Inline images are not downloaded, and this is not worked around.** Zephyr Scale serves images pasted into rich text from CloudFront behind a Forge JWT that only Atlassian's Forge runtime issues to the Zephyr app inside a browser. This script does not capture, store or replay a browser session, and holds no session file of any kind. Those images are replaced with `[Image: filename]` notes and reported at the end of the run.

**Customer data on disk.** Test case content, cycles, executions, attachments, account identifiers and internal URLs pass through the process. Two directories hold it afterwards:

- `logs/` can contain test case content and API error bodies
- `stats/` contains per-project counts and the full list of skipped or degraded items, including case keys and titles

Both are gitignored. Neither is needed once a migration is signed off.

## Handling your own credentials

- **Prefer the environment over the file.** `QASE_API_TOKEN`, `ZEPHYR_SCALE_API_TOKEN` and `JIRA_API_TOKEN` override `config.json` and take precedence, so a config file you paste into a support ticket carries no secrets.
- Use tokens scoped to the minimum permissions the migration needs. The Zephyr Scale and Jira credentials only ever need read access. The Qase token needs write access only to projects, cases, runs and attachments.
- The Zephyr Scale token inherits the permissions of the Jira user who created it. Create it as a user who can browse only the projects being migrated.
- Revoke every token used for a migration once it is finished.
- Never commit `config.json`. It is gitignored, but a file added under a different name will not be.
- **Delete `config.json`, `logs/` and `stats/` when the migration is signed off.** Logs from a large migration can reach several gigabytes and contain full API payloads.

## If a credential is exposed

Revoke it first, then clean up. A token removed from a file but not revoked is still live, and a commit deleted from a public repository stays readable by hash.
