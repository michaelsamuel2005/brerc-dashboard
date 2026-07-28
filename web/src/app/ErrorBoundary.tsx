import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  label?: string;
}
interface State {
  hasError: boolean;
}

// Per-feature boundary: one failure degrades gracefully instead of blanking the page.
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Log without leaking sensitive detail.
    console.error("Feature error:", error.message, info.componentStack);
  }

  override render(): ReactNode {
    if (this.state.hasError) {
      return <div role="alert">Sorry — {this.props.label ?? "this section"} could not be displayed.</div>;
    }
    return this.props.children;
  }
}
