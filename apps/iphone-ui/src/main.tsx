import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./style.css";

document.getElementById("boot-status")?.remove();
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
