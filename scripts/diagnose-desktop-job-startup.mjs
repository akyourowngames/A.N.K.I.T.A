// Measure actual job readiness and main-event-loop responsiveness in an isolated fixture.
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { run } from '../tools/process/run-command.mjs';
import { run as wait } from '../tools/process/job-wait.mjs';
import { cleanupJobs } from '../tools/index.mjs';
const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-startup-profile-'));
const file = path.join(fixture, 'probe.cjs');
const firstDeadlineMs = 5000; // Milliseconds; reproduce the existing jobs.test.mjs deadline.
const finalDeadlineMs = 20000; // Milliseconds; observe completion beyond the short fixture deadline.
const heartbeatMs = 20; // Milliseconds; detects caller-event-loop stalls during native launch.
const quote = value => "'" + value.replaceAll("'",process.platform==='win32'?"''":"'\\''") + "'";
const ctx = {cwd:fixture,state:{jobs:new Map()}};
let last = performance.now(), maxGap = 0;
const start = last;
const timer = setInterval(()=>{const now=performance.now();maxGap=Math.max(maxGap,now-last);last=now;},heartbeatMs);
try {
  await fs.writeFile(file,"console.log('first');setTimeout(()=>console.log('second'),300);setTimeout(()=>{},500);");
  await run({command:(process.platform==='win32'?'& ':'')+quote(process.execPath)+' '+quote(file),background:true},ctx);
  const job=[...ctx.state.jobs.values()][0];
  let readyMs, outputMs;
  void job.child.ready?.then(()=>{readyMs=performance.now()-start;});
  job.child.stdout.on('data',()=>{outputMs??=performance.now()-start;});
  const first=JSON.parse(await wait({job_id:job.id,timeout_ms:firstDeadlineMs,since_offset:0},ctx));
  const final=first.state==='done'?first:JSON.parse(await wait({job_id:job.id,timeout_ms:finalDeadlineMs,since_offset:0},ctx));
  const evidence={firstDeadlineMs,firstState:first.state,firstOutputBytes:first.output?.length||0,finalState:final.state,exitCode:final.exit_code,readyMs,firstOutputMs:outputMs,completedMs:performance.now()-start,maxCallerHeartbeatGapMs:maxGap,output:job.out.toString()};
  console.log(JSON.stringify(evidence,null,2));
} finally {clearInterval(timer);await cleanupJobs(ctx.state);await fs.rm(fixture,{recursive:true,force:true});}
