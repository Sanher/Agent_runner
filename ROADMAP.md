# Agent Runner living roadmap

> **Status:** living document. It records the agreed direction, the safety boundaries, and the next decision gates; it is not a promise that every future phase will be implemented unchanged.
>
> **Current implementation focus:** phases 1–3 only. Later phases are deliberately described as gated options, not approved implementation work.

## Product direction

Agent Runner is evolving from a set of operational assistants into a supervised engineering-intake system. It should be able to collect authorised conversation context, prepare high-quality work items, later enrich those work items with approved repository context, and eventually propose small fixes and draft pull requests.

The system must remain **supervised by default**. Reading, drafting, mutation of external systems, source-code access, branch creation, and pull-request creation are separate capabilities with separate permissions and approval gates.

## Standalone intake console

The conversation-intake product has its own small HTML application, separate from the current Home Assistant ingress UI. It began as a Discord-focused local console and is now the source-aware review console for the additional intake sources and draft checks introduced in later phases.

- It is served only by the dedicated local runner, bound to loopback by default, and protected with its own local `JOB_SECRET`.
- It must not import, embed, proxy, or depend on the current multi-agent ingress UI.
- It initially shows Discord baseline state, summaries, suggested tasks, evidence IDs, dismiss/restore, and the existing Issues prefill action.
- Phase 2 adds source-aware Telegram review to the same console without merging the two sources silently. Live Telegram delivery remains in Agent Runner through the shared Answers webhook; the local console must never become a second webhook consumer.
- Phase 3 adds the deterministic issue-quality checklist and explicit human override control.
- It remains a review surface: it does not send Discord or Telegram messages, create an issue, or create a PR merely through rendering a task.

## Isolated pilot environments

Every phase must be proven in an isolated environment before it can be considered for company data or repositories:

| Surface | Pilot environment | Explicitly excluded until a later approval |
| --- | --- | --- |
| Discord | A personal Discord test server and explicitly selected test channel(s) | Production/community servers and historical messages |
| Telegram | An explicitly allowed private test chat delivered by the existing Answers webhook, with the reader independently enabled | Unlisted chats, groups/channels until separately reviewed, and direct live delivery to the local console |
| GitHub | A personal GitHub test account and a repository containing invented code/data | Company organisations, company repositories, secrets, CI, and production branches |

Pilot data must be deliberately invented or non-sensitive. A successful pilot validates the mechanism and safety boundaries; it does not authorise moving to company data.

## Non-negotiable operating principles

1. **Least privilege and explicit allow-lists.** Every chat, repository, and external action must be explicitly configured.
2. **Read before write.** New integrations begin read-only. A write capability is introduced only in a later phase with a distinct permission and audit trail.
3. **Privacy-first collection.** A new chat starts from its activation point and does not retrospectively analyse historical messages. Data sent to an AI provider is minimised, redacted where needed, and retained for a defined period only.
4. **Human approval for material actions.** A suggested task, issue, code patch, branch, or pull request is never created merely because an AI proposed it.
5. **Provenance and reversibility.** Every suggestion must identify its evidence and source. Local review decisions, including duplicates and dismissals, must be reversible and auditable.
6. **Separated deployment surfaces.** Local development must not read or modify Home Assistant runtime data. The child application remains the source code; the add-on parent remains the published Home Assistant artifact.
7. **Safe failure.** Missing configuration, unreadable content, unknown scopes, duplicate uncertainty, or unavailable policy must stop at review rather than guess or write.

## Phase map

| Phase | Status | Outcome | External write authority |
| --- | --- | --- | --- |
| 1. Local Discord lab | In progress | A dedicated local-only intake runner and Discord review surface; real pilot pending | None |
| 2. Telegram intake | In progress | A separate read-only Telegram source fed by the shared Answers webhook, with local review support | None |
| 3. Issue authoring guidelines | Planned | A versioned, deterministic quality gate for issue drafts | Existing manual Playwright action only |
| 4. GitHub App API migration | Deferred | Replace the GitHub-specific Playwright mutation path with official API operations | Read-only first; issue writes later and explicitly approved |
| 5. Approved code context | Deferred | Attach minimal, authorised code evidence to a task or draft | None initially |
| 6. Supervised remediation and duplicate handling | Deferred | Propose small patches and identify likely duplicates | Local patch/worktree only |
| 7. Draft pull requests | Deferred | Create reviewable PRs for approved small changes | Draft PR only, never direct-to-main |
| 8. Organisation-wide supervised autonomy | Deferred | Policy-controlled multi-repository operation with audit and escalation | Per-action approval policy |

No phase is considered permanently closed. A phase can be revisited when the product model, company policy, providers, or repository conventions change.

---

## Phase 1 — Local Discord lab

### Goal

Provide a small local application that runs the read-only Discord intake and its standalone review HTML/API, without deploying to Home Assistant or starting unrelated agents. The same isolated shell can show an unavailable future source without importing its unrelated application services.

### Proposed design

- Add a dedicated local entry point that composes `DiscordAgentService` and its authenticated router, rather than importing the full `main.py` application.
- Bind to loopback by default (`127.0.0.1`), use a local data directory, and require an explicit opt-in before any real Discord or AI request.
- Reuse the existing Discord service, privacy-first baseline, local summary persistence, task dismissal, and Issues prefill contract. Do not fork its business logic.
- Serve a small standalone intake HTML review panel from the local app; do not import the current multi-agent ingress UI merely to test one agent.
- Start with manual polling only. If a local scheduler is introduced later, it needs a controlled lifecycle, a single worker, and an instance/data-directory lock so two local runners cannot duplicate polling or AI calls.
- Add an `.env.example` with placeholders only. The real `.env` stays ignored and is never copied to add-on configuration or committed.

### Local configuration contract

The canonical Discord variables remain unchanged so a local test resembles the eventual add-on configuration:

| Variable | Purpose | Local default / rule |
| --- | --- | --- |
| `DISCORD_ENABLED` | Explicit opt-in for real Discord polling | `false` |
| `DISCORD_BOT_TOKEN` | Discord bot credential | Required only when enabled; never logged |
| `DISCORD_OPENAI_API_KEY` | AI-provider credential for summaries | Required only when enabled; never logged |
| `DISCORD_OPENAI_MODEL` | Summary model | Existing default remains valid |
| `DISCORD_CHANNEL_IDS` | Comma-separated allow-list | Required only when enabled |
| `DISCORD_POLL_INTERVAL_MINUTES` | Scheduler interval | Existing default remains valid |
| `DISCORD_SUMMARY_MIN_MESSAGES` | Minimum message count before a summary | Existing range remains valid |
| `DISCORD_RETENTION_DAYS` | Local summary retention | Existing default remains valid |
| `INTAKE_LOCAL_DATA_DIR` | Isolated local persistence root | `./.data/intake_local` |
| `INTAKE_LOCAL_HOST` / `INTAKE_LOCAL_PORT` | Loopback listener | `127.0.0.1` / a non-published development port |
| `JOB_SECRET` | Direct local API/UI protection | Required for any exposed local UI/API |

`INTAKE_LOCAL_*` variables are development-only. They must not become Home Assistant add-on options unless a separate deployment decision approves that expansion.

### Deliverables

1. A dedicated local runner, launch command, and `.env.example`.
2. A local-only data root with no dependency on `/data/options.json` or Home Assistant runtime files.
3. Mock fixtures for Discord and the AI provider, including first-baseline, unreadable-message, pagination, multiple-task, and dismissal scenarios.
4. A short operator guide: create `.env`, start locally, verify loopback binding, select test channel IDs, and stop the runner.
5. Logs that identify configuration state and channel IDs but never tokens or message content.

### Acceptance criteria

- Starting locally with no `.env` or `DISCORD_ENABLED=false` makes no network request.
- The local runner never imports or starts the email, Workday, Answers, or Issue automation loops.
- The initial runner performs no automatic polling; any later scheduler must reject or otherwise prevent a second runner using the same data directory from polling concurrently.
- A mocked session covers the same privacy boundary and read-only guarantees as the add-on service.
- A real local session can only read explicitly allowed channels and cannot write to Discord.
- The first real pilot uses only the personal Discord test server and channel IDs declared in the local `.env`; it starts from the activation boundary and does not analyse older test messages.
- Local persistence is separated from Home Assistant and can be removed without affecting runtime data.

### Decision gate to enter phase 2

Approve the local-runner interface, data directory, secret handling, and proof that real test traffic is isolated from Home Assistant.

---

## Phase 2 — Read-only Telegram intake

### Goal

Add Telegram as a second authorised conversation source that produces the same reviewable task candidates as Discord, without sending messages or creating issues. It reuses the existing Answers Business bot through a single authenticated webhook delivery path, while keeping the reader independently enabled and unable to use Answers' outbound operations. Telegram reuses the existing Discord OpenAI credential and model rather than introducing a duplicate AI secret.

### Important constraints

- The repository already contains an Answers agent with the Telegram bot token and an authenticated webhook. That is the only external Telegram delivery owner. The reader must never configure a second webhook, call `getUpdates`, or receive the bot token as its own configuration.
- Telegram's webhook and long-polling delivery modes are mutually exclusive for a bot. The approved design is a single webhook followed by an internal fan-out, not two independent Telegram consumers. [Telegram Bot API](https://core.telegram.org/bots/api#getting-updates)
- The reader only accepts incoming text messages for its explicit chat allow-list. It excludes bot-originated messages, edits, attachments, and unsupported update types until a separate review approves them.
- A reader or OpenAI failure must be isolated from Answers: it must not change the webhook response, resend a Telegram reply, or cause delivery retries for an otherwise successfully handled Answers update.

### Proposed design

- Introduce a dedicated `telegram_reader` rather than extending the conversational Answers agent.
- Keep one authenticated Answers webhook. After its authentication and normal Answers handling, pass an internal copy of each eligible update to the reader; do not share the Answers service object or its outbound methods with the reader.
- Require an explicit chat allow-list and an activation boundary per chat. Do not convert messages that predate activation into retrospective historical analysis.
- Normalise Telegram messages into a source-neutral intake record: source, chat ID, message ID, timestamp, anonymised author reference, text, and evidence IDs.
- Reuse the current task-review concepts: multiple independent candidates, `bug`/`task` classification, local dismiss/restore, no automatic issue creation, and explicit provenance.
- Do not call Telegram methods from the intake service. The reader is an internal webhook fan-out consumer and review source only.
- The standalone console remains a Discord local-polling tool plus a Telegram review surface for fixtures or explicitly supplied review data. It does not receive the shared Business webhook. A future live-local Telegram pilot requires a dedicated test bot and a separately approved transport.

### Proposed configuration namespace

Names below are the child configuration contract and must be mirrored by the parent add-on before Home Assistant deployment:

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_READER_ENABLED` | Explicit opt-in; default `false` |
| `DISCORD_OPENAI_API_KEY` / `DISCORD_OPENAI_MODEL` | Shared AI-provider credential and model; no Telegram-specific duplicate secret |
| `TELEGRAM_READER_CHAT_IDS` | Explicit allowed chat IDs |
| `TELEGRAM_READER_SUMMARY_MIN_MESSAGES` | Threshold before summarisation |
| `TELEGRAM_READER_RETENTION_DAYS` | Retention policy |

`ANSWERS_TELEGRAM_BOT_TOKEN` and `ANSWERS_WEBHOOK_SECRET` remain Answers-only configuration: they provide the single bot identity and authenticated external delivery path. The reader persists under its own data subdirectory and has no Telegram transport credential.

### Deliverables

1. A source-neutral intake/task schema shared by Discord and Telegram where practical.
2. An authenticated webhook fan-out with chat allow-list, activation boundary, update/message idempotency, and isolated error handling.
3. Dedicated tests for inbound and unsupported updates, bot-originated and edited messages, duplicate delivery, first-start boundary, task suggestion review, and Answers isolation.
4. Extend the standalone intake console with source-aware Telegram review, clearly separating Telegram from Discord provenance without exposing raw chat content outside authorised review. Its Telegram poll and baseline controls stay unavailable.
5. Documentation explaining the shared webhook topology, chat allow-list, activation boundary, local-console limitation, and read-only guarantee.

### Acceptance criteria

- The reader receives no bot credential; the one Telegram token remains configured under Answers.
- The service receives and processes only allowed incoming update types and allowed chats through the authenticated webhook fan-out.
- No Telegram API method is used by the intake path.
- The initial activation does not create a retrospective summary; subsequent authorised messages can produce multiple reviewable candidates.
- Duplicate delivery or restart does not duplicate a summary, a task, or a future issue candidate.
- Answers remains operational if the reader or its AI processing fails.
- The real pilot is restricted to the designated private test chat; group/channel support is not enabled until that pilot and its privacy review pass.

### Decision gate to enter phase 3

Approve the shared webhook topology, the data-retention policy, and the shared candidate schema after mocked webhook and real test-chat validation.

---

## Phase 3 — Issue authoring guidelines and deterministic review

### Goal

Make issue quality a versioned product contract rather than an implicit prompt or a Playwright form side effect. Conversation-derived candidates must receive the same review quality as manually entered drafts. The checklist is reviewed in the standalone intake console before any manual submission flow.

### Current gap

The existing Issue agent has templates, OpenAI drafting, warnings, and an explicitly manual Playwright submission flow, but it does not yet have a versioned issue-authoring guide or a deterministic completeness review shared across all input sources.

### Deliverables

1. Add canonical English guidance under `agents/issue_agent/guidelines/`: a base rule set, optional repository/type additions, and `issue_authoring.md` as the operator-facing contract.
2. Define a source-neutral draft schema and a deterministic `draft_review` result that is backward compatible with existing `draft_warnings`.
3. Add a visible checklist in the Issue UI before the existing manual Playwright action.
4. Record a human override reason when a draft with unmet blocking criteria is intentionally continued.
5. Document the flow: intake candidate → prefilled draft → quality review → human edit/override → existing manual submission.

### Minimum authoring rules

| Type | Required review content |
| --- | --- |
| Bug | Affected area, actual result, expected result, reproduction steps or an explicit statement that reproduction is unavailable, environment/evidence, and impact when known |
| Task | Desired outcome, scope and non-scope, dependencies, and verifiable acceptance criteria |
| Feature | User/business value, measurable outcome when known, scope, risks/dependencies, and verifiable acceptance criteria |

The guide must also require:

- facts and evidence only; missing information is flagged rather than invented;
- source and privacy handling for Discord/Telegram evidence;
- repository, unit, type, confidence, and duplicate-review state where available;
- a separation between blocking gaps and advisory improvements;
- preservation of current special Issue flows rather than forcing unrelated requirements into them.

Guideline precedence must be fixed and testable: security/schema rules → repository/type template → versioned guideline → `ISSUE_OPENAI_STYLE_LAW` → memory examples → imported conversation context. The last two are untrusted data, never instructions. Store the applicable guideline version/hash with each draft and review event.

### Acceptance criteria

- Complete and incomplete examples for bug, task, and feature produce deterministic, testable review items.
- A missing critical criterion changes the draft state to `needs_review`; proceeding requires an explicit human confirmation and reason.
- The review does not create an issue, mutate Discord/Telegram, or bypass the existing manual submit action.
- Current templates, special flows, warnings, and Playwright tests remain compatible.
- Discord and Telegram transfers only prefill a draft; they never create or submit an issue automatically.
- Pilot examples use invented Discord/Telegram messages and invented issue content; no company repository or issue is needed for phase 3.

### Decision gate to enter phase 4

Approve the canonical draft schema, blocking/override policy, and audit record format. This is the contract that the GitHub API migration will consume.

---

## Phase 4 — GitHub App API migration (deferred)

### Goal

Replace the GitHub-specific browser mutation path with official API operations where the required fields and project metadata are supported, while preserving human review and the Issue draft contract from phase 3.

The entire initial API pilot runs only against the personal GitHub test account and a repository containing invented code. It must not install the app in a company organisation or request access to a company repository.

### Required approach

1. Register and install a GitHub App on an explicit repository allow-list.
2. Use a dedicated GitHub App; never reuse the App/token that notifies the add-on parent repository about child tags.
3. Start with read-only repository/issue access to validate identity, repository scope, templates, labels, and duplicate lookup.
4. Use short-lived installation access tokens constrained to selected repositories and permissions. Do not use personal access tokens as the automation identity. GitHub Apps can be scoped by repository and permission, and installation tokens expire. [GitHub App authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
5. Introduce `issues: write` only after the read-only pilot and an explicit approval policy. GitHub's official issue endpoints support creating and managing repository issues. [GitHub REST issue endpoints](https://docs.github.com/en/rest/issues)
6. Derive repository and action only from an approved allow-list, never from a client-provided target URL or prompt text.
7. Keep Playwright as a temporary fallback only for fields that cannot yet be handled safely by the approved API contract; do not silently switch action paths.

### Exit criteria

- Read-only calls are audited, repository-scoped, and do not reveal unrelated repositories.
- A test organisation/repository proves issue creation, labels, parent/project metadata where applicable, idempotency, and error recovery.
- The UI clearly names the action path (API or legacy manual browser flow).
- The capability is still human-confirmed per issue until a later policy explicitly changes it.

---

## Phase 5 — Approved code context and AI-provider decision (deferred)

### Goal

Attach minimal, relevant repository evidence to reviewed candidates without granting unrestricted code access or sending source code to an unapproved provider.

### Decision required before implementation

Choose one approved architecture:

1. **Company-hosted AI:** source code and issue context remain inside the approved company boundary.
2. **GitHub MCP through an approved gateway:** the gateway exposes only repository-scoped read tools and applies authentication, logging, redaction, and policy controls.

The decision must cover data residency, retention, model/provider terms, prompt logging, secret scanning/redaction, repository scope, and operator access. Until it is approved, neither external AI nor an MCP may be given company source code.

### First capability

Read-only code retrieval limited to an approved repository/path/revision, returning citations such as file path, immutable revision, and line references. The initial capability retrieves only fixed-SHA file content through the approved API; it does not clone repositories, install dependencies, execute repository code, or create issues as a consequence of the read.

The first evaluation uses only the invented-code test repository from phase 4. Company-source access requires the separate provider/policy decision above and a new explicit approval.

---

## Phase 6 — Supervised remediation and duplicate handling (deferred)

### Goal

Use approved code context to identify likely duplicate work and propose small, reviewable local fixes.

### Boundaries

- Duplicate detection is advisory: show candidate duplicates, evidence, and confidence; never silently close, merge, or discard an issue.
- A proposed correction is created in an isolated worktree/branch with a patch, tests, and a diff for review.
- No direct write to a company repository, no secret discovery/exfiltration, no dependency upgrade, and no production change without explicit approval.
- Initially exclude workflow/CI files, deployment and Home Assistant configuration, authentication, secrets, dependencies/lockfiles, database migrations, and parent add-on files from proposed edits.
- Each proposal carries issue/source provenance and explains what evidence supports the suggested change.
- The first patch proposals target only the invented-code test repository and are local diff artifacts, not remote writes.

### Exit criteria

An operator can approve or reject the duplicate recommendation and patch independently, and the system records that decision.

---

## Phase 7 — Draft pull requests (deferred)

### Goal

For approved small fixes or tasks, create a draft pull request containing the reviewed patch, tests, issue linkage, and an AI-generated explanation for human review.

### Boundaries

- Never push directly to a protected or default branch.
- Create only a dedicated branch and a **draft** PR.
- Require separate GitHub App permissions for repository contents and pull requests; scope them to the approved repositories.
- Require successful local/CI checks, a reviewable diff, and explicit operator approval before branch push and again before marking a PR ready for review.
- The first draft PR, if phase 7 is approved, is created only in the invented-code test repository.

---

## Phase 8 — Organisation-wide supervised autonomy (deferred)

### Goal

Operate across approved company repositories with a policy engine, clear action boundaries, auditability, and human escalation.

### Required controls

- Repository/team allow-lists and action matrix: read, draft, issue write, branch push, draft PR, ready-for-review, and merge are independent permissions.
- Per-action approvals, rate limits, kill switch, audit trail, and incident response path.
- Continuous evaluations for hallucinated facts, duplicate quality, patch quality, test coverage, privacy leakage, and policy compliance.
- Regular permission review and automatic fallback to read-only mode when policy, credentials, or evidence are incomplete.

## Roadmap maintenance rules

- Update this document before beginning a new phase or changing a safety boundary.
- Record the implemented decision, owner, test evidence, and any deferred risk at each gate.
- Do not treat an unchecked roadmap item as authorisation to access a new external system, secret, repository, or production environment.
- Reassess provider, API, and MCP assumptions at the beginning of the relevant phase; external platform behaviour and company policy can change.
