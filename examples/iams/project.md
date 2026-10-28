# Project rules for the feature pipeline — IAMS

Every pipeline agent reads this file first.

## Context
IAMS: multi-tenant insurance agency management system for North Cyprus agencies. .NET 8+, Clean Architecture, EF Core, bounded contexts, one database per tenant (agency). Holds customer personal data and policy data.

## Skills to load
- `agencies-architecture`
- `project-memory`
(Use the names exactly as `/skills` shows them; plugin skills may carry a prefix.)

## Decision / failure logs
`.claude/MEMORY.md` (decisions) and `.claude/ERRORS.md` (dead ends). Planner reads both before proposing an approach.

## Architecture rules
- Dependency direction: Domain → nothing; Application → Domain + abstractions; Infrastructure → Application/Domain; API → Application.
- EF Core types (DbContext, entities' persistence config, IQueryable) never leave Infrastructure. API contracts are DTOs, never entities.
- Tenant data is reached only through the existing tenant resolution path (tenant resolver / DbContext factory). No static or singleton state holding tenant data. Cache keys include the tenant id.
- Background jobs iterate tenants explicitly; nothing runs "without a tenant" by accident.

## Data & migrations
- Generate: `dotnet ef migrations add <Name>` with the repo's usual `-p`/`-s` flags.
- Never run `dotnet ef database ...` (banned by the guard). Migrations are applied per tenant by the migration runner, not by agents.
- Every migration must be safe for every existing tenant DB: defaults or backfill for existing rows, no destructive changes without a spec-level decision.

## Required spec sections
- `### Tenant impact`: which resolution path is used, any cross-tenant risk and how it is closed, and the line `Isolation test required: yes/no`.

## Test rules
- Tests live under `tests/unit/` and `tests/integration/`.
- When the spec says `Isolation test required: yes`: write a test proving tenant A's data and operations cannot reach tenant B.
- Never use configured tenant connection strings; use the existing test fixtures only. If no fixture can create two tenant databases, report it as a gap in tests.md.

## Review checklist (project-specific)
- DbContext obtained only via the tenant resolver; no singleton/static tenant state; cache keys include tenant id.
- Background jobs/report generators iterate tenants explicitly.
- Migration safe for existing tenant DBs (defaults/backfill).
- No PII in logs or exception messages: customer names, ID numbers, policy numbers, phone numbers, vehicle plates.
- Authorisation on every new endpoint/handler, scoped to the caller's agency.
