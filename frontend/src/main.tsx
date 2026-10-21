import { createClient } from "@supabase/supabase-js";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TutorApp } from "./tutor";
import "./index.css";

// Public values only (written by `make env` into frontend/.env.local): URL + publishable key.
const supabase = createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TutorApp supabase={supabase} apiBase="/tutor" />
  </StrictMode>,
);
