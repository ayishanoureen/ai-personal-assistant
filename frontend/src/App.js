import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Home from "./pages/Home";
import Login from "./pages/Login";
import useAutoLogout from "./hooks/useAutoLogout";

function ProtectedRoute({ children }) {
  const token = sessionStorage.getItem("token");

  const lastActivity =
    localStorage.getItem("lastActivity");

  const expired =
    !lastActivity ||
    Date.now() - Number(lastActivity) >
    2 * 60 * 60 * 1000;

  if (!token || expired) {
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("userName");
    localStorage.removeItem("lastActivity");

    return <Navigate to="/login" replace />;
  }

  return children;
}

export default function App() {
  useAutoLogout();
  return (
    <BrowserRouter>
      <Routes>

        <Route path="/login" element={<Login />} />

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Home />
            </ProtectedRoute>
          }
        />

      </Routes>
    </BrowserRouter>
  );
}