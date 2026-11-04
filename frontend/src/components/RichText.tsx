import { Fragment, type ReactNode } from 'react'

/**
 * Renders the small Markdown subset a local model actually emits: bold, italics,
 * inline code, bullet and numbered lists, and paragraph breaks. A full Markdown
 * library would be a large dependency for that, and untrusted model output is
 * safer rendered as text nodes than as HTML.
 */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`|\[\d+\])/g
  let last = 0
  let match: RegExpExecArray | null
  let index = 0
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-${index++}`
    if (token.startsWith('**'))
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    else if (token.startsWith('`'))
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>)
    else if (token.startsWith('['))
      nodes.push(
        <span className="chat-citation" key={key}>
          {token}
        </span>
      )
    else nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    last = match.index + token.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export function RichText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let paragraph: string[] = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(<p key={`p${blocks.length}`}>{inline(paragraph.join(' '), `p${blocks.length}`)}</p>)
    paragraph = []
  }
  const flushList = () => {
    if (!list) return
    const Tag = list.ordered ? 'ol' : 'ul'
    blocks.push(
      <Tag key={`l${blocks.length}`}>
        {list.items.map((item, index) => (
          <li key={index}>{inline(item, `l${blocks.length}-${index}`)}</li>
        ))}
      </Tag>
    )
    list = null
  }

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) {
      flushParagraph()
      flushList()
      continue
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line)
    if (bullet || numbered) {
      flushParagraph()
      const ordered = !!numbered
      if (!list || list.ordered !== ordered) {
        flushList()
        list = { ordered, items: [] }
      }
      list.items.push((bullet ?? numbered)![1])
      continue
    }
    if (list) flushList()
    paragraph.push(line)
  }
  flushParagraph()
  flushList()

  return <Fragment>{blocks}</Fragment>
}
