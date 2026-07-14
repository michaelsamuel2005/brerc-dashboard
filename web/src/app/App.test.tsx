import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { axe } from 'jest-axe';
import { describe, it, expect } from 'vitest';
import { App } from './App';

function renderApp(path = '/') {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <App />
    </MemoryRouter>,
  );
}

describe('App shell', () => {
  it('renders the landing heading', () => {
    renderApp();
    expect(
      screen.getByRole('heading', { level: 1, name: /explore wildlife records/i }),
    ).toBeInTheDocument();
  });

  it('always shows the "records, not populations" honesty caveat', () => {
    renderApp();
    expect(screen.getByText(/records, not a population count/i)).toBeInTheDocument();
  });

  it('provides a skip link to the main content', () => {
    renderApp();
    expect(screen.getByRole('link', { name: /skip to main content/i })).toBeInTheDocument();
  });

  it('has no automatically-detectable accessibility violations', async () => {
    const { container } = renderApp();
    expect(await axe(container)).toHaveNoViolations();
  });
});
