import assert from "node:assert/strict"
import { test } from "node:test"
import { remarkHeadingAnchors } from "../src/lib/markdown-anchors.ts"

test("section links match numbered Portuguese headings with formatted text", () => {
  const heading = {
    type: "heading",
    data: { hProperties: { id: "" } },
    children: [
      { type: "text", value: "11. Referências " },
      { type: "strong", children: [{ type: "text", value: "técnicas" }] },
    ],
  }
  remarkHeadingAnchors()({ type: "root", children: [heading] })
  assert.equal(heading.data.hProperties.id, "11-referências-técnicas")
})

test("duplicate headings receive distinct anchors and reset for another document", () => {
  const headings = ["Uso", "Uso", "Uso-1", "Uso"].map((value) => ({
    type: "heading",
    data: { hProperties: { id: "" } },
    children: [{ type: "text", value }],
  }))
  remarkHeadingAnchors()({ type: "root", children: headings })
  assert.deepEqual(
    headings.map((h) => h.data.hProperties.id),
    ["uso", "uso-1", "uso-1-1", "uso-2"]
  )
  const other = {
    type: "heading",
    data: { hProperties: { id: "" } },
    children: [{ type: "text", value: "Uso" }],
  }
  remarkHeadingAnchors()({ type: "root", children: [other] })
  assert.equal(other.data.hProperties.id, "uso")
})
