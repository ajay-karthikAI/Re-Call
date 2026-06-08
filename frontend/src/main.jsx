import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import OverlayApp from "./OverlayApp.jsx";
import "./styles/globals.css";

const params = new URLSearchParams(window.location.search);
const RootComponent = params.get("view") === "overlay" ? OverlayApp : App;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RootComponent />
  </React.StrictMode>
);
