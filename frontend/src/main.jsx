import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import { installApiContractFetch } from "./runtimeReadiness.js";
import "./styles.css";

installApiContractFetch(window);

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
