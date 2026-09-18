import React from "react";
import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {ProtocolIntakeWorkspace} from "../src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.jsx";

afterEach(()=>{cleanup(); localStorage.clear();});
it("keeps an explicitly excluded source excluded after reopening the project",async()=>{
  const source={source:{source_artifact_id:"source-reference",logical_source_key:"reference.docx",source_role:"peer_reviewed",source_version:"unidentified",jurisdiction:"unspecified",content_sha256:"a".repeat(64)},storage_key:"reference",storage_revision:1};
  const api={listSources:vi.fn(async()=>({sources:[source]})),sourceDownloadUrl:()=>"/fixture.docx"};
  const view=render(<ProtocolIntakeWorkspace projectId="selection-recovery" api={api}/>);
  const checkbox=await screen.findByRole("checkbox",{name:"纳入后续写作：reference.docx"});
  fireEvent.click(checkbox); expect(checkbox.checked).toBe(false);
  view.unmount(); render(<ProtocolIntakeWorkspace projectId="selection-recovery" api={api}/>);
  expect((await screen.findByRole("checkbox",{name:"纳入后续写作：reference.docx"})).checked).toBe(false);
});
