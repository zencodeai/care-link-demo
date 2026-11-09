import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { HelpApp } from "./trust/HelpApp";
import "./styles.css";

const root = document.getElementById("root");
if (root === null) throw new Error("Missing application root");
createRoot(root).render(
  <StrictMode>
    {import.meta.env.VITE_SURFACE === "help" ? <HelpApp /> : <App />}
  </StrictMode>,
);
