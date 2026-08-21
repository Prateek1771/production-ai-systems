export const API_BASE =
  import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Route = "vector" | "graph" | "hybrid";

export interface Citation {
  marker: number;
  kind: "graph" | "passage";
  chunk_ids: string[];
  text: string;
}

export interface Passage {
  chunk_id: string;
  filename: string;
  chunk_index: number;
  similarity: number;
  text: string;
}

export interface Fact {
  statement: string;
  hops: number;
  chunk_ids: string[];
  relation_path: string[];
}

export interface GraphNode {
  id: string;
  name: string;
  entity_type?: string | null;
  mentions?: number | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface QueryResponse {
  trace_id: string;
  question: string;
  answer: string;
  refused: boolean;
  repaired: boolean;
  route: Route;
  confidence: number;
  question_entities: string[];
  citations: Citation[];
  passages: Passage[];
  facts: Fact[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[] } | null;
  stages: Record<string, number>;
  total_ms: number;
}

export interface Chunk {
  chunk_id: string;
  document_id: string;
  filename: string;
  chunk_index: number;
  text: string;
}

export interface Stats {
  documents: number;
  chunks: number;
  embedded: number;
  extracted: number;
  entities: number;
  relations: number;
  mentions: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${body.slice(0, 200)}`);
  }

  return response.json() as Promise<T>;
}

export function askQuestion(
  question: string,
  topK = 5,
  route: Route | null = null,
): Promise<QueryResponse> {
  return request<QueryResponse>("/query", {
    method: "POST",
    body: JSON.stringify({
      question,
      top_k: topK,
      route,
      include_graph: true,
    }),
  });
}

export function fetchChunk(chunkId: string): Promise<Chunk> {
  return request<Chunk>(`/chunks/${chunkId}`);
}

export function fetchStats(): Promise<Stats> {
  return request<Stats>("/stats");
}
