# Global Commit Rules

- When creating commits, always use Conventional Commits format.
- Required format: `type(scope): short description`.
- Keep `type` and `scope` lowercase and generic to the changed area.
- Prefer concise Spanish descriptions.
- For version bumps, use: `chore(version): bump to version X.Y.Z`.
- Do not use this format only if the user explicitly requests a different one.

## Conventional Commit Taxonomy

- Allowed `type` values:
  - `feat`: nueva funcionalidad visible para usuario.
  - `fix`: corrección de bug o regresión.
  - `perf`: mejora de rendimiento.
  - `refactor`: cambio interno sin cambio funcional visible.
  - `docs`: documentación.
  - `chore`: tareas técnicas, mantenimiento o release.

- `scope` is mandatory and should be stable and clear.
- Preferred scopes:
  - `workday`
  - `email-agent`
  - `ingress`
  - `ui`
  - `api`
  - `security`
  - `version`

- User-impacting changes must use `feat` or `fix` (not `chore`).
- Avoid mixing unrelated topics in one commit.

## Changelog/Release Guidance

- Keep commit messages short and actionable so automated changelog generation is clear.
- Recommended release cut commit: `chore(version): bump to version X.Y.Z`.
- Suggested changelog grouping (if automation is used): `feat`, `fix`, `perf`, `docs`, `chore`.

## Examples

- `feat(paquetes-router): añade resolución por alias en comandos de voz`
- `fix(storage): corrige borrado por tracking normalizado`
- `docs(addon): documenta opciones y uso básico`
- `chore(ci): actualiza flujo de publicación`
- `chore(version): bump to version 0.3.2`

## Local Environment Defaults

- Home Assistant base URL (default for all repos): `http://192.168.178.35:8123`
- Home Assistant host: `192.168.178.35`
- Home Assistant port: `8123`

## Non-Generic Name Guard (Global)

- Applies to all repositories.
- Before running any `git push`, Codex must run a non-generic/proper-name validation against commits that are about to be pushed.
- When a task includes code changes that are expected to be committed, Codex must also run the same validation once just before the commit as an early quality gate.
- Do not run the check on every edit or intermediate save; use it at the pre-commit gate and again at push time.
- Scope of validation: added lines in the outgoing commit range, including string literals, identifiers, variable names, and comments.
- Source of forbidden terms: `$HOME/.codex/rules/non_generic_terms.txt` (one term per line, case-insensitive).
- The guard must also verify that no added URL contains the protected HA cloud hostname configured in local policy (case-insensitive).
- Before any `git push`, the guard must also scan the repository for URLs containing `duckdns` or `duckdns.org` (case-insensitive) and report any match for explicit confirmation before proceeding.
- If a match is found:
  - block the push,
  - report matched term(s) and file(s),
  - ask for explicit user confirmation before any bypass.
- If no forbidden term is found, proceed with push normally.

## Change Quality Gate (Global)

- Applies to all repositories when the user asks for code changes.
- Codex should refer to this pre-commit step explicitly as the `Change Quality Gate`, in the same way it refers to the `Non-Generic Name Guard`.
- After the relevant non-generic name validation has passed and immediately before creating a commit, Codex must perform a short quality gate on the changes.
- If the `Change Quality Gate` results in additional code changes, Codex must run the `Non-Generic Name Guard` again before creating the commit.
- The quality gate must include a mini code audit to check for obvious regressions, integration issues, or functionality breaks introduced by the changes.
- The quality gate must include a smoke test that covers the most basic critical path affected by the change.
- If the changes are large, cross-cutting, risky, or touch multiple subsystems, Codex must ask the user whether to run a full code audit and a broader end-to-end smoke test before committing.
- Codex should add new tests when they are needed to cover the new behavior or prevent regressions, and then run the relevant tests to verify the change.
- Codex should add or update code comments when needed to explain new functionality, non-obvious behavior, or meaningful changes to existing logic.
- For Home Assistant Addons or Home Assistant Apps, Codex should add logs when needed to make behavior observable and to surface useful warnings, alerts, or errors during operation.

## Workspace And Thread Policy

### Goal

- Use one workspace per stable workstream, not one workspace per micro-task.
- Use threads inside a workspace for related work that shares context.
- Keep `global` as the coordination workspace and default landing zone for new GPT migrations.

### Recommended Workspaces

- `global`
- `workday`
- `issue`
- `answers`
- `mail` or `email`
- Optional: `ha-deploy` for Home Assistant / Supervisor / ingress / packaging work outside normal agent logic.

### Workspace Naming

- Worktree or workspace names should include a clear role token that can be inferred from the current path or workspace label.
- Preferred tokens:
  - `global`
  - `workday`
  - `issue`
  - `answers`
  - `mail`
  - `email`
  - `ha-deploy`
- If no role token is visible, Codex should treat the workspace as `global` until clarified.

### When To Suggest A New Thread

- If the user starts a clearly new task that is unrelated to the current thread's ongoing objective, Codex should suggest opening a new thread.
- If the task is sustained, agent-specific, or likely to require more than one commit, Codex should suggest doing it in the matching agent workspace before editing.
- If the task is cross-cutting, release-related, migration-related, or affects shared shell/common infrastructure, it can stay in `global`.
- Small clarifications, quick inspections, and one-off questions do not require a new thread.

### When To Suggest A New Worktree

- Suggest a new worktree when the user is starting a long-lived line of work for one agent that should not mix with current changes.
- Suggest a new worktree when parallel work across agents is expected.
- Suggest a new worktree when the change is likely to touch different ownership areas and would benefit from a separate branch/history.
- Do not suggest a new worktree for every small bug or tiny follow-up inside an already active agent workspace.

### Inicio De Tareas En Worktrees

- Antes de empezar una tarea en un worktree/rama específica de agente, actualizarlo contra `origin/main` siempre que sea seguro.
- Flujo preferido en worktrees de agente:
  1. Revisar `git status --short --branch`.
  2. Ejecutar `git fetch origin --tags`.
  3. Ejecutar `git rebase origin/main`.
- Si el worktree tiene cambios sin commit, no hacer rebase automáticamente; revisar el estado y pedir confirmación si hay riesgo de mezclar o reescribir trabajo.
- En el worktree principal/canónico que tenga `main`, usar `git fetch origin --tags` y `git pull --ff-only origin main` en lugar de rebase.
- Si la rama del worktree ya tiene commits compartidos o publicados y el rebase puede reescribir historia ajena, pedir confirmación antes de continuar.

### Subida A Main Desde Worktrees

- Cuando el trabajo se haga en un worktree/rama específica de agente, no es obligatorio abrir PR si el remoto permite push directo a `main`.
- Flujo preferido para subir sin PR:
  1. Terminar cambios en el worktree del agente.
  2. Ejecutar tests relevantes.
  3. Ejecutar `Non-Generic Name Guard`.
  4. Ejecutar `Change Quality Gate`.
  5. Crear commit convencional en la rama del worktree.
  6. Ir al worktree principal/canónico que tenga `main`.
  7. Actualizar `main` con `git fetch origin --tags` y `git pull --ff-only origin main`.
  8. Integrar la rama del worktree con `git merge --ff-only <rama-del-worktree>`.
  9. Ejecutar de nuevo `Non-Generic Name Guard` antes del push.
  10. Hacer `git push origin main`.
  11. Crear y subir tag de versión si aplica, por ejemplo:
      `git tag -a vX.Y.Z -m "chore(version): bump to version X.Y.Z"`
      `git push origin vX.Y.Z`
- Si `git merge --ff-only` falla, no forzar el merge automáticamente; revisar divergencia y pedir confirmación.
- Si `git push origin main` falla por protección de rama, usar PR.
- Para repositorios child de add-ons Home Assistant, antes de cualquier push verificar que existe `.github/workflows/notify-parent-add-on-repo.yml`.

### Global Workspace Behavior

- The `global` workspace is the default coordinator.
- It may handle:
  - shared UI shell,
  - `main.py`,
  - shared auth/config/runtime behavior,
  - release/version work,
  - cross-agent changes,
  - Home Assistant compatibility audits,
  - migrations and persistence policy,
  - docs that affect the whole repo.
- If a task becomes clearly owned by one agent and is expected to continue beyond a small patch, `global` should suggest moving future work to that agent workspace.

### Agent Workspace Boundaries

- `workday` workspace owns primarily:
  - `agents/workday_agent/**`
  - `routers/workday_agent.py`
  - Workday-specific tests
  - Workday-only sections of `routers/ui.py`
- `issue` workspace owns primarily:
  - `agents/issue_agent/**`
  - `routers/issue_agent.py`
  - Issue-specific tests
  - Issue-only sections of `routers/ui.py`
  - Issue-specific snapshots used to extract or verify Agent Runner Docker state must live under `./config/issues_snapshots` inside the Home Assistant volume.
- `answers` workspace owns primarily:
  - `agents/answers_agent/**`
  - `routers/answers_agent.py`
  - Answers-specific tests
  - Answers-only sections of `routers/ui.py`
- `mail` / `email` workspace owns primarily:
  - `agents/email_agent/**`
  - `routers/email_agent.py`
  - Email-specific tests
  - Email-only sections of `routers/ui.py`
- `ha-deploy` workspace owns primarily:
  - Home Assistant / Supervisor integration notes
  - packaging, ingress, networking, mounts, wrapper repos, deployment docs

### Shared File Editing Rules

- Agent workspaces must avoid editing files primarily owned by another agent workspace unless the user explicitly asks for a cross-agent change.
- Shared files such as `main.py`, `routers/ui.py`, shared docs, and shared config may be edited from an agent workspace only when:
  - the change is minimal,
  - the change is strictly required for that agent task,
  - the touched area is clearly limited to that agent's scope,
  - and the edit does not silently change another agent's behavior.
- If a shared-file change is broad, structural, or likely to affect multiple agents, Codex should stop and suggest moving the work to `global`.

### Files That Need Extra Care

- Before editing `main.py`, confirm whether the change is global or agent-scoped.
- Before editing `routers/ui.py`, confirm whether the change is:
  - shell/global,
  - or strictly limited to one tab/agent section.
- Before editing tests outside the current agent's test area, confirm that the change is genuinely cross-cutting.

### Default Suggestion Rules For Codex

- If current workspace is `global` and the user asks for a new agent-specific feature/fix:
  - suggest the corresponding agent thread/workspace before making large edits.
- If current workspace is agent-specific and the user asks for unrelated work in another agent:
  - suggest switching to the correct workspace/thread before editing.
- If the user explicitly wants the change done in the current workspace anyway:
  - proceed, but acknowledge that the work is crossing the usual boundary.

### Must Not Do

- Do not casually edit code owned by another agent workspace just because the file is accessible.
- Do not use `global` as an excuse to accumulate unrelated work in one thread.
- Do not create one workspace per tiny task.
- Do not revert another workspace's changes unless the user explicitly asks.
