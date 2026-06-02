"use client";

export function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <div className="page-header">
      <div className="page-header-copy">
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}

export function Panel({ title, description, actions, className = "", children, ...props }) {
  return (
    <section className={`card panel ${className}`} {...props}>
      {(title || description || actions) && (
        <div className="panel-header">
          <div className="panel-header-copy">
            {title && <h2>{title}</h2>}
            {description && <p>{description}</p>}
          </div>
          {actions && <div className="panel-header-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...props
}) {
  return (
    <button className={`btn btn-${variant} btn-${size} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function EmptyState({ title = "No data", description, action }) {
  return (
    <Panel className="empty-state">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </Panel>
  );
}

export function ConfirmDialog({
  open,
  title,
  description,
  details = [],
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "danger",
  busy = false,
  confirmDisabled = false,
  onCancel,
  onConfirm,
}) {
  if (!open) return null;
  const confirmVariant = tone === "danger" ? "danger" : tone === "warning" ? "warning" : "primary";

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>{title}</h2>
        </div>
        {description && <p className="modal-description">{description}</p>}
        {details.length > 0 && (
          <ul className="modal-detail-list">
            {details.map((item) => <li key={item}>{item}</li>)}
          </ul>
        )}
        {children}
        <div className="modal-actions">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>{cancelLabel}</Button>
          <Button variant={confirmVariant} onClick={onConfirm} disabled={busy || confirmDisabled}>
            {busy ? "Working..." : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
