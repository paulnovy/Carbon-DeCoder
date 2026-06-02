export default function NotFound() {
  return (
    <div style={{ padding: 40, textAlign: "center" }}>
      <h1 style={{ fontSize: 48, fontWeight: 700, color: "var(--color-accent)", marginBottom: 8 }}>404</h1>
      <p style={{ fontSize: 16, color: "var(--color-text-secondary)" }}>Page not found</p>
      <a href="/" style={{ color: "var(--color-accent)", fontSize: 14, marginTop: 16, display: "inline-block" }}>
        ← Back to Dashboard
      </a>
    </div>
  );
}
