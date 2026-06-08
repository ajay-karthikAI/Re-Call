import { useState } from "react";

export function ReCallLogo({ className = "", src = "/recall-logo.png" }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  return (
    <div className={`recall-logo ${className} ${loaded ? "is-loaded" : ""}`} aria-label="Re: Call">
      {!failed ? (
        <img
          src={src}
          alt="Re: Call"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      ) : null}
      {!loaded ? (
        <div className="recall-logo-fallback" aria-hidden="true">
          <span>R:</span>
          <strong>Re<span>: Call</span></strong>
        </div>
      ) : null}
    </div>
  );
}
