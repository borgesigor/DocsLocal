import assert from "node:assert/strict"
import test from "node:test"
import { extractFrontmatter } from "../src/lib/markdown-frontmatter.ts"

test("separates skill metadata from the Markdown body without changing either", () => {
  const metadata = "name: docslocal\ndescription: Consulte e atualize documentos."
  const content = `---\n${metadata}\n---\n\n# Skill\n\nBody`
  assert.deepEqual(extractFrontmatter(content), { metadata, body: "\n# Skill\n\nBody" })
})

test("supports Windows line endings and multiline YAML text", () => {
  const metadata = "name: docslocal\r\ndescription: |\r\n  Multiple lines\r\n  preserved"
  assert.deepEqual(extractFrontmatter(`---\r\n${metadata}\r\n---\r\n# Skill`), { metadata, body: "# Skill" })
})

test("leaves ordinary Markdown horizontal rules and incomplete headers unchanged", () => {
  for (const content of ["# Heading\n---\nBody", "---\nText\n---\nBody", "---\nname: skill\nBody"]) {
    assert.deepEqual(extractFrontmatter(content), { metadata: null, body: content })
  }
})
