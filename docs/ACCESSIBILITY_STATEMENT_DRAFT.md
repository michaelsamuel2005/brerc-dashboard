# Accessibility statement wording (draft)

**Status:** draft evidence wording only; this is not the published accessibility statement.

The current `main` frontend does not yet contain the legal accessibility-statement page from the
archived integration branch. This file preserves the narrow wording correction for review without
copying that retired frontend tree or presenting an unfinished manual test as complete.

## Proposed touch-target wording

> **Touch targets** are designed to be at least 44 × 44 CSS pixels, stricter than the 24-pixel
> minimum in WCAG 2.2 Success Criterion 2.5.8. Automated measurement across the agreed viewport
> matrix must find no smaller control. Where a control overlaps the interactive map, a named
> reviewer must additionally confirm its usable hit area during the manual testing round before
> this statement is published.

This wording is deliberately conditional. A bounding box cannot prove that a target is unobscured,
unclipped and usable, and the archived manual-review ledger contains no completed reviewer
attestations. The future live statement must not change “must confirm” to “confirmed” until the
final release has a named review record.

## Publication gate

Before this text can move into a user-facing statement, all of the following are required:

- the publication-aware frontend and its legal statement page have been ported to `main` through
  the approved reconciliation sequence;
- the automated target-size evidence has been regenerated from the final release across the agreed
  viewport matrix;
- every map-overlap or otherwise indeterminate target has a named manual-review disposition;
- BRERC has supplied and approved the remaining organisation-specific legal wording and dates; and
- the final pull request has passed CI and received the required component-owner approval.

## Provenance

Adapted from `45576aa80e2c7aec36f3624d9b215e935a72cabd`. The source changed a React page that exists only on
the archived integration line; this main-based port records the wording safely until that page's
prerequisites are present. It does not merge or copy the archived frontend.
