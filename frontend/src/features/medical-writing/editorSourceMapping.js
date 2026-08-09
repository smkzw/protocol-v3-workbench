function editorNodeSourceBlockId(node) {
  return String(node?.attrs?.sourceBlockId || "").trim();
}

export function groupEditorNodesBySourceBlockId(
  contentBlocks,
  editorNodes,
  { isEffectivelyEmptyNode = () => false } = {},
) {
  const blocks = Array.isArray(contentBlocks) ? contentBlocks : [];
  const nodes = Array.isArray(editorNodes) ? editorNodes : [];
  const canonicalIds = blocks.map((block) => String(block?.block_id || "").trim());
  if (canonicalIds.some((blockId) => !blockId)) {
    return { error: "来源内容存在缺失的 block_id，不能安全映射编辑内容。", groups: [] };
  }
  if (new Set(canonicalIds).size !== canonicalIds.length) {
    return { error: "来源内容存在重复的 block_id，不能安全映射编辑内容。", groups: [] };
  }

  const blockById = new Map(blocks.map((block) => [String(block.block_id), block]));
  const groupsById = new Map(canonicalIds.map((blockId) => [
    blockId,
    {
      blockId,
      node: null,
      leadingNodes: [],
      trailingNodes: [],
    },
  ]));
  const boundIds = [];
  let activeSourceId = "";
  let pendingHeadingBody = null;

  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    const sourceBlockId = editorNodeSourceBlockId(node);
    if (sourceBlockId) {
      if (!blockById.has(sourceBlockId)) {
        return {
          error: `编辑器包含未知来源块 ${sourceBlockId}，系统已阻止保存。`,
          groups: [],
        };
      }
      const group = groupsById.get(sourceBlockId);
      const sourceBlock = blockById.get(sourceBlockId);
      if (pendingHeadingBody) {
        if (sourceBlock?.block_type !== "paragraph") {
          return {
            error: `标题后的新增正文无法绑定到相邻正文来源块 ${sourceBlockId}，系统已阻止保存。`,
            groups: [],
          };
        }
        group.leadingNodes.push(...pendingHeadingBody.nodes);
        pendingHeadingBody = null;
      }
      if (group.node) {
        return {
          error: `编辑器重复出现来源块 ${sourceBlockId}，系统已阻止保存。`,
          groups: [],
        };
      }
      const expectedId = canonicalIds[boundIds.length];
      if (sourceBlockId !== expectedId) {
        return {
          error: `来源块顺序发生变化：期望 ${expectedId || "文档结束"}，实际为 ${sourceBlockId}。`,
          groups: [],
        };
      }
      if (sourceBlock?.block_type === "heading" && node.type === "sourceBlock") {
        const content = Array.isArray(node.content) ? node.content : [];
        const [headingNode, ...overflowNodes] = content;
        if (headingNode?.type !== "heading") {
          return {
            error: `标题来源块 ${sourceBlockId} 已失去标题语义，系统已阻止保存。`,
            groups: [],
          };
        }
        const meaningfulOverflow = overflowNodes.filter((candidate) => (
          !isEffectivelyEmptyNode(candidate)
        ));
        if (meaningfulOverflow.some((candidate) => candidate?.type !== "paragraph")) {
          return {
            error: `标题来源块 ${sourceBlockId} 包含无法安全绑定的新增标题或结构节点，系统已阻止保存。`,
            groups: [],
          };
        }
        group.node = { ...node, content: [headingNode] };
        if (meaningfulOverflow.length) {
          pendingHeadingBody = {
            sourceBlockId,
            nodes: meaningfulOverflow,
          };
        }
      } else {
        group.node = node;
      }
      boundIds.push(sourceBlockId);
      activeSourceId = sourceBlockId;
      continue;
    }

    const isTrailingEmpty = index === nodes.length - 1 && isEffectivelyEmptyNode(node);
    if (isTrailingEmpty) continue;
    if (!["paragraph", "heading"].includes(String(node?.type || ""))) {
      return {
        error: `编辑器包含无法绑定来源的 ${node?.type || "unknown"} 节点，系统已阻止保存。`,
        groups: [],
      };
    }
    if (!activeSourceId) {
      return {
        error: "文档开头出现无法定位来源的新增段落，系统已阻止保存。",
        groups: [],
      };
    }
    const activeBlock = blockById.get(activeSourceId);
    if (pendingHeadingBody || activeBlock?.block_type === "heading") {
      if (node?.type !== "paragraph") {
        return {
          error: `标题后的新增内容包含无法安全绑定的 ${node?.type || "unknown"} 节点，系统已阻止保存。`,
          groups: [],
        };
      }
      if (!pendingHeadingBody) {
        pendingHeadingBody = {
          sourceBlockId: activeSourceId,
          nodes: [],
        };
      }
      pendingHeadingBody.nodes.push(node);
      continue;
    }
    if (["table", "figure"].includes(activeBlock?.block_type)) {
      return {
        error: `新增段落紧邻${activeBlock.block_type === "table" ? "表格" : "图片"}来源块 ${activeSourceId}，无法确定正文来源。`,
        groups: [],
      };
    }
    groupsById.get(activeSourceId).trailingNodes.push(node);
  }

  if (pendingHeadingBody) {
    return {
      error: `标题后的新增正文没有相邻正文来源块可供绑定（标题来源块 ${pendingHeadingBody.sourceBlockId}），系统已阻止保存。`,
      groups: [],
    };
  }
  const missingIds = canonicalIds.filter((blockId) => !groupsById.get(blockId).node);
  if (missingIds.length) {
    return {
      error: `编辑器缺少来源块 ${missingIds.slice(0, 3).join("、")}${missingIds.length > 3 ? "等" : ""}，系统已阻止保存。`,
      groups: [],
    };
  }
  return {
    error: "",
    groups: canonicalIds.map((blockId) => groupsById.get(blockId)),
    boundSourceBlockIds: boundIds,
  };
}
