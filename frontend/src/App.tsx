import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import AccuracyPage from "./pages/Accuracy";
import DecisionPage from "./pages/Decision";
import MethodologyPage from "./pages/Methodology";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<DecisionPage />} />
        <Route path="/accuracy" element={<AccuracyPage />} />
        <Route path="/about" element={<MethodologyPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
