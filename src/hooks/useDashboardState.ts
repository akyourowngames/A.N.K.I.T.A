"use client";

import { useEffect, useState } from "react";
import { fetchDashboardState, type DashboardState } from "../lib/assistantClient";

const DASHBOARD_REFRESH_MS = 5000;

export function useDashboardState() {
  const [dashboard, setDashboard] = useState<DashboardState | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let active = true;

    async function refresh() {
      try {
        const nextDashboard = await fetchDashboardState();
        if (!active) {
          return;
        }
        setDashboard(nextDashboard);
        setOffline(!nextDashboard);
      } catch {
        if (active) {
          setOffline(true);
        }
      }
    }

    refresh();
    const interval = window.setInterval(refresh, DASHBOARD_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  return { dashboard, offline };
}
