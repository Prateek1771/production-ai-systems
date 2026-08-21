import { useEffect, useState } from "react";
import "./App.css";
import GraphView from "./components/GraphView";
import {
  askQuestion,
  fetchChunk,
  fetchStats,
  type Chunk,
  type QueryResponse,
  type Route,
  type Stats,
} from "./api";

const EXAMPLES = [
  "Who runs NVIDIA?",
  "Which cloud provider does OpenAI use?",
  "How is Microsoft connected to OpenAI?",
  "What is Anthropic focused on?",
  "Which companies compete with NVIDIA?",
];

export default function App() {
  const [question, setQuestion] = useState(EXAMPLES[1]);
  const [route, setRoute] = useState<Route | "auto">("auto");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [openChunk, setOpenChunk] = useState<Chunk | null>(null);

  useEffect(() => {
    fetchStats().then(setStats).catch(() => setStats(null));
  }, []);

  async function submit(text: string) {
    if (!text.trim() || loading) return;

    setLoading(true);
    setError(null);
    setOpenChunk(null);

    try {
      setResult(
        await askQuestion(text, 5, route === "auto" ? null : route),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function showChunk(chunkId: string) {
    try {
      setOpenChunk(await fetchChunk(chunkId));
    } catch {
      setOpenChunk(null);
    }
  }

  // Turn [1] markers in the answer into buttons that open the source.
  function renderAnswer(answer: string) {
    const parts = answer.split(/(\[\d+\])/g);

    return parts.map((part, index) => {
      const match = part.match(/^\[(\d+)\]$/);
      if (!match) return <span key={index}>{part}</span>;

      const marker = Number(match[1]);
      const citation = result?.citations.find((c) => c.marker === marker);

      return (
        <button
          key={index}
          className={`marker ${citation?.kind ?? "unknown"}`}
          title={citation?.text ?? "unresolved citation"}
          onClick={() =>
            citation?.chunk_ids[0] && showChunk(citation.chunk_ids[0])
          }
        >
          {marker}
        </button>
      );
    });
  }

  return (
    <div className="app">
      <header>
        <h1>Knowledge Graph RAG</h1>
        {stats && (
          <div className="stats">
            <span>{stats.documents} docs</span>
            <span>{stats.chunks} chunks</span>
            <span>{stats.embedded} embedded</span>
            <span>{stats.extracted} extracted</span>
            <span>{stats.entities} entities</span>
            <span>{stats.relations} relations</span>
          </div>
        )}
      </header>

      <form
        className="ask"
        onSubmit={(event) => {
          event.preventDefault();
          submit(question);
        }}
      >
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about companies, executives, or products"
        />
        <select
          value={route}
          onChange={(event) => setRoute(event.target.value as Route | "auto")}
        >
          <option value="auto">auto</option>
          <option value="vector">vector</option>
          <option value="graph">graph</option>
          <option value="hybrid">hybrid</option>
        </select>
        <button type="submit" disabled={loading}>
          {loading ? "thinking" : "ask"}
        </button>
      </form>

      <div className="examples">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            onClick={() => {
              setQuestion(example);
              submit(example);
            }}
          >
            {example}
          </button>
        ))}
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <>
          <section className={`answer ${result.refused ? "refused" : ""}`}>
            <div className="badges">
              <span className={`badge route-${result.route}`}>
                {result.route}
              </span>
              <span className="badge">
                confidence {result.confidence.toFixed(2)}
              </span>
              <span className="badge">{result.total_ms.toFixed(0)} ms</span>
              {result.repaired && (
                <span className="badge warn">citations repaired</span>
              )}
              {result.refused && (
                <span className="badge warn">refused</span>
              )}
            </div>

            <p className="answer-text">{renderAnswer(result.answer)}</p>

            <div className="timings">
              {Object.entries(result.stages).map(([stage, ms]) => (
                <span key={stage}>
                  {stage} <b>{ms.toFixed(0)}ms</b>
                </span>
              ))}
            </div>
          </section>

          {openChunk && (
            <section className="chunk">
              <div className="chunk-head">
                <strong>
                  {openChunk.filename} #{openChunk.chunk_index}
                </strong>
                <button onClick={() => setOpenChunk(null)}>close</button>
              </div>
              <p>{openChunk.text}</p>
            </section>
          )}

          <div className="columns">
            <section>
              <h2>Graph facts ({result.facts.length})</h2>
              {result.facts.length === 0 && <p className="muted">none</p>}
              <ul className="facts">
                {result.facts.map((fact, index) => (
                  <li key={index}>
                    <span className="hops">{fact.hops}h</span>
                    {fact.statement}
                    <span className="path">
                      {fact.relation_path.join(" -> ")}
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h2>Passages ({result.passages.length})</h2>
              {result.passages.length === 0 && <p className="muted">none</p>}
              <ul className="passages">
                {result.passages.map((passage) => (
                  <li key={passage.chunk_id}>
                    <div className="passage-head">
                      <span>{passage.filename} #{passage.chunk_index}</span>
                      <span className="sim">
                        {passage.similarity.toFixed(3)}
                      </span>
                    </div>
                    <p>{passage.text.slice(0, 220)}...</p>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section>
            <h2>Entity neighbourhood</h2>
            <GraphView
              nodes={result.graph?.nodes ?? []}
              edges={result.graph?.edges ?? []}
              highlight={result.question_entities}
            />
          </section>
        </>
      )}
    </div>
  );
}
