import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading, ToastProvider } from "./components/ui";
import { AuthProvider, isStaff, useAuth } from "./lib/auth";

const Login = lazy(() => import("./pages/Login"));
const Home = lazy(() => import("./pages/Home"));
const TaskMap = lazy(() => import("./pages/TaskMap"));
const Workflows = lazy(() => import("./pages/Workflows"));
const WorkflowEditor = lazy(() => import("./pages/WorkflowEditor"));
const Candidates = lazy(() => import("./pages/Candidates"));
const Candidate360 = lazy(() => import("./pages/Candidate360"));
const Pipeline = lazy(() => import("./pages/Pipeline"));
const Requirements = lazy(() => import("./pages/Requirements"));
const RequirementDetail = lazy(() => import("./pages/RequirementDetail"));
const Delegation = lazy(() => import("./pages/Delegation"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Impact = lazy(() => import("./pages/Impact"));
const Compliance = lazy(() => import("./pages/Compliance"));
const Settings = lazy(() => import("./pages/Settings"));
const Portal = lazy(() => import("./pages/Portal"));
const Consent = lazy(() => import("./pages/Consent"));

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function HomeRoute() {
  const { user } = useAuth();
  return isStaff(user) ? <Home /> : <Navigate to="/delegation" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/portal/:token" element={<Portal />} />
              <Route path="/consent/:token" element={<Consent />} />
              <Route path="/" element={<Protected><HomeRoute /></Protected>} />
              <Route path="/tasks" element={<Protected><TaskMap /></Protected>} />
              <Route path="/workflows" element={<Protected><Workflows /></Protected>} />
              <Route path="/workflows/:id" element={<Protected><WorkflowEditor /></Protected>} />
              <Route path="/candidates" element={<Protected><Candidates /></Protected>} />
              <Route path="/candidates/:id" element={<Protected><Candidate360 /></Protected>} />
              <Route path="/pipeline" element={<Protected><Pipeline /></Protected>} />
              <Route path="/requirements" element={<Protected><Requirements /></Protected>} />
              <Route path="/requirements/:id" element={<Protected><RequirementDetail /></Protected>} />
              <Route path="/delegation" element={<Protected><Delegation /></Protected>} />
              <Route path="/analytics" element={<Protected><Analytics /></Protected>} />
              <Route path="/impact" element={<Protected><Impact /></Protected>} />
              <Route path="/compliance" element={<Protected><Compliance /></Protected>} />
              <Route path="/settings" element={<Protected><Settings /></Protected>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
