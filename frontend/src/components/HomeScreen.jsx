import { LayoutList, LoaderCircle, Mic } from "lucide-react";
import { ReCallLogo } from "./ReCallLogo.jsx";

export function HomeScreen({ onStart, onDashboard, status, error }) {
  const isStarting = status === "starting";

  return (
    <main className="home-screen">
      <div className="home-grid" aria-hidden="true" />
      <section className="home-content">
        <ReCallLogo className="home-logo" />
        <p className="home-tagline">Meetings, enhanced by AI</p>

        {error ? <div className="home-error">{error}</div> : null}

        <div className="home-actions">
          <button className="home-primary-action" onClick={onStart} disabled={isStarting}>
            {isStarting ? <LoaderCircle size={22} className="spin" /> : <Mic size={22} />}
            <span>{isStarting ? "Starting Meeting" : "Start a New Recorded Meeting"}</span>
          </button>
          <button className="home-secondary-action" onClick={onDashboard}>
            <LayoutList size={22} />
            <span>View Dashboard / Past Meetings</span>
          </button>
        </div>
      </section>
    </main>
  );
}
