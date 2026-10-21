# sentry-triage

Turns new production Sentry errors into Jira tickets and, when a code change makes sense, a draft pull request.

Built for an AI Day hackathon. It is a working prototype, not a finished product.

## The problem

A production error appears in Sentry. Someone has to notice it, work out where it comes from, write a ticket, and decide whether code needs to change. Errors get missed, tickets are inconsistent, and whoever picks one up starts from zero.

## What it does

For each production issue first seen in the last 24 hours (configurable):

1. Skips it if a Jira ticket already exists for that Sentry issue (matched by a `sentry-<id>` label), so reruns never duplicate.
2. Fetches the latest event: stack trace, request, release.
3. Runs headless [Claude Code](https://claude.com/claude-code) in a throwaway worktree of your repo. It reads the code the trace points at and finds the probable root cause. It edits files only if a small, safe change in that repo would fix it.
4. Creates a Jira ticket with the root cause, the suggested fix, a severity estimate and a link to the Sentry issue.
5. If there is a real code change, pushes a branch and opens a **draft** PR linked to the ticket. If the cause is a third party, infrastructure, data or another codebase, it creates only the ticket and explains why no PR is needed.

## Support tickets as a second input

Besides Sentry, it can start from a ticket in a support Jira project that is assigned to a bot user:

```sh
python3 triage.py --support                  # every open support ticket assigned to support_bot
python3 triage.py --support --ticket SUP-123 # one specific ticket
```

The flow is the same, with the support ticket's text instead of a stack trace. Claude first decides whether it is a bug in the repo, a data or config problem, a question or a feature request. A new engineering ticket is created for it (labeled `msup-<key>` so reruns skip it), a draft PR only when there is a code change, and the new ticket is assigned to `assignee` in the config. The support ticket itself is never reassigned or closed: the only thing written to it is one comment linking the new ticket and PR.

Support tickets can contain customer details and their text is sent to an LLM, so check your data policy before pointing this at real tickets.

## Safety

- **Dry-run is the default.** It runs the analysis and prints the ticket and diff it would create. Nothing is written to Jira or GitHub.
- Real writes need `--live`.
- PRs are always drafts and are never merged. Nothing pings anyone.
- At most 5 issues per run (`--limit`), and only the `production` environment.
- The analysis agent can read and edit files in the throwaway worktree only. The script, not the agent, does the commit and push.

## Setup

Needs `python3`, `git`, `gh`, [`acli`](https://developer.atlassian.com/cloud/acli/) (logged in to Jira), and the `claude` CLI.

```sh
cp config.example.json config.json   # fill in your Sentry org/project, Jira site/project, repo path
export SENTRY_AUTH_TOKEN=...         # read-only: event:read and project:read
python3 triage.py                    # dry-run on issues first seen in the last 24h
python3 triage.py --since 14d        # wider window
python3 triage.py --issue 123456789  # one specific Sentry issue
python3 triage.py --live             # really create tickets, branches and draft PRs
```

`config.json` is gitignored. If your Jira project has required custom fields, put them in `jira_fields`.

## Limits

- The suggested fix is a starting point. It has not been run through the test suite, and the PR says so. A human decides whether it is worth keeping.
- The root cause is an estimate. A nil value might be a code bug or a data problem, and the agent cannot always tell which.
- One Sentry project and one repo for now.
- The support flow was tested in dry-run only so far.
- Not built yet: Slack alerts, PagerDuty on-call, a dedicated bot user instead of a personal account, a second source such as Coralogix, running the specs before opening the PR.

## Files

- `triage.py` is the whole tool.
- `CONTEXT.md` is the glossary (Sentry Issue, Ticket, Draft Fix, and so on).
