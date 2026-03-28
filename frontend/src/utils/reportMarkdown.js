function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function sanitizeUrl(raw) {
  const value = String(raw || '').trim();
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  if (/^mailto:/i.test(value)) return value;
  return '';
}

function parseLink(raw) {
  const matched = raw.match(/^([^\s)]+)(?:\s+"([^"]+)")?$/);
  if (!matched) return { href: '', title: '' };
  return {
    href: sanitizeUrl(matched[1]),
    title: matched[2] ? String(matched[2]) : ''
  };
}

function renderInline(markdownText) {
  let text = String(markdownText || '');
  const codeTokens = [];
  const linkTokens = [];

  text = text.replace(/`([^`\n]+?)`/g, (_matched, code) => {
    const token = `@@CODE-${codeTokens.length}@@`;
    codeTokens.push(`<code>${escapeHtml(code)}</code>`);
    return token;
  });

  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_matched, label, linkRaw) => {
    const link = parseLink(linkRaw);
    const token = `@@LINK-${linkTokens.length}@@`;
    linkTokens.push({
      href: link.href,
      title: link.title,
      label
    });
    return token;
  });

  text = escapeHtml(text);

  text = text.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__([^_]+?)__/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*\n]+?)\*/g, '<em>$1</em>');
  text = text.replace(/_([^_\n]+?)_/g, '<em>$1</em>');
  text = text.replace(/~~([^~\n]+?)~~/g, '<del>$1</del>');

  for (let index = 0; index < linkTokens.length; index += 1) {
    const token = linkTokens[index];
    const safeLabel = escapeHtml(token.label);
    if (!token.href) {
      text = text.replace(`@@LINK-${index}@@`, safeLabel);
      continue;
    }
    const titleAttr = token.title ? ` title="${escapeHtml(token.title)}"` : '';
    text = text.replace(
      `@@LINK-${index}@@`,
      `<a href="${escapeHtml(token.href)}" target="_blank" rel="noreferrer noopener"${titleAttr}>${safeLabel}</a>`
    );
  }

  for (let index = 0; index < codeTokens.length; index += 1) {
    text = text.replace(`@@CODE-${index}@@`, codeTokens[index]);
  }
  return text;
}

function splitTableRow(row) {
  return String(row || '')
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function parseTableAlignments(separatorRow, width) {
  const cells = splitTableRow(separatorRow);
  const alignments = [];
  for (let index = 0; index < width; index += 1) {
    const value = String(cells[index] || '').trim();
    if (/^:-+:$/.test(value)) {
      alignments.push('center');
    } else if (/^-+:$/.test(value)) {
      alignments.push('right');
    } else {
      alignments.push('left');
    }
  }
  return alignments;
}

function isHorizontalRule(line) {
  return /^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line);
}

function isUnorderedListItem(line) {
  return /^\s*[-*+]\s+/.test(line);
}

function isOrderedListItem(line) {
  return /^\s*\d+\.\s+/.test(line);
}

function isHeading(line) {
  return /^\s{0,3}#{1,6}\s+/.test(line);
}

function isQuote(line) {
  return /^\s*>\s?/.test(line);
}

function isFence(line) {
  return /^\s*```/.test(line);
}

function isTableStart(lines, index) {
  const current = String(lines[index] || '');
  const next = String(lines[index + 1] || '');
  if (!current.includes('|')) return false;
  return /^\s*\|?[\s:-|]+\|?\s*$/.test(next);
}

function isBlockStart(lines, index) {
  const line = String(lines[index] || '');
  if (!line.trim()) return true;
  if (isFence(line) || isHeading(line) || isHorizontalRule(line) || isQuote(line)) return true;
  if (isUnorderedListItem(line) || isOrderedListItem(line)) return true;
  if (isTableStart(lines, index)) return true;
  return false;
}

function renderParagraph(lines, startIndex) {
  let index = startIndex;
  const parts = [];
  while (index < lines.length) {
    const line = String(lines[index] || '');
    if (!line.trim()) break;
    if (index !== startIndex && isBlockStart(lines, index)) break;
    parts.push(line.trim());
    index += 1;
  }
  return {
    html: `<p>${renderInline(parts.join(' '))}</p>`,
    nextIndex: index
  };
}

function renderList(lines, startIndex, ordered) {
  const regex = ordered ? /^\s*\d+\.\s+(.*)$/ : /^\s*[-*+]\s+(.*)$/;
  let index = startIndex;
  const items = [];
  while (index < lines.length) {
    const line = String(lines[index] || '');
    const matched = line.match(regex);
    if (!matched) break;

    const itemParts = [matched[1].trim()];
    index += 1;
    while (index < lines.length) {
      const continuation = String(lines[index] || '');
      if (!continuation.trim()) break;
      if (isUnorderedListItem(continuation) || isOrderedListItem(continuation)) break;
      if (isHeading(continuation) || isFence(continuation) || isHorizontalRule(continuation)) break;
      if (isQuote(continuation) || isTableStart(lines, index)) break;
      itemParts.push(continuation.trim());
      index += 1;
    }
    items.push(`<li>${renderInline(itemParts.join(' '))}</li>`);
  }

  const tag = ordered ? 'ol' : 'ul';
  return {
    html: `<${tag}>${items.join('')}</${tag}>`,
    nextIndex: index
  };
}

function renderQuote(lines, startIndex) {
  let index = startIndex;
  const quoteLines = [];
  while (index < lines.length) {
    const line = String(lines[index] || '');
    if (!isQuote(line)) break;
    quoteLines.push(line.replace(/^\s*>\s?/, '').trim());
    index += 1;
  }

  const body = quoteLines
    .filter((line) => Boolean(line))
    .map((line) => `<p>${renderInline(line)}</p>`)
    .join('');

  return {
    html: `<blockquote>${body}</blockquote>`,
    nextIndex: index
  };
}

function renderTable(lines, startIndex) {
  const headerCells = splitTableRow(lines[startIndex]);
  const alignments = parseTableAlignments(lines[startIndex + 1], headerCells.length);
  let index = startIndex + 2;
  const bodyRows = [];

  while (index < lines.length) {
    const line = String(lines[index] || '');
    if (!line.trim() || !line.includes('|')) break;
    if (isFence(line) || isHeading(line) || isHorizontalRule(line) || isQuote(line)) break;
    if (isUnorderedListItem(line) || isOrderedListItem(line)) break;
    const cells = splitTableRow(line);
    const rowHtml = headerCells.map((_cell, columnIndex) => {
      const align = alignments[columnIndex] || 'left';
      const content = renderInline(cells[columnIndex] || '');
      return `<td style="text-align:${align}">${content}</td>`;
    }).join('');
    bodyRows.push(`<tr>${rowHtml}</tr>`);
    index += 1;
  }

  const headHtml = headerCells.map((cell, columnIndex) => {
    const align = alignments[columnIndex] || 'left';
    return `<th style="text-align:${align}">${renderInline(cell)}</th>`;
  }).join('');

  return {
    html: [
      '<div class="report-md-table-wrap">',
      '<table>',
      `<thead><tr>${headHtml}</tr></thead>`,
      `<tbody>${bodyRows.join('')}</tbody>`,
      '</table>',
      '</div>'
    ].join(''),
    nextIndex: index
  };
}

function renderFenceCode(lines, startIndex) {
  const opening = String(lines[startIndex] || '').trim();
  const languageMatched = opening.match(/^```([A-Za-z0-9_-]+)?\s*$/);
  const language = String(languageMatched?.[1] || '').trim().toLowerCase();
  let index = startIndex + 1;
  const blockLines = [];

  while (index < lines.length) {
    const line = String(lines[index] || '');
    if (/^\s*```/.test(line)) {
      index += 1;
      break;
    }
    blockLines.push(line);
    index += 1;
  }

  const languageClass = language ? ` class="language-${escapeHtml(language)}"` : '';
  return {
    html: `<pre><code${languageClass}>${escapeHtml(blockLines.join('\n'))}</code></pre>`,
    nextIndex: index
  };
}

export function renderReportMarkdown(markdown) {
  const source = String(markdown || '').replace(/\r\n?/g, '\n').trim();
  if (!source) return '';

  const lines = source.split('\n');
  const chunks = [];
  let index = 0;

  while (index < lines.length) {
    const line = String(lines[index] || '');
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (isFence(line)) {
      const rendered = renderFenceCode(lines, index);
      chunks.push(rendered.html);
      index = rendered.nextIndex;
      continue;
    }

    const headingMatched = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
    if (headingMatched) {
      const level = headingMatched[1].length;
      chunks.push(`<h${level}>${renderInline(headingMatched[2].trim())}</h${level}>`);
      index += 1;
      continue;
    }

    if (isHorizontalRule(line)) {
      chunks.push('<hr />');
      index += 1;
      continue;
    }

    if (isQuote(line)) {
      const rendered = renderQuote(lines, index);
      chunks.push(rendered.html);
      index = rendered.nextIndex;
      continue;
    }

    if (isTableStart(lines, index)) {
      const rendered = renderTable(lines, index);
      chunks.push(rendered.html);
      index = rendered.nextIndex;
      continue;
    }

    if (isUnorderedListItem(line)) {
      const rendered = renderList(lines, index, false);
      chunks.push(rendered.html);
      index = rendered.nextIndex;
      continue;
    }

    if (isOrderedListItem(line)) {
      const rendered = renderList(lines, index, true);
      chunks.push(rendered.html);
      index = rendered.nextIndex;
      continue;
    }

    const rendered = renderParagraph(lines, index);
    chunks.push(rendered.html);
    index = rendered.nextIndex;
  }

  return chunks.join('');
}

export function toReportHeadline(markdown) {
  const source = String(markdown || '').replace(/\r\n?/g, '\n');
  if (!source.trim()) return '';
  const firstLine = source.split('\n').find((line) => String(line || '').trim()) || '';
  const stripped = String(firstLine)
    .trim()
    .replace(/^#{1,6}\s+/, '')
    .replace(/^>\s+/, '')
    .replace(/^\d+\.\s+/, '')
    .replace(/^[-*+]\s+/, '')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .trim();
  return stripped;
}
