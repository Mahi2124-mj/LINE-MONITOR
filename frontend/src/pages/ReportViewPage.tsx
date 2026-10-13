import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ExternalLink } from 'lucide-react';
import { api } from '../api/client';
import { usePageTitle } from '../context/PageTitleContext';
import { usePolling } from '../hooks/usePolling';

/** One saved report shown inside the dashboard (the report is a self-contained page with its video). */
export default function ReportViewPage() {
  const { name = '' } = useParams();
  const reports = usePolling(() => api.reports(), [], 0);
  const report = reports.data?.find((r) => r.name === name);
  usePageTitle(report?.title ?? 'Report');
  const url = api.reportUrl(name);

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-[480px] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/reports" className="btn btn-sm">
          <ArrowLeft className="size-3.5" /> All reports
        </Link>
        <a href={url} target="_blank" rel="noreferrer" className="btn btn-sm">
          <ExternalLink className="size-3.5" /> Open in new tab
        </a>
      </div>
      <iframe title={report?.title ?? name} src={url} className="w-full flex-1 rounded-xl border border-edge bg-panel" />
    </div>
  );
}
