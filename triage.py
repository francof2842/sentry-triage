#!/usr/bin/env python3
"""Turn new production Sentry issues into Jira tickets and draft-fix PRs.

Dry-run by default: runs the analysis and prints what it would create.
`--live` creates the Jira ticket, pushes a branch and opens a draft PR.
Needs SENTRY_AUTH_TOKEN (see ~/.config/coralogix.env), plus acli, gh, git, claude.
"""
import argparse, json, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))  # copy config.example.json and fill it in
ORG = CFG["sentry_org"]
JIRA_SITE = CFG["jira_site"]
REPO_DIR = os.path.expanduser(CFG["repo_dir"])
BASE = CFG.get("base_branch", "main")
LABEL = "auto-triage"
ASSIGNEE = CFG["assignee"]  # ponytail: a person while testing, swap for a bot user later
JIRA_PROJECT = CFG["jira_project"]
JIRA_FIELDS = CFG.get("jira_fields", {})  # extra required custom fields for your Jira project
PROMPT = """You are triaging a production error for the application in this repo.

Sentry issue:
{issue}

Read the code the stack trace points at and find the probable root cause.
Only edit files if a small, safe code change in THIS repo would fix it. Follow CLAUDE.md. Do not commit.
If the cause is a third party, infra, data, config or a frontend library, make no edits.

Your final reply must be ONLY a JSON object, no prose:
{{"title": "short ticket title", "severity": "low|medium|high",
  "root_cause": "2-4 sentences", "fix_summary": "what was changed, or why no code change is the right fix",
  "pr_needed": true or false}}"""


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"FAILED {' '.join(cmd[:3])}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def sentry(path, **params):
    url = f"https://sentry.io/api/0/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ['SENTRY_AUTH_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def summarize(issue):
    ev = sentry(f"organizations/{ORG}/issues/{issue['id']}/events/latest/")
    frames = []
    for e in ev.get("entries", []):
        if e["type"] == "exception":
            for v in e["data"]["values"]:
                frames += [f for f in v.get("stacktrace", {}).get("frames", []) if f.get("inApp")]
    req = next((e["data"] for e in ev.get("entries", []) if e["type"] == "request"), {})
    return json.dumps({
        "url": f"https://{ORG}.sentry.io/issues/{issue['id']}/",
        "title": issue["title"], "culprit": issue["culprit"], "events": issue["count"],
        "users": issue["userCount"], "firstSeen": issue["firstSeen"], "release": (ev.get("release") or {}).get("version"),
        "request": f"{req.get('method')} {req.get('url')}" if req else None,
        "inAppFrames": [f"{f.get('filename')}:{f.get('lineNo')} in {f.get('function')}: {(f.get('context') or [[0, '']])[-1][1].strip() if f.get('context') else ''}"
                        for f in frames[-8:]],
    }, indent=2)


def existing_ticket(issue_id):
    out = run(["acli", "jira", "workitem", "search", "--jql",
               f'project = {JIRA_PROJECT} AND labels = "sentry-{issue_id}"', "--limit", "1", "--fields", "key"])
    m = re.search(rf"{JIRA_PROJECT}-\d+", out)
    return m.group(0) if m else None


def analyze(issue_text):
    wt = tempfile.mkdtemp(prefix="sentry-triage-")
    run(["git", "-C", REPO_DIR, "fetch", "origin", BASE, "-q"])
    run(["git", "-C", REPO_DIR, "worktree", "add", "-d", wt, f"origin/{BASE}", "-f"])
    out = run(["claude", "-p", PROMPT.format(issue=issue_text), "--permission-mode", "acceptEdits",
               "--allowedTools", "Read,Grep,Glob,Edit,Write", "--output-format", "json"], cwd=wt)
    reply = json.loads(out)["result"]
    # ponytail: first {...} block in the reply, Claude is told to return JSON only
    result = json.loads(re.search(r"\{.*\}", reply, re.S).group(0))
    diff = run(["git", "diff"], cwd=wt)
    return wt, result, diff


def adf(text):
    """Plain text to Jira's document format: one paragraph per line, URLs as links."""
    def inline(line):
        parts = re.split(r"(https?://\S+)", line)
        return [{"type": "text", "text": t, **({"marks": [{"type": "link", "attrs": {"href": t}}]} if t.startswith("http") else {})}
                for t in parts if t]
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": inline(l)} for l in text.split("\n") if l.strip()]}


def create_ticket(issue, result):
    description = (f"{result['root_cause']}\n\nSuggested fix: {result['fix_summary']}\n\n"
                   f"Severity (Claude's estimate): {result['severity']}\n"
                   f"Sentry: https://{ORG}.sentry.io/issues/{issue['id']}/\n"
                   f"Events: {issue['count']}, users: {issue['userCount']}, first seen {issue['firstSeen']}\n\n"
                   "Created automatically by sentry-triage. Close it if it is not worth fixing.")
    payload = {"projectKey": JIRA_PROJECT, "type": "Bug", "summary": f"[Sentry] {result['title']}",
               "description": adf(description), "assignee": ASSIGNEE, "labels": [LABEL, f"sentry-{issue['id']}"],
               "additionalAttributes": JIRA_FIELDS}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
    return re.search(rf"{JIRA_PROJECT}-\d+", run(["acli", "jira", "workitem", "create", "--from-json", f.name])).group(0)


def open_pr(wt, key, result):
    branch = f"auto-triage/{key}"
    msg = f"fix({key}): {result['title']}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
    run(["git", "checkout", "-q", "-b", branch], cwd=wt)
    run(["git", "add", "-A"], cwd=wt)
    run(["git", "commit", "-q", "-m", msg, "--no-verify"], cwd=wt)
    run(["git", "push", "-q", "-u", "origin", branch], cwd=wt)
    body = (f"Auto-generated draft by sentry-triage for https://{JIRA_SITE}/browse/{key}.\n\n"
            f"{result['root_cause']}\n\n{result['fix_summary']}\n\nReview before merging, this was not tested by a human.\n\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
    return run(["gh", "pr", "create", "--draft", "--title", f"fix({key}): {result['title']}",
                "--body", body], cwd=wt).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=CFG["sentry_project"], help="Sentry project slug ")
    ap.add_argument("--since", default="24h", help="first seen within, e.g. 24h or 14d")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--issue", help="triage one Sentry issue id instead of searching")
    ap.add_argument("--live", action="store_true", help="really create tickets, branches and PRs")
    a = ap.parse_args()

    if a.issue:
        issues = [sentry(f"organizations/{ORG}/issues/{a.issue}/")]
    else:
        issues = sentry(f"projects/{ORG}/{a.project}/issues/", query=f"is:unresolved environment:production firstSeen:-{a.since}")
    print(f"{len(issues)} production issue(s), mode: {'LIVE' if a.live else 'dry-run'}")
    for issue in issues[: a.limit]:
        print(f"\n== {issue['id']} {issue['title'][:80]}")
        if key := existing_ticket(issue["id"]):
            print(f"   already has {key}, skipping")
            continue
        wt, result, diff = analyze(summarize(issue))
        print(f"   [{result['severity']}] {result['title']}\n   cause: {result['root_cause']}\n   fix: {result['fix_summary']}")
        has_pr = result["pr_needed"] and diff.strip()
        if not a.live:
            print(f"   would create ticket{' and draft PR' if has_pr else ' (no PR)'}")
            if has_pr:
                print(diff)
        else:
            key = create_ticket(issue, result)
            print(f"   ticket {key}: https://{JIRA_SITE}/browse/{key}")
            print(f"   sentry: https://{ORG}.sentry.io/issues/{issue['id']}/")
            if has_pr:
                pr = open_pr(wt, key, result)
                print(f"   draft PR {pr}")
                run(["acli", "jira", "workitem", "comment", "create", "--key", key, "--body", f"Draft fix: {pr}"])
        subprocess.run(["git", "-C", REPO_DIR, "worktree", "remove", "--force", wt], capture_output=True)
    extra = len(issues) - a.limit
    if extra > 0:
        print(f"\n{extra} more issue(s) not processed, raise --limit")


if __name__ == "__main__":
    main()
