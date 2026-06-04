# Definition of Done — All Agents

A task is only **DONE** when ALL of the following criteria are met.

---

## Universal Criteria (All Agents)

Every agent's work must satisfy:

- [ ] **Code compiles/runs** — no syntax errors, no import errors
- [ ] **No breaking changes** — existing routes, pages, and features still work
- [ ] **Tests pass** — no new failing tests, no regressions in existing tests
- [ ] **No forbidden actions** — nothing from `forbidden-actions.md` was done
- [ ] **File ownership respected** — no agent modified another agent's files
- [ ] **User notified** — the user knows what was done and what changed

---

## TDD Agent — Definition of Done

- [ ] Tests written BEFORE implementation (not after)
- [ ] Test describes expected **behavior**, not implementation detail
- [ ] Tests are runnable with `python -m pytest tests/`
- [ ] All tests pass (or failures documented with root cause)
- [ ] Test covers the stated requirement completely
- [ ] No regression in existing test suite

---

## Backend Agent — Definition of Done

- [ ] Routes preserved — no breaking changes to existing URLs
- [ ] All SQL uses parameterized `%s` queries (no string concatenation)
- [ ] New routes return correct data shape for templates
- [ ] Error handling — graceful degradation with flash messages on failure
- [ ] Input validation on `from_date`, `to_date`, `site` parameters
- [ ] `requirements.txt` updated if new dependencies added
- [ ] `shared-rules.md` followed (file ownership, code style, error handling)
- [ ] Documentation — if a DB schema change is needed, it's clearly documented

---

## UI Agent — Definition of Done

- [ ] `templates/base.html` read completely before any changes
- [ ] All new charts registered to `chartInstances` with click-to-modal handler
- [ ] Theme-aware colors used (`tc()` and `gc()` helpers)
- [ ] No duplicate CDN includes (Chart.js, Font Awesome, Google Fonts in base.html only)
- [ ] Mobile responsive — CSS media query added
- [ ] No `window.addEventListener("resize", ...)` added to page templates
- [ ] No `window.xxxChart = xxx` global chart assignments added
- [ ] Popup modal works on all charts
- [ ] Dark/light theme toggle works on all new elements
- [ ] `shared-rules.md` followed (CSS rules, JS rules, error handling)

---

## Perf Agent — Definition of Done

- [ ] Chart.js decimation added to all `makeOpts()` functions (threshold ≥ 500)
- [ ] Cache-Control headers added to route responses
- [ ] No breaking changes to existing routes or features
- [ ] `requirements.txt` updated if new dependencies added
- [ ] Performance improvement is measurable/documented:
    - e.g., "reduced chart points from 720 to 200 via LTTB decimation"
- [ ] New caching does not serve stale data to users
- [ ] `shared-rules.md` followed (no breaking changes)

---

## Security Agent — Definition of Done

- [ ] All SQL queries parameterized (`%s` placeholders)
- [ ] CSRF tokens on ALL POST/PUT/DELETE forms
- [ ] CSRF tokens verified server-side before processing
- [ ] Session cookies have `HttpOnly`, `Secure`, `SameSite` flags set
- [ ] Secret key from env var — no weak fallback
- [ ] Input validation on all user-provided parameters
- [ ] Custom error handlers for 404 and 500 (no stack traces exposed)
- [ ] Bruteforce protection on login (≥ 5 attempts → lockout)
- [ ] No `| safe` filter on user-controlled content
- [ ] Security checklist completed and reported

---

## Architect Agent — Definition of Done

- [ ] File ownership map declared BEFORE agents spawn
- [ ] No two agents write to the same file simultaneously
- [ ] All agents' outputs validated against their Definition of Done
- [ ] Conflicts resolved — no overwritten changes
- [ ] User receives a complete summary report of all changes
- [ ] `shared-rules.md` and `forbidden-actions.md` referenced in all agent prompts

---

## Quick Checklist for Every Task

```
Before starting:
  [ ] Read .agent.md, shared-rules.md, forbidden-actions.md
  [ ] Declare file ownership
  [ ] Check: does this task need multiple agents?

During work:
  [ ] No forbidden actions taken
  [ ] File ownership respected
  [ ] Error handling in place
  [ ] Code style matches shared-rules.md

After completing:
  [ ] All universal criteria met
  [ ] Task-specific criteria met
  [ ] User notified with summary
```

---

*Last updated: 2025-05-17*