import React, { useEffect, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

type Node = {
  id: string;
  label: string;
  [key: string]: any;
};

type Link = {
  source: string;
  target: string;
  type?: string;
};

const App = () => {
  const [graphData, setGraphData] = useState<{ nodes: Node[]; links: Link[] }>({
    nodes: [],
    links: []
  });


const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';

useEffect(() => {
  fetch(`${API_BASE}/graph`)
    .then((res) => res.json())
    .then((rawData) => {
      const nodes: Node[] = [];
      const links: Link[] = [];

      for (const el of rawData) {
        if (el.data.source && el.data.target) {
          links.push({
            source: el.data.source,
            target: el.data.target,
            type: el.data.label
          });
        } else {
          nodes.push({
            id: el.data.id,
            label: el.data.label,
            type: el.classes // optional, for color grouping
          });
        }
      }

      setGraphData({ nodes, links });
    });
}, []);




  return (
    <div style={{ height: "100vh", width: "100vw" }}>
      <ForceGraph2D
        graphData={graphData}
        nodeLabel="label"
        linkDirectionalArrowLength={6}
        linkDirectionalArrowRelPos={1}
        nodeAutoColorBy="type"
      />
    </div>
  );
};

export default App;
