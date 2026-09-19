import { PROJECTS_FILE } from "../src/config.mjs";
import { ProjectStore, describeProject, describeProjectFull } from "../src/projects.mjs";

export const name = "project";
export const description =
  "Keep track of the projects you work on - a folder or repo, a server or database, a client, " +
  "or all three. Use this when the user mentions a project, asks to add one, or asks what you " +
  "know about it. Only a name is required to start; ask the user for the rest rather than " +
  "inventing it, then fill the fields in with update. " +
  "Actions: add, list, show, use, update, forget.";

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
    return (
      s.projects.map((p) => describeProject(p, s.activeId)).join("\n") +
      "\n\n(the * marks the active project; ids are the second column)"
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

  return `Error: unknown action "${action}". Use add, list, show, use, update, or forget.`;
}
