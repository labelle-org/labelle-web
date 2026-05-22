import { useEffect, useState } from "react";

const REPO_URL = "https://github.com/szrudi/labelle-web";

interface HealthInfo {
  version: string;
  commit?: string;
  branch?: string;
}

export function Footer() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [latestVersion, setLatestVersion] = useState<string | null>(null);

  // Read the running server's `/api/health` for the real version, branch
  // and commit. The Vite-injected __APP_VERSION__ is a build-time
  // fallback for the very early window before the API responds.
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: HealthInfo | null) => {
        if (data?.version) setHealth(data);
      })
      .catch(() => {
        // AbortError on unmount, or network failure — fall back to __APP_VERSION__.
      });
    return () => controller.abort();
  }, []);

  // Only nag about a newer release when we're on a production build —
  // dev builds are usually ahead of the latest tag, and `latest !==
  // version` would otherwise flag every feature branch as "out of date".
  const onMain = health?.branch === "main";
  useEffect(() => {
    if (!health?.version || !onMain) return;
    const controller = new AbortController();
    fetch("https://api.github.com/repos/szrudi/labelle-web/releases/latest", {
      signal: controller.signal,
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data?.tag_name) return;
        const latest = data.tag_name.replace(/^v/, "");
        if (latest !== health.version) {
          setLatestVersion(latest);
        }
      })
      .catch(() => {
        // AbortError on unmount, or GH API unreachable — skip the "newer release" hint.
      });
    return () => controller.abort();
  }, [health?.version, onMain]);

  const version = health?.version ?? __APP_VERSION__;
  const commit = health?.commit;
  // "Dev" = anything not built from main. release.yml stamps GIT_BRANCH=main
  // for production images, so onMain is a reliable signal.
  const isDev = health?.branch !== undefined && !onMain;

  return (
    <footer className="mt-8 text-center text-xs text-gray-400">
      <div className="mx-auto mb-3 max-w-2xl rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
        <strong>Heads up:</strong> labelle-web has moved to{" "}
        <a
          href="https://github.com/labelle-org/labelle-web"
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium underline hover:text-amber-700"
        >
          labelle-org/labelle-web
        </a>
        . Update <code>compose.yaml</code> to pull{" "}
        <code>ghcr.io/labelle-org/labelle-web:latest</code>.{" "}
        <a
          href="https://github.com/labelle-org/labelle/issues/139"
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:text-amber-700"
        >
          Context
        </a>
        .
      </div>
      <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="hover:text-gray-600">
        Labelle Web
      </a>{" "}
      v{version}
      {isDev && (
        <span className="text-gray-500">
          -dev{commit && ` (${commit})`}
        </span>
      )}
      {latestVersion && (
        <>
          {" · "}
          <a
            href={`${REPO_URL}/releases/tag/v${latestVersion}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:text-blue-600"
          >
            v{latestVersion} available
          </a>
        </>
      )}
    </footer>
  );
}