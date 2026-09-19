import { PROJECTS_FILE, STATE_FILE } from "../src/config.mjs";
import { ProjectStore, describeProject, describeProjectFull, STATUSES } from "../src/projects.mjs";
import { RoutineStore } from "../src/routines.mjs";

export const name = "project";
export const description =
  "Keep track of the projects you work on - a folder or repo, a server or database, a client, " +
  "or all three. Use this when the user mentions a project, asks to add one, or asks what you " +
  "know about it. Only a name is required to start; ask the user for the rest rather than " +
  "inventing it, then fill the fields in with update. " +
  "Actions: add, list, show, use, rename, update, status, archive, restore, attach, contact, " +
  "link, forget.";

export const parameters = {
  type: "object",
  properties: {
    action: { type: "string", description: "add, list, show, use, update, or forget." },
    name: { type: "string", description: "Project name (also accepts an existing id)." },
    summary: { type: "string", description: "One line about what the project is." },
    path: { type: "string", description: "Folder or repo path on disk." },
    repo: { type: "string", description: "Git remote or repo URL." },
    client: { type: "string", description: "Which client or person this is for, if any." },
    conventions: {
      type: "array",
      description: "How the user likes things done here, e.g. ['pnpm not npm', 'ports 4000+'].",
      items: { type: "string" },
    },
    convention: {
      type: "string",
      description: "One convention to append without replacing the existing list.",
    },
    databases: {
      type: "array",
      description: "Databases this project uses. Credentials are stored as NAMES only, never values.",
      items: {
        type: "object",
        properties: {
          name: { type: "string" },
          kind: { type: "string", description: "postgres, mysql, sqlite, mongo, ..." },
          environment: { type: "string", description: "prod, staging, local, ..." },
          credential: { type: "string", description: "Name of a stored credential, not the secret." },
        },
      },
    },
    environments: {
      type: "array",
      description: "Servers or environments this runs on.",
      items: {
        type: "object",
        properties: {
          name: { type: "string" },
          host: { type: "string" },
          credential: { type: "string" },
        },
      },
    },
    new_name: { type: "string", description: "For rename: the new display name (the id never changes)." },
    status: { type: "string", description: `For status: one of ${STATUSES.join(", ")}.` },
    archived: { type: "boolean", description: "For list: include archived projects. Default false." },
    contact_name: { type: "string", description: "For contact: the person's name." },
    role: { type: "string", description: "For contact: their role, e.g. PM, CTO." },
    email: { type: "string", description: "For contact: their email." },
    label: { type: "string", description: "For link: a short label for the url." },
    url: { type: "string", description: "For link: the url to record." },
    routines: {
      type: "array",
      description: "For attach: specific routine ids to tag. Omit to tag every untagged routine.",
      items: { type: "string" },
    },
    watches: {
      type: "array",
      description: "For attach: specific watch ids to tag. Omit to tag every untagged watch.",
      items: { type: "string" },
    },
  },
  required: ["action"],
};

export const needsApproval = false;

function store() {
  return new ProjectStore(PROJECTS_FILE).load();
}

function askLine(missing) {
  if (!missing.length) return "";
  return `\nWorth asking ${"them"} about (skip any that do not apply): ${missing.join(", ")}.`;
}

export function run(args = {}) {
  const s = store();
  const action = String(args.action || "list").toLowerCase();

  if (action === "add") {
    const label = String(args.name ?? "").trim();
    if (!label) {
      // Guided intake: nothing is created until we know what to call it.
      return (
        "I need a name before I can add anything.\n" +
        "Ask the user which project this is (offer the existing ones from `project action=list`), " +
        "and whether it is new.\n" +
        "Then ask, one at a time: what it is, where it lives, which database, which servers, " +
        "how they like things done, which client."
      );
    }
    const existing = s.find(label);
    if (existing) {
      return `A project called "${existing.name}" already exists (id ${existing.id}). Ask whether to update that one instead.`;
    }
    try {
      const project = s.add({
        name: label,
        summary: args.summary,
        path: args.path,
        repo: args.repo,
        client: args.client,
        conventions: args.conventions,
        environments: args.environments,
        databases: args.databases,
      });
      // Adding a project means you are working on it, so make it active.
      const activated = s.use(project.id);
      const missing = s.missingFor(activated);
      return (
        `Added project "${activated.name}" (id ${activated.id})` +
        (activated.path ? ` at ${activated.path}` : "") +
        " and made it the active project.\nTell the user it is saved, then ask the next question." +
        askLine(missing)
      );
    } catch (err) {
      return `Error: ${err.message}`;
    }
  }

  if (action === "list") {
    if (!s.projects.length) {
      return "No projects yet. Ask the user whether to add one, starting with its name.";
    }
    const all = s.projects;
    const shown = args.archived ? all : all.filter((p) => !p.archived);
    if (!shown.length) {
      return `All ${all.length} project(s) are archived. Use archived: true to see them.`;
    }
    const hidden = all.length - shown.length;
    return (
      shown.map((p) => describeProject(p, s.activeId)).join("\n") +
      "\n\n(the * marks the active project; ids are the second column)" +
      (hidden ? `\n(${hidden} archived project(s) hidden - pass archived: true to include)` : "")
    );
  }

  if (action === "rename") {
    if (!args.name) return "Error: 'name' is required to rename (which project?).";
    if (!args.new_name) return "Error: 'new_name' is required. What should it be called?";
    const before = s.find(args.name);
    if (!before) return `Error: no project "${args.name}". See project action=list.`;
    if (s.find(args.new_name) && s.find(args.new_name).id !== before.id) {
      return `Error: another project is already called "${args.new_name}".`;
    }
    const renamed = s.renameProject(before.id, args.new_name);
    return (
      `Renamed "${before.name}" to "${renamed.name}".\n` +
      `Id is unchanged at "${renamed.id}", so anything already tagged with it still points here.`
    );
  }

  if (action === "status") {
    if (!args.name) return "Error: 'name' is required.";
    if (!args.status) {
      const p = s.find(args.name);
      if (!p) return `Error: no project "${args.name}".`;
      return `"${p.name}" is ${p.status || "active"}${p.archived ? " (archived)" : ""}. Set it with status: one of ${STATUSES.join(", ")}.`;
    }
    const updated = s.setStatus(args.name, args.status);
    if (!updated) return `Error: no project "${args.name}".`;
    if (updated.error) return `Error: ${updated.error}.`;
    return `"${updated.name}" is now ${updated.status}.`;
  }

  if (action === "archive" || action === "restore") {
    if (!args.name) return `Error: 'name' is required to ${action}.`;
    const updated = s.setArchived(args.name, action === "archive");
    if (!updated) return `Error: no project "${args.name}".`;
    return action === "archive"
      ? `Archived "${updated.name}". It is hidden from list and is no longer active; nothing on disk was touched. Use restore to bring it back.`
      : `Restored "${updated.name}". It shows in list again.`;
  }

  if (action === "contact" || action === "link") {
    if (!args.name) return `Error: 'name' is required to add a ${action}. Which project?`;
    const updated =
      action === "contact"
        ? s.addContact(args.name, { name: args.contact_name, role: args.role, email: args.email })
        : s.addLink(args.name, { label: args.label, url: args.url });
    if (!updated) return `Error: no project "${args.name}".`;
    if (updated.error) return `Error: ${updated.error}.`;
    const rows = action === "contact" ? updated.contacts : updated.links;
    return (
      `Updated "${updated.name}".\n` +
      rows
        .map((r) =>
          action === "contact"
            ? `  ${[r.name, r.role, r.email].filter(Boolean).join(" · ")}`
            : `  ${r.label}  ${r.url}`
        )
        .join("\n")
    );
  }

  if (action === "attach") {
    if (!args.name) return "Error: 'name' is required to attach. Which project?";
    const project = s.find(args.name);
    if (!project) return `Error: no project "${args.name}". See project action=list.`;

    const store = new RoutineStore(STATE_FILE).load();
    const moved = store.attachToProject(project.id, { routines: args.routines, watches: args.watches });
    const total = moved.routines.length + moved.watches.length;
    if (!total) {
      return args.routines || args.watches
        ? `Nothing matched, so "${project.name}" was left alone. Check the ids with schedule action=list / watch action=list.`
        : `Every routine and watch is already tagged, so there was nothing to attach.`;
    }
    return (
      `Attached ${total} item(s) to "${project.name}":\n` +
      [
        ...moved.routines.map((id) => `  routine ${id}`),
        ...moved.watches.map((id) => `  watch ${id}`),
      ].join("\n")
    );
  }

  if (action === "show") {
    const project = args.name ? s.find(args.name) : s.active;
    if (!project) {
      return args.name
        ? `Error: no project "${args.name}". See project action=list.`
        : "No project is active and none was named. Ask which project they mean.";
    }
    return describeProjectFull(project, s);
  }

  if (action === "use") {
    const project = s.use(args.name);
    if (!project) return `Error: no project "${args.name}". See project action=list.`;
    return (
      `Active project is now "${project.name}" (id ${project.id}).` +
      (project.path ? `\nWorking directory: ${project.path}` : "") +
      "\nTell the user, and mention they may need to restart nothing - it applies from now on."
    );
  }

  if (action === "update") {
    if (!args.name) return "Error: 'name' is required to update. Which project?";
    const target = s.find(args.name);
    if (!target) return `Error: no project "${args.name}". See project action=list.`;

    const patch = {};
    for (const field of ["summary", "path", "repo", "client", "conventions", "environments", "databases"]) {
      if (args[field] !== undefined) patch[field] = args[field];
    }
    let project = Object.keys(patch).length ? s.update(target.id, patch) : target;
    if (args.convention) project = s.addConvention(target.id, args.convention);
    if (!project) return `Error: could not update "${args.name}".`;

    const missing = s.missingFor(project);
    return (
      `Updated "${project.name}".\n${describeProjectFull(project, s)}` +
      (missing.length ? `\nStill unknown: ${missing.join(", ")}. Ask only if it matters now.` : "")
    );
  }

  if (action === "forget") {
    if (!args.name) return "Error: 'name' is required to forget.";
    const removed = s.forget(args.name);
    if (!removed) return `Error: no project "${args.name}".`;
    return `Forgot project "${removed.name}". Nothing on disk was touched - only the record.`;
  }

  return `Error: unknown action "${action}". Use add, list, show, use, rename, update, status, archive, restore, attach, contact, link, or forget.`;
}
