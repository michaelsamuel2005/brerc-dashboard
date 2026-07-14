import '@testing-library/jest-dom/vitest';
import { expect } from 'vitest';
import { toHaveNoViolations } from 'jest-axe';

// Adds `toHaveNoViolations()` so component tests can assert accessibility (R5).
expect.extend(toHaveNoViolations);
