# 43. Contributing

> Version: V1.0
>
> Status: Engineering Documentation
>
> Last Updated: August 2026

---

# 1. Purpose

This document defines the contribution process for CartFlow.

It establishes standards for proposing, implementing, reviewing, testing, documenting, and merging changes into the project.

---

# 2. Guiding Principles

Every contribution should be:

- Useful
- Maintainable
- Tested
- Documented
- Secure
- Consistent

Quality is always prioritized over speed.

---

# 3. Who Can Contribute

Contributors may include:

- Core Developers
- Maintainers
- Designers
- QA Engineers
- Documentation Writers
- Future Open Source Contributors

Each role has different responsibilities.

---

# 4. Types of Contributions

Examples include:

- New Features
- Bug Fixes
- Performance Improvements
- Documentation Updates
- Refactoring
- Security Fixes
- UI Improvements
- Test Improvements

---

# 5. Before You Start

Before beginning development:

- Understand the feature requirements.
- Review existing documentation.
- Check for existing issues or tasks.
- Verify the proposed change aligns with project goals.

---

# 6. Branching Strategy

Recommended branch naming:

Feature:

```
feature/product-reviews
```

Bug Fix:

```
bugfix/cart-total
```

Hotfix:

```
hotfix/payment-timeout
```

Documentation:

```
docs/api-versioning
```

Refactor:

```
refactor/order-service
```

---

# 7. Development Workflow

Typical workflow:

1. Pull latest changes.
2. Create a feature branch.
3. Implement changes.
4. Write or update tests.
5. Update documentation.
6. Self-review.
7. Submit pull request.
8. Address review comments.
9. Merge after approval.

---

# 8. Commit Standards

Commit messages should be clear and descriptive.

Examples:

```
feat: add product review system

fix: resolve duplicate checkout request

docs: update payment architecture

refactor: simplify notification service

test: add order API integration tests

chore: update dependencies
```

Avoid vague messages such as:

```
Update

Fix

Changes

Testing

Done
```

---

# 9. Pull Request Guidelines

Every pull request should include:

- Purpose
- Summary of changes
- Testing performed
- Documentation updated
- Breaking changes (if any)

---

# 10. Code Quality Expectations

Code should:

- Be readable.
- Be modular.
- Follow project architecture.
- Avoid duplication.
- Follow naming conventions.
- Include comments where appropriate.

---

# 11. Documentation Requirements

If a feature changes:

- APIs
- Database
- Business Rules
- User Experience
- Deployment
- Architecture

The relevant documentation must also be updated.

Documentation and code should remain synchronized.

---

# 12. Testing Requirements

Every contribution should include appropriate testing.

Examples:

- Unit Tests
- Integration Tests
- API Tests
- Manual Verification

Critical features require additional testing.

---

# 13. Database Changes

When modifying the database:

- Create a migration.
- Test migration locally.
- Verify rollback.
- Update schema documentation.

---

# 14. API Changes

When modifying APIs:

- Preserve backward compatibility whenever possible.
- Update API documentation.
- Update request/response examples.
- Document breaking changes.

---

# 15. UI Changes

When modifying the interface:

- Verify responsive layouts.
- Test accessibility.
- Check **both themes**. Light is the default and dark is opt-in, so light is the
  one most people see — but the palette is authored as `[data-theme="light"]`
  overrides on top of a dark `:root`, which means dark is what you get if a rule
  forgets to define its light value. A fixed colour that looks right in dark
  (`text-white` on a photo is fine; `text-white` on a card is not) disappears in
  light. Toggle it in Settings → Appearance and look at the page, both ways.
- Ensure consistency with the Design System.

Three theme rules that are easy to break by tidying:

1. **The theme is resolved in a blocking inline script in `<head>`**
   (`base.html`). It has to be: light is a `[data-theme]` override on a dark
   `:root`, so resolving it any later means every page load paints one dark frame
   and snaps to light. Do not move it, defer it, or give it a `src`.
2. **`applyTheme()` must not write to `localStorage`; only `toggleTheme()` may.**
   An absent key means "hasn't chosen", which is deliberately not the same as
   "chose light". If rendering a page persisted the fallback, the default could
   never be changed again for anyone who had already visited, and honouring
   `prefers-color-scheme` later would be impossible to add.
3. **One control, in Settings → Appearance.** The toggle used to sit in the
   sidebar, the mobile top bar, the bare footer, home.html and shop.html — five
   copies of a preference almost nobody changes twice, each one taking space from
   navigation on the screen where space is tightest. `toggleTheme` is global
   because settings.html calls it by name; renaming or scoping it breaks that
   page's only theme control silently, since nothing else references it.

All three are enforced by `tests/test_theme_default.py`.

Reference:

`36-design-system.md`

---

# 16. Security Review

Changes affecting:

- Authentication
- Authorization
- Payments
- Escrow
- File Uploads
- Administration

Require additional review.

---

# 17. Performance Review

Review:

- Database queries
- API response time
- Memory usage
- Background jobs
- Media optimization

Performance regressions should be avoided.

---

# 18. Review Checklist

Reviewers should verify:

- Requirements satisfied
- Code quality
- Documentation updated
- Tests passing
- Security considerations
- Performance considerations
- Naming consistency
- Maintainability

---

# 19. Merge Requirements

A pull request may be merged only when:

- Reviews are complete.
- Required tests pass.
- Documentation is updated.
- No blocking issues remain.

---

# 20. Handling Bugs

When reporting bugs:

Include:

- Summary
- Expected behavior
- Actual behavior
- Steps to reproduce
- Screenshots (if applicable)
- Logs (if applicable)

---

# 21. Feature Requests

Feature requests should include:

- Problem statement
- Proposed solution
- Benefits
- Possible drawbacks
- Related documentation

---

# 22. Refactoring

Refactoring should:

- Preserve behavior.
- Improve maintainability.
- Include regression testing.
- Avoid unrelated changes.

---

# 23. Dependency Updates

When updating dependencies:

- Review release notes.
- Test compatibility.
- Check security advisories.
- Update documentation if required.

---

# 24. Release Contributions

Before a release:

- Verify assigned tasks.
- Complete testing.
- Resolve outstanding issues.
- Confirm documentation is current.

---

# 25. Communication

Contributors should:

- Ask questions early.
- Explain technical decisions.
- Respond respectfully during reviews.
- Document important architectural changes.

---

# 26. Recommendation

Contributions should remain as focused as possible.

Each pull request should address a single feature, bug, or improvement rather than combining multiple unrelated changes. Smaller, well-defined contributions are easier to review, test, document, and revert if necessary.

Additionally, contributors should view documentation updates as part of the feature itself—not as an optional follow-up task. A feature is not considered complete until its documentation accurately reflects its implementation.

---

# 27. Summary

The CartFlow contribution process emphasizes quality, consistency, and maintainability.

By following standardized workflows, review practices, testing expectations, and documentation requirements, contributors help ensure the platform remains reliable, scalable, and easy to evolve as the project and development team grow.

---

# End of Document