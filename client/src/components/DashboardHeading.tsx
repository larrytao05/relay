export default function DashboardHeading() {
  return (
    <div className="dashboard-heading">
      <div>
        <h1>Your canvases</h1>
        <p>Choose a canvas to open, or start a new one.</p>
      </div>
      <button className="button primary" type="button">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path
            d="M10 4v12M4 10h12"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
        New canvas
      </button>
    </div>
  );
}
