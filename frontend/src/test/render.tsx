import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { App } from "../App";

export let currentLocation = "";
function Spy() {
  const l = useLocation();
  currentLocation = l.pathname + l.search;
  return null;
}

/** Full app at `url`, live WebSocket disabled, API mocked via mockFetch. */
export function renderApp(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchInterval: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <App live={false} />
        <Spy />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
