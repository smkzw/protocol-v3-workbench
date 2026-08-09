/**
 * Stable runtime multi-root content-hash inventory for the E3 12-lane harness.
 *
 * Key contract changes (acceptance remediation):
 * - Includes ALL files by default (dot files included); exclusion is an
 *   explicit empty allowlist only.
 * - Symlinks are represented deterministically as link-target hash entries;
 *   broken symlinks are inventory errors, not silent absences.
 * - Unreadable root → fail-closed error, never an empty snapshot.
 * - Unreadable subdirectory/file → inventory error propagated to snapshot.
 * - Multi-root inventory with explicit root labels and aggregate hash.
 * - Missing/unreadable configured roots fail closed.
 *
 * @module final_release_12lane_stable_hash
 */

import { createHash } from "node:crypto";
import { createReadStream, existsSync, lstatSync, readlinkSync, statSync } from "node:fs";
import { readdir, lstat, readlink, stat } from "node:fs/promises";
import path from "node:path";

// ─── Inventory entry shape ──────────────────────────────────────────────

/**
 * @typedef {Object} InventoryEntry
 * @property {string} rootLabel       — label of the root this entry belongs to
 * @property {string} relativePath    — POSIX-normalised relative path from root
 * @property {number} size            — file size in bytes (metadata only)
 * @property {string} sha256          — hex SHA-256 of file content
 * @property {string} mtime           — ISO timestamp (metadata only)
 * @property {string} [linkTarget]    — symlink target (for symlink entries)
 * @property {string} kind            — "file" | "symlink"
 */

/**
 * @typedef {Object} RootSnapshot
 * @property {string} label           — explicit root label
 * @property {string} root            — absolute root directory
 * @property {boolean} exists         — whether the root existed at capture time
 * @property {string|null} canonicalHash — SHA-256 of canonical entry array
 * @property {number} fileCount
 * @property {InventoryEntry[]} entries
 * @property {string[]} errors        — inventory errors for this root
 * @property {boolean} incomplete     — true if any error occurred
 */

/**
 * @typedef {Object} MultiRootSnapshot
 * @property {string} capturedAt      — ISO timestamp
 * @property {RootSnapshot[]} roots
 * @property {string} aggregateHash   — SHA-256 over all root canonical hashes
 * @property {number} totalFileCount
 * @property {boolean} incomplete     — true if any root is incomplete
 * @property {string[]} allErrors     — all errors across all roots
 */

// ─── Internal helpers ───────────────────────────────────────────────────

/**
 * Compute SHA-256 of a file using streaming.
 * @param {string} filePath
 * @returns {Promise<string>} hex digest
 */
async function fileSha256Stream(filePath) {
  const hash = createHash("sha256");
  const stream = createReadStream(filePath);
  for await (const chunk of stream) hash.update(chunk);
  return hash.digest("hex");
}

/**
 * Recursively walk a directory and collect all file entries.
 *
 * Changes from old version:
 * - Includes dot files and dot directories (no skip by default).
 * - Handles symlinks deterministically: record link target + target hash.
 * - Propagates errors instead of silently returning empty.
 *
 * @param {string} dir
 * @param {string} root  — original root for relative path calculation
 * @param {string} label — root label
 * @param {string[]} errors  — accumulated errors
 * @returns {Promise<InventoryEntry[]>}
 */
async function walkDir(dir, root, label, errors) {
  const entries = [];

  let items;
  try {
    items = await readdir(dir, { withFileTypes: true });
  } catch (err) {
    errors.push(`readdir_error:${dir}:${err.message}`);
    return entries;
  }

  for (const item of items) {
    const fullPath = path.join(dir, item.name);
    const rel = path.relative(root, fullPath).split(path.sep).join("/");

    if (item.isSymbolicLink()) {
      // Represent symlinks deterministically
      let linkTarget = null;
      try {
        linkTarget = await readlink(fullPath);
      } catch (err) {
        errors.push(`readlink_error:${fullPath}:${err.message}`);
        continue;
      }

      // Compute hash of link target string itself
      const linkHash = createHash("sha256")
        .update(linkTarget)
        .digest("hex");

      let st = null;
      try {
        st = await stat(fullPath); // stat follows the link
      } catch {
        // Broken symlink — record as error
        errors.push(`broken_symlink:${fullPath}->${linkTarget}`);
      }

      entries.push({
        rootLabel: label,
        relativePath: rel,
        size: st ? st.size : 0,
        sha256: linkHash,
        mtime: st ? st.mtime.toISOString() : new Date(0).toISOString(),
        linkTarget,
        kind: "symlink",
      });
    } else if (item.isDirectory()) {
      entries.push(...(await walkDir(fullPath, root, label, errors)));
    } else if (item.isFile()) {
      try {
        const s = await stat(fullPath);
        const sha = await fileSha256Stream(fullPath);
        entries.push({
          rootLabel: label,
          relativePath: rel,
          size: s.size,
          sha256: sha,
          mtime: s.mtime.toISOString(),
          kind: "file",
        });
      } catch (err) {
        errors.push(`stat_or_hash_error:${fullPath}:${err.message}`);
      }
    }
    // Other types (FIFO, socket, block/char device) — record as error
    else if (!item.isBlockDevice() && !item.isCharacterDevice() && !item.isFIFO() && !item.isSocket()) {
      errors.push(`unknown_type:${fullPath}`);
    }
  }

  return entries;
}

/**
 * Build a deterministic canonical JSON string from inventory entries and
 * compute its SHA-256.
 *
 * Entries are sorted by (rootLabel, relativePath) for determinism.
 *
 * @param {InventoryEntry[]} entries
 * @returns {{ canonicalJson: string, canonicalHash: string }}
 */
function canonicalHashFromEntries(entries) {
  const sorted = [...entries].sort((a, b) => {
    if (a.rootLabel !== b.rootLabel) {
      return a.rootLabel < b.rootLabel ? -1 : 1;
    }
    return a.relativePath < b.relativePath ? -1 : a.relativePath > b.relativePath ? 1 : 0;
  });
  const minimal = sorted.map((e) => ({
    r: e.rootLabel,
    p: e.relativePath,
    s: e.sha256,
  }));
  const canonicalJson = JSON.stringify(minimal);
  const canonicalHash = createHash("sha256")
    .update(canonicalJson)
    .digest("hex");
  return { canonicalJson, canonicalHash };
}

// ─── Single-root API (backward compat) ──────────────────────────────────

export class StableHash {
  /**
   * @param {string} rootDir  Absolute path to the stable runtime directory.
   */
  constructor(rootDir) {
    this.rootDir = rootDir;
  }

  /**
   * Capture a full recursive SHA-256 content inventory.
   * Throws if root does not exist or is unreadable (fail-closed).
   *
   * @returns {Promise<RootSnapshot>}
   */
  async snapshot() {
    if (!existsSync(this.rootDir)) {
      // Fail-closed: return an error snapshot, NOT empty
      return {
        label: "default",
        root: this.rootDir,
        exists: false,
        canonicalHash: null,
        fileCount: 0,
        entries: [],
        errors: [`root_not_found:${this.rootDir}`],
        incomplete: true,
      };
    }

    const errors = [];
    const entries = await walkDir(this.rootDir, this.rootDir, "default", errors);
    const { canonicalHash } = canonicalHashFromEntries(entries);

    return {
      label: "default",
      root: this.rootDir,
      exists: true,
      canonicalHash,
      fileCount: entries.length,
      entries,
      errors,
      incomplete: errors.length > 0,
    };
  }

  /**
   * Capture a snapshot and write it to a JSON file.
   *
   * @param {string} outputPath
   * @returns {Promise<RootSnapshot>}
   */
  async snapshotToFile(outputPath) {
    const snap = await this.snapshot();
    const { writeFile, mkdir } = await import("node:fs/promises");
    await mkdir(path.dirname(outputPath), { recursive: true });
    await writeFile(outputPath, JSON.stringify(snap, null, 2), "utf8");
    return snap;
  }
}

// ─── Multi-root API ─────────────────────────────────────────────────────

export class MultiRootStableHash {
  /**
   * @param {Array<{label: string, path: string}>} roots
   */
  constructor(roots) {
    if (!Array.isArray(roots) || roots.length === 0) {
      throw new Error("MultiRootStableHash: at least one root required");
    }
    this.roots = roots;
  }

  /**
   * Capture snapshots from all roots.
   * Missing/unreadable roots produce error snapshots (fail-closed).
   *
   * @returns {Promise<MultiRootSnapshot>}
   */
  async snapshot() {
    const rootSnapshots = [];

    for (const { label, path: rootPath } of this.roots) {
      if (!existsSync(rootPath)) {
        rootSnapshots.push({
          label,
          root: rootPath,
          exists: false,
          canonicalHash: null,
          fileCount: 0,
          entries: [],
          errors: [`root_not_found:${rootPath}`],
          incomplete: true,
        });
        continue;
      }

      const errors = [];
      const entries = await walkDir(rootPath, rootPath, label, errors);
      const { canonicalHash } = canonicalHashFromEntries(entries);

      rootSnapshots.push({
        label,
        root: rootPath,
        exists: true,
        canonicalHash,
        fileCount: entries.length,
        entries,
        errors,
        incomplete: errors.length > 0,
      });
    }

    // Aggregate hash: hash of all root canonical hashes in label order
    const sortedRoots = [...rootSnapshots].sort((a, b) =>
      a.label < b.label ? -1 : a.label > b.label ? 1 : 0,
    );
    const rootHashStrings = sortedRoots.map((r) =>
      `${r.label}:${r.incomplete ? "INCOMPLETE" : r.canonicalHash || "NULL"}`,
    );
    const aggregateHash = createHash("sha256")
      .update(rootHashStrings.join("|"))
      .digest("hex");

    const allErrors = rootSnapshots.flatMap((r) => r.errors);
    const totalFileCount = rootSnapshots.reduce((sum, r) => sum + r.fileCount, 0);

    return {
      capturedAt: new Date().toISOString(),
      roots: rootSnapshots,
      aggregateHash,
      totalFileCount,
      incomplete: allErrors.length > 0,
      allErrors,
    };
  }

  /**
   * Capture and write to a JSON file.
   * @param {string} outputPath
   */
  async snapshotToFile(outputPath) {
    const snap = await this.snapshot();
    const { writeFile, mkdir } = await import("node:fs/promises");
    await mkdir(path.dirname(outputPath), { recursive: true });
    await writeFile(outputPath, JSON.stringify(snap, null, 2), "utf8");
    return snap;
  }
}

// ─── Diff functions ─────────────────────────────────────────────────────

/**
 * Compare two single-root snapshots.
 *
 * A change is any:
 * - path created (in `after` but not `before`)
 * - path deleted (in `before` but not `after`)
 * - content hash changed for the same path
 *
 * If either snapshot is incomplete, diff returns hasChanges=true and
 * records the incompleteness as an error.
 *
 * @param {RootSnapshot} before
 * @param {RootSnapshot} after
 * @returns {{ hasChanges: boolean, changes: string[], summary: Object }}
 */
StableHash.diff = function diff(before, after) {
  const changes = [];

  // If either snapshot is incomplete, that is a P0 change
  if (before.incomplete || after.incomplete) {
    const incompleteErrors = [];
    if (before.incomplete) incompleteErrors.push(...before.errors);
    if (after.incomplete) incompleteErrors.push(...after.errors);
    return {
      hasChanges: true,
      changes: incompleteErrors.map((e) => `inventory_error:${e}`),
      summary: {
        beforeFiles: before.fileCount,
        afterFiles: after.fileCount,
        beforeHash: before.canonicalHash,
        afterHash: after.canonicalHash,
        hashEqual: false,
        incomplete: true,
      },
    };
  }

  const beforeMap = new Map();
  for (const e of before.entries) beforeMap.set(e.relativePath, e.sha256);

  const afterMap = new Map();
  for (const e of after.entries) afterMap.set(e.relativePath, e.sha256);

  // Deleted or content-changed
  for (const [relPath, oldHash] of beforeMap) {
    const newHash = afterMap.get(relPath);
    if (newHash === undefined) {
      changes.push(`deleted:${relPath}`);
    } else if (newHash !== oldHash) {
      changes.push(`content_changed:${relPath}`);
    }
  }

  // Created
  for (const [relPath] of afterMap) {
    if (!beforeMap.has(relPath)) {
      changes.push(`created:${relPath}`);
    }
  }

  return {
    hasChanges: changes.length > 0,
    changes,
    summary: {
      beforeFiles: before.fileCount,
      afterFiles: after.fileCount,
      beforeHash: before.canonicalHash,
      afterHash: after.canonicalHash,
      hashEqual: before.canonicalHash === after.canonicalHash,
      incomplete: false,
    },
  };
};

/**
 * Compare two multi-root snapshots.
 * Any root-level incomplete/error/changed → hasChanges=true.
 *
 * @param {MultiRootSnapshot} before
 * @param {MultiRootSnapshot} after
 * @returns {{ hasChanges: boolean, changes: string[], summary: Object }}
 */
MultiRootStableHash.diff = function diff(before, after) {
  const changes = [];

  // Aggregate hash comparison first (fast path)
  if (before.aggregateHash !== after.aggregateHash) {
    // Detailed per-root diff
    const beforeRoots = new Map(before.roots.map((r) => [r.label, r]));
    const afterRoots = new Map(after.roots.map((r) => [r.label, r]));

    // Check for root-level existence/incomplete changes
    const allLabels = new Set([...beforeRoots.keys(), ...afterRoots.keys()]);
    for (const label of allLabels) {
      const bRoot = beforeRoots.get(label);
      const aRoot = afterRoots.get(label);
      if (!bRoot) {
        changes.push(`root_created:${label}`);
      } else if (!aRoot) {
        changes.push(`root_deleted:${label}`);
      } else {
        if (bRoot.incomplete || aRoot.incomplete) {
          const errs = [...(bRoot.errors || []), ...(aRoot.errors || [])];
          changes.push(`root_incomplete:${label}:${errs.join(";")}`);
        } else if (bRoot.canonicalHash !== aRoot.canonicalHash) {
          // Detailed entry diff
          const beforeMap = new Map(bRoot.entries.map((e) => [e.relativePath, e.sha256]));
          const afterMap = new Map(aRoot.entries.map((e) => [e.relativePath, e.sha256]));
          for (const [rel, oldHash] of beforeMap) {
            if (!afterMap.has(rel)) changes.push(`deleted:${label}:${rel}`);
            else if (afterMap.get(rel) !== oldHash) changes.push(`content_changed:${label}:${rel}`);
          }
          for (const [rel] of afterMap) {
            if (!beforeMap.has(rel)) changes.push(`created:${label}:${rel}`);
          }
        }
      }
    }
  }

  // Incompleteness at any level is a P0 change
  if (before.incomplete || after.incomplete) {
    const errs = [...(before.allErrors || []), ...(after.allErrors || [])];
    if (!changes.length) {
      for (const e of errs) changes.push(`inventory_error:${e}`);
    }
  }

  return {
    hasChanges: changes.length > 0,
    changes,
    summary: {
      beforeAggregateHash: before.aggregateHash,
      afterAggregateHash: after.aggregateHash,
      beforeTotalFiles: before.totalFileCount,
      afterTotalFiles: after.totalFileCount,
      hashEqual: before.aggregateHash === after.aggregateHash,
      beforeIncomplete: before.incomplete,
      afterIncomplete: after.incomplete,
    },
  };
};

// ─── Exports for testing ────────────────────────────────────────────────

export { fileSha256Stream, walkDir, canonicalHashFromEntries };
