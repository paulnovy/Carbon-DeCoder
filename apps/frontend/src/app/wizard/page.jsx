"use client";

import { PageHeader } from "@/components/ui";

export default function WizardPage() {
  return (
    <div>
      <PageHeader
        eyebrow="Workflow"
        title="Wizard"
      />
      <div className="empty-state">
        <div className="empty-state-title">Wizard · SOON</div>
      </div>
    </div>
  );
}
