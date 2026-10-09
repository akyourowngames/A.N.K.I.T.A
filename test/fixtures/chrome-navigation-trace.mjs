const TRACE_CHARACTERS = 2048; // Test-only characters: bounded, owned-fixture tab evidence on a native navigation failure.

export async function traceFixtureNavigation(adapter, mcp, args, ctx) {
  try { return await adapter.run(args, ctx); }
  catch (error) {
    if (/net::ERR_ABORTED/.test(error.message)) {
      // Delay config-dependent imports until the caller has isolated CONFIG_DIR.
      const { CHROME_MCP_ID } = await import('../../src/integrations/browser-plugins.mjs');
      // Never retry new_page. Read its resulting tabs to diagnose whether the
      // upstream error happened before or after the owned navigation settled.
      let tabs;
      try { tabs = await mcp.callTool(`mcp__${CHROME_MCP_ID}__list_pages`, {}, { signal: ctx.signal }); }
      catch (inspection) { tabs = inspection.message; }
      console.log('CHROME_FIXTURE_NAVIGATION_FAILURE', JSON.stringify({ error: error.message, tabs: String(tabs).slice(0, TRACE_CHARACTERS), replayed: false }));
    }
    throw error;
  }
}
