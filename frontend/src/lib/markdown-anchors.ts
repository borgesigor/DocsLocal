type MarkdownNode = {
  type: string
  value?: string
  children?: MarkdownNode[]
  data?: { hProperties?: Record<string, unknown> }
}

function nodeText(node: MarkdownNode): string {
  return node.value ?? node.children?.map(nodeText).join("") ?? ""
}

export function remarkHeadingAnchors() {
  return (tree: MarkdownNode) => {
    const anchors = new Set<string>()
    function visit(node: MarkdownNode) {
      if (node.type === "heading") {
        const base = nodeText(node)
          .toLowerCase()
          .replace(/[^\p{L}\p{N}\p{M}_\s-]/gu, "")
          .replace(/\s/g, "-")
        let anchor = base
        let suffix = 0
        while (anchors.has(anchor)) anchor = `${base}-${++suffix}`
        anchors.add(anchor)
        node.data = {
          ...node.data,
          hProperties: { ...node.data?.hProperties, id: anchor },
        }
      }
      node.children?.forEach(visit)
    }
    visit(tree)
  }
}
