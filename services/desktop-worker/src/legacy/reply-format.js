'use strict';
const {markdownLink,plainLinks}=require('./links');

// Passive inline-code controls are content; named/focusable editors are not.
function inlineCode(node) {
  const passive = n => [20, 30, 41].includes(n.role) && !(n.state & 0x100000) && (n.children || []).every(passive);
  return node.role === 42 && !node.name && !node.value && !(node.state & 0x100000) &&
    (node.children || []).length > 0 && node.children.every(passive);
}

// QQ's proportional font cannot reliably align a grid. Repeat the column labels
// in each record instead, keeping empty cells so later values never shift left.
function renderTable(rows, hasHeader = true) {
  if (!rows.length) return '';
  const headers = hasHeader ? rows[0] : [];
  const data = hasHeader ? rows.slice(1) : rows;
  if (!data.length) return headers.join(' | ');
  const width = Math.max(headers.length, ...data.map(row => row.length));
  const label = index => (headers[index] || '').trim() || `第${index + 1}列`;
  const value = text => (text || '').trim() || '—';
  return data.map((row, index) => {
    if (width === 1) return `${label(0)}：${value(row[0])}`;
    const title = hasHeader ? `${label(0)}：${value(row[0])}` : `第${index + 1}项`;
    const fields = [];
    for (let column = hasHeader ? 1 : 0; column < width; column++)
      fields.push(`${label(column)}：${value(row[column]).replace(/\n/g, '\n  ')}`);
    return `【${title.replace(/\n/g, ' / ')}】\n${fields.join('\n')}`;
  }).join('\n\n');
}

function descendantsAt(node, roles) {
  const found = [];
  function visit(n) {
    if (roles.includes(n.role)) { found.push(n); return; }
    // A nested table/list owns its own rows/items.
    if (n.role === 24 || n.role === 33) return;
    for (const child of n.children || []) visit(child);
  }
  for (const child of node.children || []) visit(child);
  return found;
}

function renderBody(tokens) {
  if (!tokens.length) return '';
  const paths = tokens.map(t => [...t.parents, t.node]);
  let common = paths[0].length;
  for (const path of paths.slice(1)) {
    let i = 0; while (i < common && i < path.length && path[i] === paths[0][i]) i++;
    common = i;
  }
  // Even a one-cell table or a one-item list still has semantic structure.
  const codeBlock = node => (node.children || []).some(child => child.role === 43 && /^(复制代码|Copy code)$/.test(child.name || ''));
  for (let i = 0; i < common; i++) if ([24, 30, 33, 34].includes(paths[0][i].role) || codeBlock(paths[0][i])) { common = i + 1; break; }
  const selected = new Set(tokens.map(t => t.node)), included = new WeakMap();
  function contains(node) {
    if (!included.has(node)) included.set(node, selected.has(node) || (node.children || []).some(contains));
    return included.get(node);
  }
  function render(node, code = false) {
    if (selected.has(node)) return node.role === 30&&!code ? markdownLink(node.name||'',node.value) : node.role === 34 ? '- ' + node.name : node.name || '';
    if (!contains(node) || node.role === 43 || node.role === 57 || node.role === 42 && !inlineCode(node)) return '';
    if (node.role === 24) {
      const rows = descendantsAt(node, [28]).map(row => descendantsAt(row, [25, 26, 29]));
      const visible = rows.filter(cells => cells.some(contains));
      return renderTable(visible.map(cells => cells.map(cell => render(cell))),
        !!visible[0]?.some(cell => cell.role === 25));
    }
    const children = node.children || [];
    const ownCode = codeBlock(node), isCode = code || ownCode;
    const rendered = children.map(child => ({ node: child, text: render(child, isCode) })).filter(child => child.text !== '');
    if (node.role === 34) {
      let body = '';
      for (const child of rendered) {
        if (child.node.role === 33) body += '\n' + child.text.split('\n').map(line => '  ' + line).join('\n');
        else body += child.text;
      }
      return /^\s*(?:[-*•]|\d+[.)、])\s/u.test(body) ? body : '- ' + body;
    }
    const inline = node.role === 30 || inlineCode(node) || rendered.some(child => selected.has(child.node) || child.node.role === 30 || inlineCode(child.node));
    const separator = node.role === 33 ? '\n' : inline ? '' : isCode ? '\n' : '\n\n';
    const body = rendered.map(child => child.text).join(separator);
    if(node.role===30&&!isCode)return markdownLink(body||node.name||'',node.value);
    if (ownCode && !code) {
      const longest = Math.max(0, ...(body.match(/`+/g) || []).map(run => run.length));
      const fence = '`'.repeat(Math.max(3, longest + 1));
      return `${fence}\n${body}\n${fence}`;
    }
    return body;
  }
  return (common ? render(paths[0][common - 1]) : tokens.map(t => t.text).join('')).trim();
}

function pipeCells(line) {
  line = line.trim();
  let cells = [], cell = '', fence = 0, lastPipe = -1;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '\\' && line[i + 1] === '|') { cell += '|'; i++; continue; }
    if (ch === '`') {
      let end = i; while (line[end] === '`') end++;
      const size = end - i; fence = fence === size ? 0 : fence || size;
      cell += line.slice(i, end); i = end - 1; continue;
    }
    if (ch === '|' && !fence) { cells.push(cell.trim()); cell = ''; lastPipe = i; } else cell += ch;
  }
  cells.push(cell.trim());
  if (line.trimStart().startsWith('|')) cells.shift();
  if (lastPipe === line.length - 1) cells.pop();
  return cells;
}

function splitTableText(text) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n'), out = [];
  const parts = [], flush = () => { const value=out.join('\n').trim();if(value)parts.push({kind:'text',text:value});out.length=0; };
  let fence = null;
  for (let i = 0; i < lines.length; i++) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(lines[i]);
    if (fence) { out.push(lines[i]); if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null; continue; }
    if (marker) { fence = marker[1]; out.push(lines[i]); continue; }
    const headers = pipeCells(lines[i]), delimiters = pipeCells(lines[i + 1] || '');
    if (headers.length < 2 || delimiters.length !== headers.length || !delimiters.every(cell => /^:?-{3,}:?$/.test(cell))) {
      out.push(lines[i]); continue;
    }
    const rows = [headers]; i++;
    while (i + 1 < lines.length && lines[i + 1].trim() && lines[i + 1].includes('|')) {
      const row = pipeCells(lines[i + 1]);
      // Reject a ragged candidate instead of silently assigning the wrong header.
      if (row.length !== headers.length) break;
      rows.push(row.map(cell => cell.replace(/<br\s*\/?\s*>/gi, '\n'))); i++;
    }
    flush();parts.push({kind:'table',rows,hasHeader:true});
  }
  flush();return parts;
}

function formatReplyText(text) {return plainLinks(splitTableText(text).map(part=>part.kind==='table'?renderTable(part.rows,part.hasHeader):part.text).join('\n\n'));}

function tableData(node) {
  const rows=descendantsAt(node,[28]).map(row=>descendantsAt(row,[25,26,29]));
  if(!rows.length)return null;
  const cellText=cell=>{
    const tokens=[];
    function visit(n,parents=[]){
      if(n.role===43||n.role===57||n.role===42&&!inlineCode(n))return;
      if(n.role===41||[25,26,29,30].includes(n.role)&&!(n.children||[]).length){tokens.push({node:n,parents,text:n.name||''});return;}
      for(const child of n.children||[])visit(child,[...parents,n]);
    }
    visit(cell);return renderBody(tokens);
  };
  return {kind:'table',rows:rows.map(cells=>cells.map(cellText)),hasHeader:rows[0].some(cell=>cell.role===25)};
}

module.exports = { inlineCode, renderBody, renderTable, formatReplyText, splitTableText, tableData };
