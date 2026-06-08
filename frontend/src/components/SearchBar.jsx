import { LoaderCircle, Search } from "lucide-react";
import { useState } from "react";

export function SearchBar({ apiBaseUrl }) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (!query.trim()) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, limit: 5 }),
      });
      if (!response.ok) {
        throw new Error("Search failed");
      }
      setResult(await response.json());
    } catch (searchError) {
      setError(searchError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="sidebar-section search-section">
      <form className="search-form" onSubmit={submit}>
        <Search size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search calls" />
        <button className="icon-button" disabled={loading} title="Run search">
          {loading ? <LoaderCircle size={15} className="spin" /> : <Search size={15} />}
        </button>
      </form>
      {error ? <div className="error-text">{error}</div> : null}
      {result ? (
        <div className="search-result">
          <p>{result.answer}</p>
          {result.sources?.map((source, index) => (
            <div className="source" key={`${source.meeting_title}-${index}`}>
              <strong>{source.meeting_title}</strong>
              <span>{Math.round(source.similarity * 100)}%</span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
