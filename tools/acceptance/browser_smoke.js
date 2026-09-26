// G0 browser smoke (A006): module execution / root mount / error surface.
// Invocation: ego-browser nodejs < tools/acceptance/browser_smoke.js
// Emits exactly one line: SMOKE_JSON={...} for the gate's --check-smoke parser.
// 5186 unreachable -> BLOCKED (never PASS); empty #root or load failure -> FAIL.

const target = process.env.SMOKE_URL || "http://127.0.0.1:5186/";

function emit(verdict, extra) {
  console.log("SMOKE_JSON=" + JSON.stringify({
    url: target,
    verdict,
    reasons: [],
    ...extra,
    snapshot_at: new Date().toISOString(),
  }));
}

try {
  const task = await taskSpace("G0 acceptance smoke 5186");
  const page = task.page("p1");
  try {
    await page.goto(target);
  } catch (err) {
    await task.finish({ keep: [] });
    emit("BLOCKED", { reasons: ["frontend_unreachable", String(err).slice(0, 200)] });
    process.exit(0);
  }
  let rootState;
  try {
    await page.waitForSelector("#root", { timeout: 15000 });
    await page.waitForTimeout(2500); // allow vite module graph + React mount
    rootState = await page.evaluate(() => {
      const root = document.querySelector("#root");
      return {
        rootExists: !!root,
        rootChildren: root ? root.children.length : -1,
        rootTextLength: root ? (root.textContent || "").trim().length : -1,
        title: document.title || "",
      };
    });
  } catch (err) {
    await task.finish({ keep: [] });
    emit("FAIL", { reasons: ["root_mount_check_failed", String(err).slice(0, 200)] });
    process.exit(0);
  }

  let errorSurface = [];
  try {
    const events = await page.events();
    errorSurface = (events || [])
      .map((ev) => JSON.stringify(ev))
      .filter((text) => /"(pageerror|error)"|Failed to load module|SyntaxError|ReferenceError/i.test(text))
      .slice(0, 10);
  } catch (err) {
    // event buffer unavailable is not itself a page failure; root state decides
  }

  const mounted = rootState.rootExists && rootState.rootChildren > 0;
  await task.finish({ keep: [] });
  if (!mounted) {
    emit("FAIL", { rootState, reasons: ["root_not_mounted_module_load_failure"],
                    errorSurface });
  } else {
    emit(errorSurface.length ? "FAIL" : "PASS", { rootState, errorSurface,
      reasons: errorSurface.length ? ["browser_error_events"] : [] });
  }
  process.exit(0);
} catch (err) {
  emit("BLOCKED", { reasons: ["smoke_runtime_error", String(err).slice(0, 200)] });
  process.exit(0);
}
