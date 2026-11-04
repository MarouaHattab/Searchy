import { Fragment, type ReactNode } from 'react'

function inline(
  text: string,
  keyPrefix: string,
  onCitationClick?: (num: number) => void
): ReactNode[] {
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
    else if (token.startsWith('[')) {
      const num = parseInt(token.slice(1, -1), 10)
      nodes.push(
        <button
          type="button"
          className="chat-citation interactive"
          key={key}
          onClick={() => onCitationClick?.(num)}
          title={`Open source [${num}]`}
        >
          {token}
        </button>
      )
    } else nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    last = match.index + token.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export function RichText({
  text,
  onCitationClick,
}: {
  text: string
  onCitationClick?: (num: number) => void
}) {
  const lines = text.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let paragraph: string[] = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(
      <p key={`p${blocks.length}`}>
        {inline(paragraph.join(' '), `p${blocks.length}`, onCitationClick)}
      </p>
    )
    paragraph = []
  }
  const flushList = () => {
    if (!list) return
    const Tag = list.ordered ? 'ol' : 'ul'
    blocks.push(
      <Tag key={`l${blocks.length}`}>
        {list.items.map((item, index) => (
          <li key={index}>{inline(item, `l${blocks.length}-${index}`, onCitationClick)}</li>
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
