// Synthetic display material; no research adoption or model execution.
export function chapterFixture() {
  const table={table_id:'table:one',block_id:'block:table',title:'访视安排',header_row_count:1,
    columns:[{column_id:'activity',order:0},{column_id:'week0',order:1},{column_id:'week4',order:2}],
    rows:[
      {row_id:'header',order:0,cells:[{cell_id:'h1',column_id:'activity',text:'项目',row_span:1,column_span:1},
        {cell_id:'h2',column_id:'week0',text:'研究访视',row_span:1,column_span:2}]},
      {row_id:'body1',order:1,cells:[{cell_id:'a',column_id:'activity',text:'安全性评估',row_span:2,column_span:1},
        {cell_id:'b',column_id:'week0',text:'筛选期',row_span:1,column_span:1,note_refs:['note:a']},
        {cell_id:'c',column_id:'week4',text:'第4周',row_span:1,column_span:1}]},
      {row_id:'body2',order:2,cells:[{cell_id:'d',column_id:'week0',text:'0 mg',row_span:1,column_span:1},
        {cell_id:'e',column_id:'week4',text:'按方案执行',row_span:1,column_span:1}]},
    ],notes:[{note_id:'note:a',marker:'a',text:'给药前完成相关检查。'}]};
  return {node_id:'node:one',chapter_contract_id:'contract:one',blocks:[
    {kind:'paragraph',block_id:'before',text:'首段保留原文。\n第二行仍保留。'},
    {kind:'table',block_id:'block:table',table},
    {kind:'paragraph',block_id:'after',text:'表后段落不得提前。'},
  ]};
}
