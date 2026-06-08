import { ChevronDown, Download, FileText, LoaderCircle, Presentation, ScrollText } from "lucide-react";
import { useState } from "react";

const EXPORT_OPTIONS = [
  { format: "pptx", label: "PowerPoint", extension: "pptx", Icon: Presentation },
  { format: "markdown", label: "Markdown", extension: "md", Icon: ScrollText },
  { format: "pdf", label: "PDF", extension: "pdf", Icon: FileText },
];

export function ExportButton({ apiBaseUrl, meeting }) {
  const [open, setOpen] = useState(false);
  const [loadingFormat, setLoadingFormat] = useState("");
  const [error, setError] = useState("");

  function downloadUrl(url, filename) {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename || "";
    link.rel = "noopener noreferrer";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function exportMeeting(format) {
    if (!meeting) {
      return;
    }
    setLoadingFormat(format);
    setError("");
    setOpen(false);
    try {
      const response = await fetch(`${apiBaseUrl}/api/export/${meeting.id}?format=${format}`, { method: "POST" });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Export failed");
      }
      const data = await response.json();
      const url = data.download_url || data.pptx_url;
      if (url) {
        downloadUrl(url, data.filename);
      }
    } catch (exportError) {
      setError(exportError.message);
    } finally {
      setLoadingFormat("");
    }
  }

  const loading = Boolean(loadingFormat);

  return (
    <div className="export-control">
      <button
        className="secondary-button"
        onClick={() => setOpen((value) => !value)}
        disabled={!meeting || loading}
        title="Export meeting"
      >
        {loading ? <LoaderCircle size={16} className="spin" /> : <Download size={16} />}
        <span>{loading ? "Exporting" : "Export"}</span>
        <ChevronDown size={15} />
      </button>
      {open ? (
        <div className="export-menu">
          {EXPORT_OPTIONS.map(({ format, label, extension, Icon }) => (
            <button className="export-menu-item" key={format} onClick={() => exportMeeting(format)}>
              <Icon size={16} />
              <span>{label}</span>
              <span className="export-extension">.{extension}</span>
            </button>
          ))}
        </div>
      ) : null}
      {error ? <span className="export-error">{error}</span> : null}
    </div>
  );
}
