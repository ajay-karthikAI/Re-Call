import { Check, Copy } from "lucide-react";
import { useState } from "react";

export function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="code-block">
      <div className="code-header">
        <span>{language || "code"}</span>
        <button className="icon-button" onClick={copyCode} title="Copy code">
          {copied ? <Check size={15} /> : <Copy size={15} />}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}
