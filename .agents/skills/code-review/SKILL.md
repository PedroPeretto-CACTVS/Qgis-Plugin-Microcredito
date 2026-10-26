---
name: code-review
description: Review a repository change after implementation and before handoff. Trigger for pull requests, branches, working-tree changes, or the mandatory final review required by this repository. Check both documented standards and the requested behavior, including uncommitted changes.
---

# Code Review

Review the complete task diff on two independent axes:

- **Standards:** compliance with the applicable `AGENTS.md`, repository conventions, architecture, safety rules, and quality gates.
- **Spec:** fidelity to the user's request, acceptance criteria, issue, or specification that originated the change.

Do not rubber-stamp. A passing test suite is evidence, not proof that the behavior is correct.

## Establish the review scope

Preserve unrelated user work. Start by recording `git status --short`, the current branch, and the candidate fixed point.

Use the fixed point supplied by the user. If none was supplied, choose the merge-base with the tracked integration branch (`main` or its upstream) and state that choice. Review committed, staged, and unstaged task changes; do not rely only on `git diff <base>...HEAD`, because that omits working-tree edits.

Capture:

- `git diff <fixed-point>` for the complete working-tree diff;
- `git diff --cached <fixed-point>` when staged content needs separate inspection;
- `git log <fixed-point>..HEAD --oneline` for committed task history;
- the list of changed files and applicable instruction files.

Stop if the fixed point cannot be resolved or the intended task diff cannot be distinguished from unrelated changes.

## Determine standards and spec

Read all `AGENTS.md` files that apply to changed paths, then relevant repository sources such as `CONTRIBUTING.md`, `pyproject.toml`, test configuration, architecture decisions, or documented compatibility rules.

Use the first available specification source:

1. the user's request and acceptance criteria in the active task;
2. an explicitly supplied issue, PR, or spec path;
3. issue references in task commits;
4. a matching file under `docs/`, `specs/`, or `.scratch/`.

If no behavioral specification exists, report that limitation instead of inventing requirements.

## Review independently

When sub-agents are available and authorized, run the Standards and Spec reviews in parallel so their conclusions remain independent. Give both reviewers the same fixed point, diff commands, changed-file list, and task scope. Give the Standards reviewer the standards sources; give the Spec reviewer the specification source.

Each reviewer must inspect concrete code and report only actionable findings. Check especially:

- correctness, regressions, data loss, security, privacy, error handling, and cleanup;
- compatibility with supported QGIS/Python/runtime versions;
- missing tests or tests that cannot fail when behavior is wrong;
- implementation-coupled or tautological tests;
- scope creep and behavior requested but not implemented;
- duplication, misleading names, excessive coupling, and speculative abstractions when they materially increase risk.

Tooling-enforced formatting is not a review finding unless the tool actually fails.

## Findings format

List findings before any summary, ordered by severity:

- **P0:** immediate data loss, security incident, or unusable release;
- **P1:** likely functional failure or major regression;
- **P2:** real defect with limited impact or important missing coverage;
- **P3:** low-risk maintainability problem worth fixing in this change.

Every finding must include the affected file and tight line range, the observed behavior, why it violates the standard or spec, and the smallest credible correction. Do not report speculation without a reproducible path or code evidence.

Keep the axes separate under `## Standards` and `## Spec`. If an axis has no actionable findings, say so explicitly and mention any residual test limitation.

When this skill is the repository's mandatory self-review, return in-scope findings to the implementation loop. Fix them through `$tdd`, rerun relevant quality gates, and review the resulting diff again before handoff.
