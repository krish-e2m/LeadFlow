import React from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  /** Right-aligned actions: one ink primary button, the rest secondary or ghost. */
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, actions }) => (
  <div className="flex flex-wrap items-start justify-between gap-4">
    <div className="min-w-0">
      <h1 className="text-2xl font-semibold text-fg">{title}</h1>
      {description && <p className="mt-1 text-sm text-fg-secondary">{description}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </div>
);
