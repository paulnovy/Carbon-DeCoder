"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/", icon: "◉" },
  { label: "Wizard", href: "/wizard", icon: "⬆", disabled: true, badge: "SOON", title: "Wizard workflow is coming soon." },
  { label: "Projects", href: "/projects", icon: "▣" },
  { label: "Runs", href: "/runs", icon: "▶" },
  { label: "divider" },
  { label: "Variants", href: "/variants", icon: "◇" },
  { label: "Coverage", href: "/coverage", icon: "▬" },
  { label: "SV / CNV", href: "/sv-cnv", icon: "⬡" },
  { label: "Taxonomy", href: "/taxonomy", icon: "❋" },
  { label: "mtDNA", href: "/mtdna", icon: "🔬" },
  { label: "PRS", href: "/prs", icon: "📊" },
  { label: "Insights", href: "/insights", icon: "✦" },
  { label: "Genome Browser", href: "/genome", icon: "⌬" },
  { label: "divider" },
  { label: "Reports", href: "/reports", icon: "⎙" },
  { label: "Benchmark", href: "/benchmark", icon: "⚑", disabled: true, badge: "EXPERIMENTAL", title: "Benchmark is experimental and currently disabled." },
  { label: "Dark Matter", href: "/dark-matter", icon: "◒", disabled: true, badge: "EXPERIMENTAL", title: "Dark Matter is experimental and currently disabled." },
  { label: "divider" },
  { label: "Settings", href: "/settings", icon: "⚙" },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-logo">⬡</span>
        <span className="sidebar-title-stack">
          <span className="sidebar-title-main">Carbon DeCoder</span>
          <span className="sidebar-title-sub">WGS Cockpit</span>
        </span>
      </div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item, i) =>
          item.label === "divider" ? (
            <div key={`d-${i}`} className="sidebar-divider" />
          ) : item.disabled ? (
            <div key={item.label} className="sidebar-link sidebar-link-disabled" title={item.title} aria-disabled="true">
              <span className="sidebar-icon">{item.icon}</span>
              <span className="sidebar-link-text">
                <span>{item.label}</span>
                {item.badge && <small>{item.badge}</small>}
              </span>
            </div>
          ) : (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar-link ${pathname === item.href ? "active" : ""}`}
            >
              <span className="sidebar-icon">{item.icon}</span>
              {item.label}
            </Link>
          )
        )}
      </nav>
      <div className="sidebar-footer">
        research-only · non-diagnostic
      </div>
    </aside>
  );
}
