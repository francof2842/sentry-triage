# Sentry Triage

Turns production errors reported to Sentry into Jira tickets and draft fixes for the team that owns the code.

## Language

**Sentry Issue**:
A group of events Sentry treats as the same error. One Sentry Issue maps to at most one Ticket.
_Avoid_: error, bug, event

**Production**:
Sentry events whose environment is `production`. Staging, demo and dev events are ignored.
_Avoid_: prod traffic

**Support Ticket**:
A request raised by someone in the support Jira project. It stays where it is and is never reassigned or closed by the tool. A Support Ticket assigned to the Claude bot is a second way work enters the tool, alongside a Sentry Issue.
_Avoid_: ticket (unqualified)

**Ticket**:
The engineering Jira work item the tool creates for a Sentry Issue or a Support Ticket so one person owns the fix.
_Avoid_: alert, bug report

**Draft Fix**:
A draft pull request proposing a change for a Ticket. It is a starting point for the owner, never merged automatically. It exists only when analysis finds a change worth proposing.
_Avoid_: auto-fix, patch

**Alert**:
A Slack message announcing a new Ticket. Deferred for now, see flagged ambiguities.

**On-call**:
The person responsible for responding to a Ticket right now, from PagerDuty. Deferred, nothing pings anyone yet.

## Relationships

- A **Sentry Issue** in **Production** produces one **Ticket**
- A **Support Ticket** assigned to the Claude bot produces one **Ticket** and links back to it
- A **Ticket** may have one **Draft Fix**
- An **Alert** announces a **Ticket** and may mention **On-call**

## Flagged ambiguities

- "Alert" was used for "something created for every production error". It is resolved as the Slack message about a Ticket, not the Ticket itself, and is out of scope until after tickets and Draft Fixes work.
