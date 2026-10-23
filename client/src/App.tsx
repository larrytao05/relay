import "./App.css";
import { Navigate, Route, Routes } from "react-router";
import DashboardPage from "./DashboardPage.tsx";
import EditorPage from "./EditorPage.tsx";
import SignInPage from "./SignInPage.tsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<SignInPage />} />
      <Route path="/signup" element={<SignInPage mode="sign-up" />} />
      <Route path="/canvases" element={<DashboardPage />} />
      <Route path="/canvases/:canvasId" element={<EditorPage />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
