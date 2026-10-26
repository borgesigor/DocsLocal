export type WorkspaceRoute = {
  projectId: string | null
  documentId: string | null
  documentPath: string | null
  invalid: boolean
}

export function readWorkspaceRoute(url: URL): WorkspaceRoute {
  const empty: WorkspaceRoute = {
    projectId: null,
    documentId: null,
    documentPath: null,
    invalid: false,
  }
  if (url.pathname === "/") {
    return {
      ...empty,
      projectId: url.searchParams.get("project"),
      documentId: url.searchParams.get("document"),
    }
  }

  let segments: string[]
  try {
    segments = url.pathname
      .replace(/\/$/, "")
      .slice(1)
      .split("/")
      .map(decodeURIComponent)
  } catch {
    return { ...empty, invalid: true }
  }
  const [projectId, ...documentSegments] = segments
  if (
    !/^[A-Za-z0-9_-]+$/.test(projectId) ||
    segments.some(
      (segment) =>
        !segment || segment === "." || segment === ".." || /[/\\]/.test(segment)
    )
  ) {
    return { ...empty, invalid: true }
  }
  const documentPath = documentSegments.join("/") || null
  if (
    documentPath &&
    (!documentPath.toLowerCase().endsWith(".md") ||
      documentSegments.some((segment) => segment.toLowerCase() === ".git"))
  ) {
    return { ...empty, invalid: true }
  }
  return { projectId, documentPath, documentId: null, invalid: false }
}

export function buildWorkspaceLocation(
  currentUrl: URL,
  projectId: string | null,
  documentPath: string | null
): string {
  const url = new URL(currentUrl)
  const segments = projectId
    ? [projectId, ...(documentPath?.split("/") ?? [])]
    : []
  url.pathname = "/" + segments.map(encodeURIComponent).join("/")
  url.searchParams.delete("project")
  url.searchParams.delete("document")
  return `${url.pathname}${url.search}${url.hash}`
}
