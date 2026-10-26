export function extractFrontmatter(content: string): {
  metadata: string | null
  body: string
} {
  const header = /^(?:\uFEFF)?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(content)
  if (!header || !/^[A-Za-z_][\w-]*\s*:/m.test(header[1])) {
    return { metadata: null, body: content }
  }
  return { metadata: header[1], body: content.slice(header[0].length) }
}
