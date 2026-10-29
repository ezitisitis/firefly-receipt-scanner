# Contributing

Contributions are welcome! Open an issue to discuss larger changes, then send a
pull request against `main`.

## Branch naming

The repository has a **Branch naming** ruleset that applies to every branch
except the ones matching the patterns below. If you create a branch whose name
doesn't match one of them, the push is rejected, so pick a prefix that
describes the change:

| Prefix          | Use it for                                                  | Example                          |
| --------------- | ----------------------------------------------------------- | -------------------------------- |
| `feature/`      | New functionality or user-visible improvements              | `feature/receipt-attachments`    |
| `fix/`          | Bug fixes                                                   | `fix/timezone-in-receipt-date`   |
| `chore/`        | Maintenance: dependencies, CI, refactoring, tooling         | `chore/bump-python-3.13`         |
| `docs/`         | Documentation-only changes                                  | `docs/branch-naming`             |
| `dependabot/`   | Reserved for Dependabot's automatic update branches         | `dependabot/uv/openai-1.60.0`    |

`main` is the default branch and is also excluded; changes reach it through
pull requests.

### Rules of thumb

- Use lowercase words separated by hyphens after the prefix:
  `feature/budget-suggestions`, not `Feature/BudgetSuggestions`.
- Keep it short and descriptive. Referencing an issue is welcome:
  `fix/42-empty-category-list`.
- The patterns use `**`, so deeper paths are allowed too
  (`feature/ui/dark-mode`), but a single level is usually enough.
- Don't create `dependabot/` branches by hand.

### Names that are rejected

Anything without one of the prefixes above, for example:

- `7-feature-request-add-scanned-document-as-attachment` (no prefix; use
  `feature/7-scanned-document-attachment`)
- `hotfix/endpoint_changes` (`hotfix/` isn't an allowed prefix; use
  `fix/endpoint-changes`)
- `claude/practical-maxwell-vswklf` (tool-generated names; rename to e.g.
  `chore/...` or `feature/...` before pushing)

### Renaming a branch

If you already created a branch with a non-matching name locally:

```bash
git branch -m old-name feature/new-name
git push -u origin feature/new-name
```
