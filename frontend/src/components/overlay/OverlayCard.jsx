import { Check, Copy, X } from "lucide-react";
import { useState } from "react";

export function OverlayCard({
  id,
  eyebrow,
  title,
  icon: Icon,
  children,
  tone = "default",
  copyText = "",
  onDismiss,
}) {
  const [copied, setCopied] = useState(false);

  async function copyToClipboard() {
    if (!copyText) {
      return;
    }

    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  }

  return (
    <article className={`overlay-ai-card overlay-ai-card-${tone}`}>
      <div className="overlay-ai-card-header">
        <div className="overlay-ai-card-title">
          {Icon ? <Icon size={15} /> : null}
          <div>
            {eyebrow ? <span>{eyebrow}</span> : null}
            <h3>{title}</h3>
          </div>
        </div>
        <div className="overlay-ai-card-actions">
          {copyText ? (
            <button type="button" onClick={copyToClipboard} title="Copy suggested answer">
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          ) : null}
          {onDismiss ? (
            <button type="button" onClick={() => onDismiss(id)} title="Dismiss card">
              <X size={14} />
            </button>
          ) : null}
        </div>
      </div>
      <div className="overlay-ai-card-body">{children}</div>
    </article>
  );
}
