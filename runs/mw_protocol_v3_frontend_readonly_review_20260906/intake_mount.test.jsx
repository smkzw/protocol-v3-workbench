import React, { StrictMode } from '../../frontend/node_modules/react/index.js';
import { afterEach, expect, it, vi } from '../../frontend/node_modules/vitest/dist/index.js';
import { cleanup, fireEvent, render, screen, waitFor } from '../../frontend/node_modules/@testing-library/react/dist/index.js';
import { webcrypto } from 'node:crypto';
import { MedicalWritingSynopsisProjectIntake } from '../../frontend/src/features/medical-writing/MedicalWritingSynopsisProjectIntake.jsx';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

for (const strict of [false, true]) {
  it(`successful upload reaches review, StrictMode=${strict}`, async () => {
    const request = vi.fn(async (url) => ({
      ok: true,
      json: async () => url.endsWith('/result') ? {
        source: { source_id: 'test-source', original_filename: 'test.docx' },
        proposed_framing: { investigational_product: 'test', indication: 'test', study_phase: 'II期' },
        proposed_picos: {}, proposed_synopsis_text: 'test-only synopsis',
      } : { intake_id: 'test-intake', idempotency_key: 'test-key', status: 'review_ready' },
    }));
    vi.stubGlobal('fetch', request);
    vi.stubGlobal('crypto', webcrypto);
    const component = <MedicalWritingSynopsisProjectIntake />;
    const { container } = render(strict ? <StrictMode>{component}</StrictMode> : component);
    const file = new File(['test'], 'test.docx');
    file.arrayBuffer = async () => new Uint8Array([116, 101, 115, 116]).buffer;
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: /导入并提取/ }));
    await waitFor(() => expect(screen.queryByText('AI 已提取 · 一次确认')).not.toBeNull());
    expect(request).toHaveBeenCalledTimes(2);
  });
}
