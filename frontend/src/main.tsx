import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";

if (localStorage.getItem("interis.dark") === "1") document.documentElement.classList.add("dark");

// The server puts a fresh CSP nonce into this page. get-nonce, which the style library uses for
// its scroll-lock <style> elements, reads the global __webpack_nonce__ when it creates them.
const nonce = document.querySelector<HTMLMetaElement>('meta[name="csp-nonce"]')?.content;
if (nonce) (globalThis as { __webpack_nonce__?: string }).__webpack_nonce__ = nonce;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
