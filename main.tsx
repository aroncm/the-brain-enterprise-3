import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

type RootErrorBoundaryState = {
  error: Error | null;
};

class RootErrorBoundary extends React.Component<React.PropsWithChildren, RootErrorBoundaryState> {
  state: RootErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): RootErrorBoundaryState {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <main className="fatal-preview">
          <p>Run Saving Tool Preview Error</p>
          <h1>The frontend loaded, but React hit a runtime error.</h1>
          <pre>{this.state.error.message}</pre>
          <span>Open the browser console for the full stack trace.</span>
        </main>
      );
    }

    return this.props.children;
  }
}

const root = document.getElementById("root");

if (!root) {
  document.body.innerHTML = `
    <main class="fatal-preview">
      <p>Run Saving Tool Preview Error</p>
      <h1>Missing root element.</h1>
      <pre>index.html must include &lt;div id="root"&gt;&lt;/div&gt;.</pre>
    </main>
  `;
} else {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <RootErrorBoundary>
        <App />
      </RootErrorBoundary>
    </React.StrictMode>,
  );
}
