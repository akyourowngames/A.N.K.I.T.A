import fs from "node:fs";
import path from "node:path";
import { SESSIONS_DIR, MCP_FILE, COMPOSIO_FILE, PROJECTS_FILE } from "./config.mjs";
import { ProjectStore } from './projects.mjs';
import { McpStore } from "./mcp-store.mjs";
import { ComposioStore } from "./composio-store.mjs";
import { Agent } from "./agent.mjs";
import { sanitizeMessages } from "./history.mjs";
import { checkWatch } from "./watcher.mjs";
import { describeCron } from "./cron.mjs";
import { buildAlertPrompt, renderAlertFallback } from "./alerts.mjs";
import { recordTurn, saveSession } from './sessions.mjs';
import {
  transcribeGroq,
  synthesizeEdge,
  synthesizeGroq,
  convertAudio,
  voiceRuntimeCheck,
  resolveTtsProvider,
  resolveTtsVoice,
} from "./voice.mjs";

/**
 * The proactive loop: scheduled routines, URL watches, and a Telegram inbox,
 * all driving the same Agent the REPL uses.
 *
 * Pure-ish by construction — every side effect (running a prompt, delivering
 * a message) is injected, so the loop can be tested without a network or a
 * terminal.
 */

const ANSI = /\x1b\[[0-9;]*m/g;

/** Approval diffs come from the CLI renderer with colour codes; Telegram wants plain text. */
export const stripAnsi = (s) => String(s ?? "").replace(ANSI, "");

/** Approval replies are short: "y", "yes", "ok", "always", "a", "n", "no". */
export function parseApproval(text) {
  const t = String(text || "").trim().toLowerCase().replace(/[.!]+$/, "");
  if (!t) return "no";
  if (/^(a|always|all|yes always|y always|yes all|always allow)$/.test(t)) return "always";
  if (/^(y|ye|yes|yeah|yep|ok|okay|sure|approve|approved|allow|allowed|go|do it|fine|k)$/.test(t)) return "yes";
  return "no";
}

/**
 * True for a bare affirmative ("y", "yes", "ok", "a", "always") and nothing
 * else. Used to catch a late answer to an expired approval so it is not fed
 * to the model as a prompt — which produces "did you mean to type y?".
 */
export function isBareApproval(text) {
  const t = String(text || "").trim().toLowerCase().replace(/[.!]+$/, "");
  return /^(y|ye|yes|yeah|yep|ok|okay|sure|approve|approved|allow|allowed|go|do it|fine|k|a|always|all)$/.test(t);
}

export class Daemon {
  constructor({
    store,
    bot = null,
    config,
    client,
    model = null,
    tool = null,
    runPrompt,
    deliver,
    flushNotifications = null,
    consolidator = null,
    log = () => {},
    logFile = null,
    tickMs = 20000,
    maxConcurrent = null,
    checker = checkWatch,
    mcp = null,
    now = () => new Date(),
  }) {
    this.store = store;
    this.bot = bot?.enabled ? bot : null;
    this.config = config;
    this.client = client;
    // Same chat/tool-model split as the REPL, so Telegram DMs get it too.
    this.tool = tool;
    // Chat agents must use the same resolved model as the REPL; without this
    // they send model:null and depend on the server's fallback.
    this.model = model;
    this.runPrompt = runPrompt;
    this.deliver = deliver;
    this.flushNotifications = flushNotifications;
    this.consolidator = consolidator;
    this.logFile = logFile;
    // Tee every line to a UTF-8 log file, and to the terminal when one exists.
    this.log = (message) => {
      log(message);
      if (!this.logFile) return;
      try {
        fs.mkdirSync(path.dirname(this.logFile), { recursive: true });
        fs.appendFileSync(this.logFile, `[${new Date().toISOString()}] ${message}\n`, "utf8");
      } catch {}
    };
    this.tickMs = Math.max(5000, tickMs);
    // Injectable so tests can drive the real dispatch/flush path.
    this.checker = checker;
    // The process-level MCP manager, shared with the REPL when both run here.
    this.mcp = mcp;
    this.now = now;

    this.stopping = false;
    // Resume the inbox cursor so a restart neither replays nor drops messages.
    this.offset = store.telegramOffset || 0;
    this.offsetReady = this.offset > 0;
    this.chatAgents = new Map();
    // Per-chat work chains: the poll loop must stay free to receive an
    // approval reply while an agent turn is parked waiting for one.
    this.chains = new Map();
    this.pending = new Map();
    // Guards so a long-running routine (e.g. one parked on an approval) cannot
    // be dispatched again by the next tick.
    this.runningRoutines = new Set();
    this.runningWatches = new Set();
    // Changes collected during a tick, flushed as one composed message.
    this.alertQueue = [];
    this.flushing = false;
    // Every routine scheduled for the same minute would otherwise start at
    // once and rate-limit the provider. Serialise the agent turns instead.
    this.maxConcurrent = Math.max(1, Number(maxConcurrent ?? config.maxConcurrent) || 4);
    this.active = 0;
    this.waiting = [];
    // Config is in SECONDS; the floor keeps a typo from making approval impossible.
    this.confirmTimeoutMs = Math.max(30000, (Number(config.telegramConfirmTimeout) || 300) * 1000);
    this.stats = { routinesRun: 0, changesAlerted: 0, messagesHandled: 0, errors: 0 };
  }

  stop() {
    this.stopping = true;
  }

  /* ------------------------- conversation per chat ------------------------ */

  sessionFile(chatId) {
    return path.join(SESSIONS_DIR, `dm-${String(chatId).replace(/[^0-9-]/g, "")}.json`);
  }

  chatAgent(chatId) {
    const key = String(chatId);
    if (this.chatAgents.has(key)) return this.chatAgents.get(key);

    const agent = new Agent({
      client: this.client,
      skillsEnabled: false,
      tool: this.tool,
      config: this.config,
      journal: turn => recordTurn(turn, { timeZone: this.config.timeZone }),
      // A DM cannot answer a terminal prompt, so the question is forwarded to
      // Telegram and the turn parks until you reply. Read-only tools never
      // reach here. Without a bot, fall back to the configured default.
      confirm: (toolName, detail) => this.confirmFrom(key, toolName, detail),
      print: () => {},
      write: () => {},
    });
    if (this.model) agent.model = this.model;
    try {
      const saved = JSON.parse(fs.readFileSync(this.sessionFile(key), "utf8"));
      if (saved.projectId) {
        const projects = new ProjectStore(PROJECTS_FILE).load();
        if (projects.find(saved.projectId)) {
          projects.data.active = saved.projectId;
          agent.setProject(projects.promptBlock(), saved.projectId);
        }
      }
      const restored = sanitizeMessages((saved.messages || []).filter((m) => m.role !== "system"));
      agent.messages.push(...restored);
    } catch {}
    this.chatAgents.set(key, agent);
    return agent;
  }

  /* ------------------------------ approvals ------------------------------ */

  /** Approval for routine/brief work: asks the owner's chat when there is one. */
  confirmOwner(toolName, detail) {
    const chatId = this.config.telegramChatId || this.ownerFallbackChat();
    if (this.bot && chatId) return this.confirmFrom(String(chatId), toolName, detail);
    return Promise.resolve(Boolean(this.config.autoApprove));
  }

  ownerFallbackChat() {
    const first = String(this.config.telegramAllowedChatIds || "").split(/[,\s]+/).filter(Boolean)[0];
    return first || null;
  }

  /**
   * Sends the approval question to a chat and resolves when that chat replies.
   * Returns true to allow. A reply of "always" also flips the chat's agent to
   * auto-approve for the rest of the session.
   */
  async confirmFrom(chatId, toolName, detail) {
    const key = String(chatId);
    const agent = this.chatAgents.get(key);
    if (this.config.autoApprove || agent?.autoApprove) return true;
    if (!this.bot) return false;

    const body = stripAnsi(detail).trim();
    await this.bot.send(
      chatId,
      `Permission needed: ${toolName}\n\n${body}\n\nReply y = allow once, a = always, n = deny` +
        `\n(times out in ${Math.round(this.confirmTimeoutMs / 60000)} min)`
    );

    this.log(`waiting for ${toolName} approval in chat ${key}`);
    return new Promise((resolve) => {
      const entry = {
        toolName,
        settle: (answer) => {
          clearTimeout(entry.timer);
          if (this.pending.get(key) === entry) this.pending.delete(key);
          this.log(`${toolName} ${answer === "no" ? "denied" : "approved"} in chat ${key}`);
          resolve(answer === "yes" || answer === "always");
        },
      };
      entry.timer = setTimeout(() => {
        const stillWaiting = this.pending.get(key) === entry;
        entry.settle("no");
        if (stillWaiting) {
          this.bot.send(chatId, `No reply, so I skipped ${toolName}.`).catch(() => {});
        }
      }, this.confirmTimeoutMs);
      this.pending.set(key, entry);
    });
  }

  /**
   * If this message is an answer to a pending approval, consume it and return
   * true so it is not also treated as a new request.
   */
  resolvePending(job) {
    const key = String(job.chatId);
    const waiting = this.pending.get(key);
    if (!waiting) return false;
    if (job.kind !== "text") {
      this.bot?.send(key, `Reply with text (y / n / a) to approve ${waiting.toolName}.`).catch(() => {});
      return true;
    }
    const answer = parseApproval(job.text);
    if (answer === "always") {
      const agent = this.chatAgents.get(key);
      if (agent) agent.autoApprove = true;
    }
    waiting.settle(answer);
    return true;
  }

  saveChat(chatId) {
    const agent = this.chatAgents.get(String(chatId));
    if (!agent) return;
    try {
      fs.mkdirSync(SESSIONS_DIR, { recursive: true });
      saveSession(this.sessionFile(chatId), { savedAt: new Date().toISOString(), model: agent.model, messages: agent.messages, projectId: agent.projectId, journaled: agent.journalComplete });
    } catch (err) {
      this.log(`could not save dm session: ${err.message}`);
    }
  }

  /* ------------------------------- routines ------------------------------ */

  /**
   * Queues due routines and returns immediately.
   *
   * Never await the work here: a routine that needs approval parks until you
   * answer in Telegram, and the poll that would deliver your answer lives in
   * this same loop. Blocking on it guarantees the approval times out.
   */
  dispatchRoutines() {
    const due = this.store.dueRoutines(this.now());
    let queued = 0;
    for (const routine of due) {
      if (this.runningRoutines.has(routine.id)) continue;
      this.runningRoutines.add(routine.id);
      // Claim it now so the next tick cannot double-fire while it is in flight.
      this.store.claimRoutine(routine.id, this.now().toISOString());
      this.log(`routine ${routine.id} (${describeCron(routine.cron)}) firing`);
      this.chain(`routine:${routine.id}`, () => this.executeRoutine(routine));
      queued++;
    }
    return queued;
  }

  async executeRoutine(routine) {
    let status = "ok";
    let summary = "";
    try {
      const text = await this.runPrompt(routine.prompt, { purpose: "routine", routine });
      summary = String(text || "").trim();
      if (!summary) status = "empty";
      else await this.deliver(`*${routine.name}*\n\n${summary}`, { routine });
    } catch (err) {
      status = "error";
      summary = err.message;
      this.stats.errors++;
      this.log(`routine ${routine.id} failed: ${err.message}`);
    } finally {
      this.runningRoutines.delete(routine.id);
      this.store.markRoutineRun(routine.id, {
        status,
        summary,
        at: this.now().toISOString(),
      });
      this.stats.routinesRun++;
    }
  }

  /** Dispatch and wait - used by tests and by callers that want completion. */
  async runDueRoutines() {
    const queued = this.dispatchRoutines();
    await this.drain();
    return queued;
  }

  /* -------------------------------- watches ------------------------------ */

  /** Queues due watch checks and returns immediately (same reason as routines). */
  dispatchWatches() {
    const due = this.store.dueWatches(this.now());
    const pending = [];
    for (const watch of due) {
      if (this.runningWatches.has(watch.id)) continue;
      this.runningWatches.add(watch.id);
      pending.push(this.chain(`watch:${watch.id}`, () => this.executeWatch(watch)));
    }
    // Once this tick's checks settle, report everything in one message. The
    // flush is not awaited: the poll loop must stay free.
    if (pending.length) {
      Promise.allSettled(pending)
        .then(() => this.flushAlerts())
        .catch((err) => this.log(`alert flush failed: ${err.message}`));
    }
    return due.length;
  }

  /**
   * Sends one composed message covering every change from the last check.
   * Falls back to plain text if the model is unavailable, so a change is
   * never silently dropped.
   */
  async flushAlerts() {
    if (this.flushing || !this.alertQueue.length) return null;
    const changes = this.alertQueue.splice(0, this.alertQueue.length);
    this.flushing = true;
    try {
      if (this.config.watchAlertLlm === false) {
        await this.deliver(renderAlertFallback(changes), { watch: changes[0].watch });
        return "fallback";
      }
      const prompt = buildAlertPrompt({
        username: this.config.username,
        agentName: this.config.agentName,
        changes,
        template: this.config.watchAlertPrompt,
      });
      let text = "";
      try {
        text = String((await this.runPrompt(prompt, { purpose: "alert", changes })) || "").trim();
      } catch (err) {
        this.log(`alert composition failed (${err.message}); sending plain text`);
      }
      const message = text || renderAlertFallback(changes);
      const mode = text ? "composed" : "fallback";
      this.log(
        `alert (${mode}) covering ${changes.length} change(s): ${message.replace(/\s+/g, " ").slice(0, 120)}`
      );
      await this.deliver(message, { watch: changes[0].watch });
      return mode;
    } catch (err) {
      this.alertQueue.unshift(...changes);
      throw err;
    } finally {
      this.flushing = false;
    }
  }

  async executeWatch(watch) {
    let result;
    try {
      result = await this.checker(watch, { cwd: process.cwd(), config: this.config });
    } catch (err) {
      result = { error: err.message };
    } finally {
      this.runningWatches.delete(watch.id);
    }
    const recorded = this.store.recordWatchCheck(watch.id, {
      value: result.value ?? null,
      text: result.text ?? null,
      error: result.error ?? null,
    });
    if (result.error) {
      this.log(`watch ${watch.id}: ${result.error}`);
      return;
    }
    if (recorded?.changed && watch.notify) {
      if (!this.store.shouldAlert(recorded.watched, this.now())) {
        this.log(`watch ${watch.id} moved but is inside its alert cooldown`);
        return;
      }
      this.stats.changesAlerted++;
      this.store.markAlerted(watch.id, this.now().toISOString());
      // Queue it: the tick reports every change in one message.
      this.alertQueue.push({
        watch: recorded.watched,
        previous: recorded.previous ?? null,
        value: recorded.value ?? null,
        delta: recorded.delta ?? null,
      });
    }
  }

  /** Dispatch and wait - used by tests. */
  async checkDueWatches() {
    const queued = this.dispatchWatches();
    await this.drain();
    return { checked: queued, alerted: 0 };
  }

  /* -------------------------------- inbox -------------------------------- */

  async handleJob(job) {
    const agent = this.chatAgent(job.chatId);
    let prompt = job.text || "";
    try {
      if (job.kind === "voice") {
        if (voiceRuntimeCheck()) throw new Error(voiceRuntimeCheck());
        if (!this.config.groqApiKey) throw new Error("set GROQ_API_KEY to transcribe voice notes");
        const ogg = await this.bot.download(job.fileId);
        const wav = await convertAudio(ogg, { to: "wav" });
        const wavPath = path.join(
          process.env.TEMP || process.env.TMPDIR || "/tmp",
          `ankita-tg-${Date.now()}.wav`
        );
        fs.writeFileSync(wavPath, wav);
        try {
          prompt = await transcribeGroq({
            apiKey: this.config.groqApiKey,
            model: this.config.sttModel,
            wavPath,
          });
        } finally {
          try {
            fs.unlinkSync(wavPath);
          } catch {}
        }
        if (!prompt) {
          await this.bot.send(job.chatId, "I could not make out that voice note.");
          return;
        }
      }

      await this.bot.sendTyping(job.chatId);
      const reply = await agent.send(prompt, {});
      const text = String(reply || "").trim() || "(no reply)";
      await this.bot.send(job.chatId, text, { replyTo: job.messageId });

      if (this.config.telegramVoiceReply) {
        await this.speakBack(job.chatId, text);
      }
    } catch (err) {
      this.stats.errors++;
      this.log(`dm ${job.chatId} failed: ${err.message}`);
      try {
        await this.bot.send(job.chatId, `error: ${err.message}`);
      } catch {}
    } finally {
      this.stats.messagesHandled++;
      this.saveChat(job.chatId);
    }
  }

  async speakBack(chatId, text) {
    try {
      const provider = resolveTtsProvider(this.config);
      const audio =
        provider === "groq"
          ? await synthesizeGroq({
              apiKey: this.config.groqApiKey,
              model: this.config.ttsModel,
              voice: resolveTtsVoice(this.config, "groq"),
              text,
            })
          : await synthesizeEdge({
              voice: resolveTtsVoice(this.config, "edge"),
              rate: this.config.ttsRate,
              text,
            });
      const ogg = await convertAudio(audio, { to: "ogg" });
      await this.bot.sendVoice(chatId, ogg);
    } catch (err) {
      this.log(`voice reply failed: ${err.message}`);
    }
  }

  async pollInbox() {
    if (!this.bot) return 0;

    // First ever run: skip whatever backlog is sitting in the bot's queue
    // rather than answering week-old messages.
    if (!this.offsetReady) {
      const drain = await this.bot.poll(-1, { timeoutSec: 0 });
      this.offsetReady = true;
      if (!drain.error && drain.offset > 0) {
        this.offset = drain.offset;
        this.store.setTelegramOffset(this.offset);
        this.log(`inbox: skipping backlog, cursor at ${this.offset}`);
      } else {
        this.log("inbox: no backlog");
      }
      return 0;
    }

    const { jobs, denied, offset, error } = await this.bot.poll(this.offset);
    if (error) {
      this.log(`telegram poll: ${error}`);
      return 0;
    }
    if (offset !== this.offset && offset > 0) {
      this.offset = offset;
      this.store.setTelegramOffset(offset);
    }
    for (const job of denied || []) {
      try {
        await this.bot.send(
          job.chatId,
          `This bot is private. Your chat id is ${job.chatId} - add it to TELEGRAM_ALLOWED_CHAT_IDS to allow it.`
        );
      } catch {}
    }
    for (const job of jobs) {
      if (this.resolvePending(job)) continue;
      // A stray "y" with nothing pending is an answer to a question that has
      // already expired; say so instead of asking the model what it meant.
      if (job.kind === "text" && isBareApproval(job.text)) {
        this.bot
          .send(job.chatId, "Nothing is waiting for approval right now.", { replyTo: job.messageId })
          .catch(() => {});
        continue;
      }
      this.dispatch(job);
    }
    return jobs.length;
  }

  /**
   * Runs a job without blocking the poll loop, serialised per chat so two
   * messages cannot interleave inside one conversation. Staying non-blocking
   * is what lets an approval reply be received while a turn waits for it.
   */
  dispatch(job) {
    return this.chain(`chat:${job.chatId}`, () => this.handleJob(job));
  }

  /** Global concurrency gate for agent turns. */
  async acquire() {
    if (this.active < this.maxConcurrent) {
      this.active++;
      return;
    }
    await new Promise((resolve) => this.waiting.push(resolve));
  }

  release() {
    this.active--;
    const next = this.waiting.shift();
    if (next) {
      this.active++;
      next();
    }
  }

  /**
   * Serialises work per key without blocking the poll loop, and caps how many
   * keys run at once. The poll itself is never gated.
   */
  chain(key, work) {
    const gated = async () => {
      await this.acquire();
      try {
        return await work();
      } finally {
        this.release();
      }
    };
    const previous = this.chains.get(key) || Promise.resolve();
    const next = previous
      .then(gated)
      .catch((err) => {
        this.stats.errors++;
        this.log(`${key} failed: ${err.message}`);
      })
      .finally(() => {
        if (this.chains.get(key) === next) this.chains.delete(key);
      });
    this.chains.set(key, next);
    return next;
  }

  /**
   * Waits for in-flight turns, but never forever: a turn parked on an
   * approval would otherwise hold shutdown open until it times out.
   */
  async drain(timeoutMs = 10000) {
    const pending = [...this.chains.values()];
    if (!pending.length) return false;
    let timer;
    try {
      const finished = await Promise.race([
        Promise.allSettled(pending).then(() => true),
        new Promise((resolve) => {
          timer = setTimeout(() => resolve(false), Math.max(0, timeoutMs));
          timer.unref?.();
        }),
      ]);
      if (!finished) this.log(`${this.chains.size} turn(s) still running after ${timeoutMs}ms`);
      return finished;
    } finally {
      clearTimeout(timer);
    }
  }

  /** One pass of everything. Exposed so tests can step the loop deterministically. */
  async tickOnce() {
    // Re-read state first: routines and watches can be added from the REPL or
    // by the agent itself while this daemon is already running.
    try {
      this.store.load();
    } catch (err) {
      this.log(`could not reload state: ${err.message}`);
    }
    // Bring MCP connections in line with the store, so `/mcp add` in another
    // window reaches a running daemon without a restart. Same reasoning as
    // reloading routines and watches above.
    if (this.mcp) {
      try {
        await this.mcp.reconcile(new McpStore(MCP_FILE).load());
        if (this.config.composioApiKey || this.config.composioBrokerUrl) {
          await this.mcp.ensureComposio(this.config, new ComposioStore(COMPOSIO_FILE).load());
        }
      } catch (err) {
        this.log(`mcp reconcile failed: ${err.message}`);
      }
    }

    const routines = this.dispatchRoutines();
    const checked = this.dispatchWatches();
    if (!checked && this.alertQueue.length && !this.flushing && !this.chains.has('alert-retry')) {
      this.chain('alert-retry', () => this.flushAlerts());
    }
    // Receive interactive work before deciding whether maintenance can start.
    const messages = await this.pollInbox();
    if (this.consolidator?.due() && !this.chains.has('consolidation') && this.active === 0 && this.waiting.length === 0 &&
        ![...this.chains.keys()].some(key => key !== 'notifications')) {
      // Low-priority maintenance starts only while idle, without using a chat slot.
      const work = this.consolidator.run()
        .then(async result => {
          if (result.processed) {
            this.log(`memory: consolidated ${result.processed} transcript part(s)`);
            const { warmRecall } = await import('../tools/recall.mjs');
            void warmRecall({ config: this.config });
          }
        })
        .catch(err => { this.stats.errors++; this.log(`memory consolidation failed: ${err.message}`); })
        .finally(() => this.chains.delete('consolidation'));
      this.chains.set('consolidation', work);
    }
    if (this.flushNotifications && !this.chains.has('notifications')) {
      const work = Promise.resolve().then(this.flushNotifications)
        .catch(err => this.log(`notification flush failed: ${err.message}`))
        .finally(() => this.chains.delete('notifications'));
      this.chains.set('notifications', work);
    }
    // Only the poll is awaited: it is the sleep, and it must keep running so a
    // Telegram approval can be received while a routine is parked.
    return { routines, checked, messages };
  }

  async run() {
    if (!this.bot) {
      this.log("no TELEGRAM_BOT_TOKEN: running schedules and watches with configured notification fallbacks");
    } else {
      try {
        const me = await this.bot.whoami();
        this.log(`telegram: @${me.username} - inbox open`);
      } catch (err) {
        this.log(`telegram login failed: ${err.message}`);
        this.bot = null;
      }
    }

    this.log(
      `daemon up - ${this.store.routines.length} routine(s), ${this.store.watches.length} watch(es), tick ${Math.round(this.tickMs / 1000)}s`
    );

    while (!this.stopping) {
      let result = null;
      try {
        result = await this.tickOnce();
      } catch (err) {
        this.stats.errors++;
        this.log(`tick failed: ${err.message}`);
      }

      if (this.stopping) break;
      // A Telegram long-poll already waits ~25s; otherwise sleep the tick.
      if (!this.bot) await new Promise((r) => setTimeout(r, this.tickMs));
      else if (result && result.routines === 0 && result.checked === 0 && result.messages === 0) {
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
    this.log("waiting for in-flight turns to finish");
    await this.drain();
    if (this.flushNotifications) await this.flushNotifications();
    for (const chatId of this.chatAgents.keys()) this.saveChat(chatId);
    this.log(`daemon stopping - ${JSON.stringify(this.stats)}`);
  }
}
