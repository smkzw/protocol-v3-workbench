import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, it, expect } from 'vitest';
import { ChapterDraftPreview } from './ChapterDraftPreview';
afterEach(cleanup);

import { chapterFixture } from '../../../../tests/fixtures/chapter-preview-fixture.mjs';

it('reads ordered paragraphs, merged cells and actual note markers without source or approval labels',()=>{
  const candidate=chapterFixture();const before=JSON.stringify(candidate);
  const {container}=render(<ChapterDraftPreview title='研究程序' candidate={candidate}/>);
  const blocks=[...container.querySelectorAll('[data-draft-block]')];
  expect(blocks.map(b=>b.dataset.draftBlock)).toEqual(['before','block:table','after']);
  expect(screen.getByText('安全性评估').getAttribute('rowspan')).toBe('2');
  expect(screen.getByText('研究访视').getAttribute('colspan')).toBe('2');
  expect(screen.getByText('0 mg')).toBeTruthy();
  expect(screen.getByRole('link',{name:'查看注 a'}).getAttribute('href')).toContain('note');
  expect(screen.getByText('给药前完成相关检查。')).toBeTruthy();
  expect(screen.queryByText(/原始来源只读|已批准|已采用|完整方案已完成/)).toBeNull();
  expect(JSON.stringify(candidate)).toBe(before);
});

it('reports overlapping grid instead of silently shifting a medical cell',()=>{
  const candidate=chapterFixture();
  candidate.blocks[1].table.rows[2].cells[0].column_id='activity';
  render(<ChapterDraftPreview title='研究程序' candidate={candidate}/>);
  expect(screen.getByRole('alert').textContent).toContain('表格布局需要核对');
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.getByText('表后段落不得提前。')).toBeTruthy();
});

it('keeps every note even when it is attached to the table rather than a cell',()=>{
  const candidate=chapterFixture();
  candidate.blocks[1].table.notes.push({note_id:'note:whole',marker:'',text:'整表说明不得丢失。'});
  render(<ChapterDraftPreview title='研究程序' candidate={candidate}/>);
  expect(screen.getByText('整表说明不得丢失。')).toBeTruthy();
});
