import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { EmptyState } from '../components/EmptyState';
import { usePageTitle } from '../context/PageTitleContext';

export default function NotFoundPage() {
  usePageTitle('Not found');
  return (
    <EmptyState
      icon={<Compass className="size-10" strokeWidth={1.5} />}
      title="Page not found"
      message="The page you are looking for does not exist."
      action={
        <Link to="/" className="btn btn-primary">
          Back to overview
        </Link>
      }
    />
  );
}
