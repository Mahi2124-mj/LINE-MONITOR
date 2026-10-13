import { lazy, Suspense, type ReactElement } from 'react';
import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { AlertToaster } from './components/AlertToaster';
import { SkeletonPanel, SkeletonTiles } from './components/EmptyState';
import { LiveProvider } from './context/LiveContext';
import { PageTitleProvider } from './context/PageTitleContext';
import { RangeProvider } from './context/RangeContext';
import { ToastProvider } from './context/ToastContext';

const OverviewPage = lazy(() => import('./pages/OverviewPage'));
const LinePage = lazy(() => import('./pages/LinePage'));
const StationPage = lazy(() => import('./pages/StationPage'));
const MovementPage = lazy(() => import('./pages/MovementPage'));
const CamerasPage = lazy(() => import('./pages/CamerasPage'));
const CameraDetailPage = lazy(() => import('./pages/CameraDetailPage'));
const ZoneEditorPage = lazy(() => import('./pages/ZoneEditorPage'));
const AnalysisIndexPage = lazy(() => import('./pages/AnalysisIndexPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const AlertsPage = lazy(() => import('./pages/AlertsPage'));
const ReportsPage = lazy(() => import('./pages/ReportsPage'));
const ReportViewPage = lazy(() => import('./pages/ReportViewPage'));
const SetupPage = lazy(() => import('./pages/SetupPage'));
const AdvancedSetupPage = lazy(() => import('./pages/AdvancedSetupPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

function PageFallback() {
  return (
    <div className="space-y-4">
      <SkeletonTiles />
      <SkeletonPanel className="h-72" />
    </div>
  );
}

export default function App() {
  return (
    <RangeProvider>
      <ToastProvider>
        <LiveProvider>
          <PageTitleProvider>
            <AlertToaster />
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Lazy el={<OverviewPage />} />} />
                <Route path="lines/:id" element={<Lazy el={<LinePage />} />} />
                <Route path="stations/:id" element={<Lazy el={<StationPage />} />} />
                <Route path="movement" element={<Lazy el={<MovementPage />} />} />
                <Route path="cameras" element={<Lazy el={<CamerasPage />} />} />
                <Route path="cameras/:id" element={<Lazy el={<CameraDetailPage />} />} />
                <Route path="cameras/:id/zones" element={<Lazy el={<ZoneEditorPage />} />} />
                <Route path="analysis" element={<Lazy el={<AnalysisIndexPage />} />} />
                <Route path="analysis/:cameraId" element={<Lazy el={<AnalysisPage />} />} />
                <Route path="alerts" element={<Lazy el={<AlertsPage />} />} />
                <Route path="reports" element={<Lazy el={<ReportsPage />} />} />
                <Route path="reports/:name" element={<Lazy el={<ReportViewPage />} />} />
                <Route path="setup" element={<Lazy el={<SetupPage />} />} />
                <Route path="setup/advanced" element={<Lazy el={<AdvancedSetupPage />} />} />
                <Route path="*" element={<Lazy el={<NotFoundPage />} />} />
              </Route>
            </Routes>
          </PageTitleProvider>
        </LiveProvider>
      </ToastProvider>
    </RangeProvider>
  );
}

function Lazy({ el }: { el: ReactElement }) {
  return <Suspense fallback={<PageFallback />}>{el}</Suspense>;
}
