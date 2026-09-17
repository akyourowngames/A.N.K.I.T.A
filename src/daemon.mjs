import fs from "node:fs";
import path from "node:path";
import { SESSIONS_DIR } from "./config.mjs";
import { Agent } from "./agent.mjs";
import { sanitizeMessages } from "./history.mjs";
import { checkWatch, formatWatchStatus } from "./watcher.mjs";
import { describeCron } from "./cron.mjs";
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

export class Daemon {
  constructor({
    store,
    bot = null,
    config,
    client,
    runPrompt,
    deliver,
    log = () => {},
    tickMs = 20000,
    now = () => new Date(),
  }) {
    this.store = store;
    this.bot = bot?.enabled ? bot : null;
    this.config = config;
    this.client = client;
    this.runPrompt = runPrompt;
    this.deliver = deliver;
    this.log = log;
    this.tickMs = Math.max(5000, tickMs);
    this.now = now;

    this.stopping = false;
    this.offset = 0;
    this.chatAgents = new Map();
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
      config: this.config,
      confirm: async () => true, // remote DMs cannot answer y/n prompts; read-only tools auto-run
      print: () => {},
      write: () => {},
    });
    try {
      const saved = JSON.parse(fs.readFileSync(this.sessionFile(key), "utf8"));
      const restored = sanitizeMessages((saved.messages || []).filter((m) => m.role !== "system"));
      agent.messages.push(...restored);
    } catch {}
    this.chatAgents.set(key, agent);
    return agent;
  }

  saveChat(chatId) {
    const agent = this.chatAgents.get(String(chatId));
    if (!agent) return;
    try {
      fs.mkdirSync(SESSIONS_DIR, { recursive: true });
      fs.writeFileSync(
        this.sessionFile(chatId),
        JSON.stringify({ savedAt: new Date().toISOString(), model: agent.model, messages: agent.messages }, null, 2)
      );
    } catch (err) {
      this.log(`could not save dm session: ${err.message}`);
    }
  }

  /* ------------------------------- routines ------------------------------ */

  async runDueRoutines() {
    const due = this.store.dueRoutines(this.now());
    for (const routine of due) {
      this.log(`routine ${routine.id} (${describeCron(routine.cron)}) firing`);
      let status = "ok";
      let summary = "";
      try {
        const text = await this.runPrompt(routine.prompt, { purpose: "routine", routine });
        summary = String(text || "").trim();
        if (!summary) {
          status = "empty";
        } else {
          await this.deliver(`*${routine.name}*\n\n${summary}`, { routine });
        }
      } catch (err) {
        status = "error";
        summary = err.message;
        this.stats.errors++;
        this.log(`routine ${routine.id} failed: ${err.message}`);
      }
      this.store.markRoutineRun(routine.id, {
        status,
        summary,
        at: this.now().toISOString(),
      });
      this.store.clearRunAt(routine.id);
      this.stats.routinesRun++;
    }
    return due.length;
  }

  /* -------------------------------- watches ------------------------------ */

  async checkDueWatches() {
    const due = this.store.dueWatches(this.now());
    let alerted = 0;
    for (const watch of due) {
      const ctx = { cwd: process.cwd(), config: this.config };
      let result;
      try {
        result = await checkWatch(watch, ctx);
      } catch (err) {
        result = { error: err.message };
      }
      const recorded = this.store.recordWatchCheck(watch.id, {
        value: result.value ?? null,
        text: result.text ?? null,
        error: result.error ?? null,
      });
      if (result.error) {
        this.log(`watch ${watch.id}: ${result.error}`);
        continue;
      }
      if (recorded?.changed && watch.notify) {
        alerted++;
        this.stats.changesAlerted++;
        const line = formatWatchStatus(recorded.watched, recorded);
        await this.deliver(`\u{1F514} ${line}\n${watch.url}`, { watch: recorded.watched });
      }
    }
    return { checked: due.length, alerted };
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
      agent.autoApprove = this.config.autoApprove;
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
    const { jobs, denied, offset, error } = await this.bot.poll(this.offset);
    this.offset = offset ?? this.offset;
    if (error) {
      this.log(`telegram poll: ${error}`);
      return 0;
    }
    for (const job of denied || []) {
      try {
        await this.bot.send(
          job.chatId,
          `This bot is private. Your chat id is ${job.chatId} - add it to TELEGRAM_ALLOWED_CHAT_IDS to allow it.`
        );
      } catch {}
    }
    for (const job of jobs) await this.handleJob(job);
    return jobs.length;
  }

  /** One pass of everything. Exposed so tests can step the loop deterministically. */
  async tickOnce() {
    const routines = await this.runDueRoutines();
    const watches = await this.checkDueWatches();
    const messages = await this.pollInbox();
    return { routines, ...watches, messages };
  }

  async run() {
    if (!this.bot) {
      this.log("no TELEGRAM_BOT_TOKEN: running schedules and watches only (alerts print locally)");
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
    this.log(`daemon stopping - ${JSON.stringify(this.stats)}`);
    for (const chatId of this.chatAgents.keys()) this.saveChat(chatId);
  }
}
