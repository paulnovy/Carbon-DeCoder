"use client";

import { useState, useEffect } from "react";
import { API_BASE, fetchApiHealth } from "@/lib/api";

export default function TopBar() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const fetchStatus = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const nextHealth = await fetchApiHealth(API_BASE, { timeoutMs: 5000 });
        if (!cancelled) setHealth(nextHealth);
      } catch {
        if (!cancelled) setHealth(null);
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 60000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <header className="topbar">
      <div style={{ flex: 1 }} />
      <div className="topbar-status">
        <div className={`topbar-indicator ${health?.ok ? "ok" : "err"}`}>
          <span />
          {health?.ok ? "API Connected" : "API Disconnected"}
        </div>
        <span className="badge badge-warn">non-diagnostic</span>
      </div>
    </header>
  );
}
