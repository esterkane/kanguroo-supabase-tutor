import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TutorApp } from "./tutor";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TutorApp apiBase="/tutor" />
  </StrictMode>,
);
