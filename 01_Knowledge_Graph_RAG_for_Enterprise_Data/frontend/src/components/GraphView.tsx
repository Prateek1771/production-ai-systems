import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { GraphEdge, GraphNode } from "../api";

const TYPE_COLORS: Record<string, string> = {
  Person: "#7c9eff",
  Company: "#5ec9a7",
  Product: "#e0a458",
  Technology: "#c07ce0",
  Industry: "#6fb1d6",
  Location: "#d67c8a",
};

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlight?: string[];
}

export default function GraphView({ nodes, edges, highlight = [] }: Props) {
  const wrapper = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);

  useEffect(() => {
    const element = wrapper.current;
    if (!element) return;

    const observer = new ResizeObserver(() => {
      setWidth(element.clientWidth);
    });

    observer.observe(element);
    setWidth(element.clientWidth);

    return () => observer.disconnect();
  }, []);

  // react-force-graph mutates the objects it is given, so hand it copies.
  const data = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    return {
      nodes: nodes.map((n) => ({ ...n })),
      links: edges
        .filter((e) => ids.has(e.source) && ids.has(e.target))
        .map((e) => ({ ...e })),
    };
  }, [nodes, edges]);

  const highlighted = useMemo(
    () => new Set(highlight.map((name) => name.toLowerCase())),
    [highlight],
  );

  if (!nodes.length) {
    return (
      <div className="graph-empty">
        No graph neighbourhood for this question.
      </div>
    );
  }

  return (
    <div className="graph-wrapper" ref={wrapper}>
      <ForceGraph2D
        graphData={data}
        width={width}
        height={380}
        backgroundColor="transparent"
        cooldownTicks={80}
        linkColor={() => "rgba(140,150,170,0.35)"}
        linkDirectionalArrowLength={3}
        linkDirectionalArrowRelPos={1}
        linkLabel={(link: any) => link.relation}
        nodeLabel={(node: any) =>
          `${node.name} (${node.entity_type ?? "?"})`
        }
        nodeCanvasObject={(node: any, ctx, globalScale) => {
          const isHot = highlighted.has(String(node.name).toLowerCase());
          const radius = isHot ? 7 : 4.5;

          ctx.beginPath();
          ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
          ctx.fillStyle = TYPE_COLORS[node.entity_type ?? ""] ?? "#9aa4b2";
          ctx.fill();

          if (isHot) {
            ctx.lineWidth = 2 / globalScale;
            ctx.strokeStyle = "#f2f4f8";
            ctx.stroke();
          }

          const fontSize = Math.max(9, 12 / globalScale);
          ctx.font = `${fontSize}px system-ui, sans-serif`;
          ctx.fillStyle = "#cfd6e4";
          ctx.textAlign = "center";
          ctx.fillText(node.name, node.x, node.y + radius + fontSize);
        }}
      />
      <div className="graph-legend">
        {Object.entries(TYPE_COLORS).map(([type, color]) => (
          <span key={type}>
            <i style={{ background: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}
