import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./styles/global.css";
import "./styles/hcm.css";
import "./styles/dossier.css";
import "./styles/roster.css";
import "./styles/scheduling.css";
import "./styles/acd.css";
import "./styles/wfm.css";
import "./styles/payroll.css";
import "./styles/phase21.css";
import "./styles/layout.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
