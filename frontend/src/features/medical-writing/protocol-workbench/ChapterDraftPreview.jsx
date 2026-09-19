import { useEffect, useId, useRef, useState } from 'react';
import './kangzheProtocol.css';
import './ChapterDraftPreview.css';

function orderedGrid(table) {
  const columns=[...table.columns].sort((a,b)=>a.order-b.order);
  const rows=[...table.rows].sort((a,b)=>a.order-b.order);
  const indices=new Map(columns.map((column,index)=>[column.column_id,index]));
  const occupied=rows.map(()=>Array(columns.length).fill(false));
  return rows.map((row,rowIndex)=>{
    const cells=[...row.cells].sort((a,b)=>indices.get(a.column_id)-indices.get(b.column_id));
    for(const cell of cells) {
      const start=indices.get(cell.column_id);
      const height=cell.row_span ?? 1, width=cell.column_span ?? 1;
      if(!Number.isInteger(start)||!Number.isInteger(height)||!Number.isInteger(width)
        ||height<1||width<1||rowIndex+height>rows.length||start+width>columns.length) throw new Error('grid');
      for(let r=rowIndex;r<rowIndex+height;r++)for(let c=start;c<start+width;c++) {
        if(occupied[r][c])throw new Error('overlap');
        occupied[r][c]=true;
      }
    }
    // Do not silently move cells into absent columns or invent their contents.
    if(occupied[rowIndex].some(value=>!value))throw new Error('incomplete');
    return {...row,cells};
  });
}

function DraftTable({ table }) {
  const prefix=useId();
  let rows;
  try { rows=orderedGrid(table); }
  catch { return <p role="alert">{table.title || '本节表格'}：表格布局需要核对，原内容已保留。</p>; }
  const notes=new Map((table.notes || []).map(note=>[note.note_id,note]));
  const noteId=note=>`${prefix}-note-${encodeURIComponent(note.note_id)}`;
  return <>
    <div className="pcd-table-scroll" role="region" aria-label={table.title || '章节表格'} tabIndex={0}>
      <table>
        {table.title && <caption>{table.title}</caption>}
        <tbody>{rows.map((row,index)=><tr key={row.row_id}>
          {row.cells.map(cell=>{
            const Tag=index<table.header_row_count||row.style_role==='header'||cell.style_role==='header'?'th':'td';
            return <Tag key={cell.cell_id} rowSpan={cell.row_span || 1} colSpan={cell.column_span || 1}>
              {cell.text}
              {(cell.note_refs || []).map(ref=>{
                const note=notes.get(ref);
                return note && <sup key={ref}><a href={`#${noteId(note)}`} aria-label={`查看注 ${note.marker || '说明'}`}>{note.marker || '注'}</a></sup>;
              })}
            </Tag>;
          })}
        </tr>)}</tbody>
      </table>
    </div>
    {(table.notes || []).length>0 && <div className="pcd-notes" aria-label="表格附注">
      {table.notes.map(note=><p key={note.note_id} id={noteId(note)}>
        {note.marker && <span className="pcd-note-marker">{note.marker}</span>}<span>{note.text}</span>
      </p>)}
    </div>}
  </>;
}

function ParagraphEditor({ initialText, composingRef, busy, onSave, onCancel, onDraft }) {
  const [text, setText] = useState(initialText);
  return <div className="pcd-edit-shell">
    <textarea className="pcd-edit-area" aria-label="编辑段落内容" value={text} disabled={busy}
      onCompositionStart={() => { composingRef.current = true; }}
      onCompositionEnd={() => { composingRef.current = false; }}
      onChange={event => {
        // Version-bound keystroke buffer (B07): unsubmitted typing survives
        // refresh, chapter switches and save failures, IME composition included.
        setText(event.target.value);
        onDraft?.(event.target.value);
      }}/>
    <div className="pcd-edit-actions">
      <button type="button" className="pcd-edit-save" disabled={busy}
        onClick={() => { if (!composingRef.current) onSave(text); }}>保存修改</button>
      <button type="button" disabled={busy} onClick={onCancel}>取消</button>
      <small>修改会保存为新版本；涉及研究事实的内容会在显式核对中提示，研究事实本身保持不变。</small>
    </div>
  </div>;
}

export function ChapterDraftPreview({ title, candidate, saved = false, edit = null }) {
  // edit = { busy, composingRef, onSave(blockId, newText), editingBlockId,
  //          onStartEdit(blockId), onCancelEdit, localDrafts } — absent = read-only.
  const editable = Boolean(edit);
  return <article className="kz-protocol kz-chapter-preview pcd-preview" aria-label={`${title}章节初稿`}>
    <header><span className="pcd-status">{saved ? "已保存工作初稿" : "章节初稿"}</span><h2>{title}</h2><p>{saved ? "当前文档中的正文，尚待医学核对" : "尚未合并到完整方案"}</p></header>
    {candidate.blocks.map(block=><div key={block.block_id} data-draft-block={block.block_id}>
      {block.kind==='paragraph' ? (
        editable && edit.editingBlockId === block.block_id ? (
          <ParagraphEditor initialText={edit.localDrafts?.[block.block_id] ?? block.text}
            composingRef={edit.composingRef} busy={edit.busy}
            onSave={text => edit.onSave(block.block_id, text)}
            onDraft={text => edit.onDraft?.(block.block_id, text)}
            onCancel={edit.onCancelEdit}/>
        ) : <p className="pcd-paragraph">
          {editable ? <button type="button" className="pcd-edit-link"
            disabled={edit.busy}
            onClick={() => edit.onStartEdit(block.block_id)}
            aria-label={`编辑本段：${block.text.slice(0, 20)}…`}>编辑</button> : null}
          {edit?.localDrafts?.[block.block_id] ?? block.text}
        </p>
      ) : block.kind==='table' ? <DraftTable table={block.table}/>
        : <p role="alert">本段内容需要核对，原记录已保留。</p>}
    </div>)}
  </article>;
}
