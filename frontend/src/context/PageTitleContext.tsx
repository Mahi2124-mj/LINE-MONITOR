import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export interface Crumb {
  label: string;
  to?: string;
}

interface PageTitle {
  title: string;
  crumbs: Crumb[];
}

interface Ctx {
  page: PageTitle;
  setPage: (p: PageTitle) => void;
}

const TitleCtx = createContext<Ctx | null>(null);

export function PageTitleProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageTitle>({ title: '', crumbs: [] });
  const value = useMemo(() => ({ page, setPage }), [page]);
  return <TitleCtx.Provider value={value}>{children}</TitleCtx.Provider>;
}

export function usePageTitleValue(): PageTitle {
  return useContext(TitleCtx)?.page ?? { title: '', crumbs: [] };
}

/** Set the top-bar title (and document title). `crumbs` are shown before the title. */
export function usePageTitle(title: string, crumbs: Crumb[] = []): void {
  const ctx = useContext(TitleCtx);
  const setPage = ctx?.setPage;
  const crumbKey = JSON.stringify(crumbs);
  useEffect(() => {
    if (!setPage) return;
    setPage({ title, crumbs: JSON.parse(crumbKey) as Crumb[] });
    document.title = title ? `${title} · Line Monitor` : 'Line Monitor';
  }, [setPage, title, crumbKey]);
}
