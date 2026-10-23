import CanvasList from "./components/CanvasList.tsx";
import DashboardHeader from "./components/DashboardHeader.tsx";
import DashboardHeading from "./components/DashboardHeading.tsx";
import type { CanvasSummary } from "./types.ts";
import "./DashboardPage.css";

const canvases = [
  { id: "checkout", name: "Checkout flow", preview: "checkout" },
  { id: "account", name: "Account setup", preview: "account" },
  { id: "planning", name: "Q4 planning", preview: "planning" },
] satisfies CanvasSummary[];

export default function DashboardPage() {
  return (
    <div className="dashboard-page">
      <DashboardHeader />
      <main className="dashboard-content">
        <DashboardHeading />
        <CanvasList canvases={canvases} />
      </main>
    </div>
  );
}
