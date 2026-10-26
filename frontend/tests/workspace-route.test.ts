import assert from "node:assert/strict"
import { test } from "node:test"
import {
  readWorkspaceRoute,
  buildWorkspaceLocation,
} from "../src/lib/workspace-route.ts"

test("reads the document path and project from the address", () => {
  assert.deepEqual(
    readWorkspaceRoute(
      new URL("http://localhost/demo-project/docs/regras-para-agentes.md")
    ),
    {
      projectId: "demo-project",
      documentId: null,
      documentPath: "docs/regras-para-agentes.md",
      invalid: false,
    }
  )
})

test("decodes each segment once, including spaces, accents and literal percent", () => {
  const route = readWorkspaceRoute(
    new URL(
      "http://localhost/demo-project/docs/guia%20de%20a%C3%A7%C3%A3o/100%25.md"
    )
  )
  assert.equal(route.documentPath, "docs/guia de ação/100%.md")
})

test("reads index and project-only addresses", () => {
  assert.equal(
    readWorkspaceRoute(new URL("http://localhost/demo-project/index.md"))
      .documentPath,
    "index.md"
  )
  const project = readWorkspaceRoute(new URL("http://localhost/demo-project/"))
  assert.equal(project.projectId, "demo-project")
  assert.equal(project.documentPath, null)
})

test("keeps legacy query links readable", () => {
  const route = readWorkspaceRoute(
    new URL("http://localhost/?project=demo-project&document=stable-id")
  )
  assert.equal(route.projectId, "demo-project")
  assert.equal(route.documentId, "stable-id")
  assert.equal(route.documentPath, null)
})

test("path addresses take precedence over stale legacy parameters", () => {
  const route = readWorkspaceRoute(
    new URL(
      "http://localhost/demo-project/docs/guia.md?project=other&document=old"
    )
  )
  assert.equal(route.projectId, "demo-project")
  assert.equal(route.documentPath, "docs/guia.md")
  assert.equal(route.documentId, null)
})

test("reads Markdown at the project root and in any folder", () => {
  for (const path of ["skill.md", "abc/note.md", "assets/note.md"]) {
    const route = readWorkspaceRoute(new URL(`http://docs.local/demo-project/${path}`))
    assert.equal(route.invalid, false)
    assert.equal(route.documentPath, path)
  }
})

test("rejects invalid path encodings and non-Markdown routes", () => {
  for (const path of [
    "/demo-project/docs/%ZZ.md",
    "/demo-project/project.toml",
    "/demo-project/docs/a%2Fb.md",
    "/demo-project/docs/a%5Cb.md",
  ]) {
    assert.equal(
      readWorkspaceRoute(new URL("http://localhost" + path)).invalid,
      true,
      path
    )
  }
})

test("builds canonical links with segment encoding and no legacy identifiers", () => {
  const url = new URL(
    "http://localhost/?project=demo-project&document=stable-id&view=reader#secao"
  )
  assert.equal(
    buildWorkspaceLocation(url, "demo-project", "docs/guia de ação/100%.md"),
    "/demo-project/docs/guia%20de%20a%C3%A7%C3%A3o/100%25.md?view=reader#secao"
  )
})

test("builds project and empty workspace addresses", () => {
  const url = new URL(
    "http://localhost/demo-project/docs/guia.md?project=old&document=old"
  )
  assert.equal(buildWorkspaceLocation(url, "demo-project", null), "/demo-project")
  assert.equal(buildWorkspaceLocation(url, null, null), "/")
})

test("round trips paths without confusing encoded query or hash characters", () => {
  const path = "docs/guia + notas/ação & 100%.md"
  const address = buildWorkspaceLocation(
    new URL("http://localhost"),
    "demo-project",
    path
  )
  assert.equal(
    readWorkspaceRoute(new URL(address, "http://localhost")).documentPath,
    path
  )
})
