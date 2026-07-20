import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import { Providers } from "./app/providers";
import "./styles/tokens.css";

// In dev the whole UI runs against the MSW mock (A11) — no backend needed.
async function enableMocking(): Promise<void> {
  if (!import.meta.env.DEV) return;
  const { worker } = await import("./test/msw/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}

void enableMocking().then(() => {
  const rootEl = document.getElementById("root");
  if (!rootEl) throw new Error("Root element #root not found");
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <Providers>
        <App />
      </Providers>
    </React.StrictMode>,
  );
});
