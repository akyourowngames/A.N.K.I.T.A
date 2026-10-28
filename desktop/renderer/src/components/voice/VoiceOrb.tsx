import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { VoicePhase, VoiceState } from '../../../../shared/voice.mjs';
import { useReducedMotion } from '../../lib/useReducedMotion';

const MAX_RENDER_PIXELS = 640; // Pixels per axis: cap GPU work on large and high-DPI displays.
const MAX_PIXEL_RATIO = 1.5; // Render density: soft pearl reflections need no full retina buffer.
const FRAME_MS = 1000 / 30; // Milliseconds: smooth, bounded thirty-frame animation.
const PHASE_ENERGY: Partial<Record<VoicePhase, number>> = { listening: .25, speaking: .8, working: .48, transcribing: .38, approval: .12, paused: .04 };
// Normalized RGB material swatches, shared by the shader and its CSS fallback.
const ORB_MATERIAL = Object.freeze({ ink: [.025, .025, .028], slate: [.23, .24, .26], frost: [.72, .76, .8], pearl: [.96, .97, .99], iris: [.46, .48, .53] });
const MATERIAL_STYLE = Object.fromEntries(Object.entries(ORB_MATERIAL).map(([name, rgb]) =>
  [`--orb-${name}`, `rgb(${rgb.map(value => Math.round(value * 255)).join(' ')})`])) as CSSProperties;
const VERTEX = `attribute vec2 a; varying vec2 uv; void main(){uv=a;gl_Position=vec4(a,0.,1.);}`;
// Original dark pearl: smooth satin lighting and a soft silver edge, without mesh or liquid folds.
// The coefficients below author geometry/light, not environment or service configuration.
const FRAGMENT = `precision highp float;
varying vec2 uv; uniform float time; uniform float energy; uniform float level;
uniform vec3 ink; uniform vec3 slate; uniform vec3 frost; uniform vec3 pearl; uniform vec3 iris;
void main(){
 vec2 p=uv*1.24; float r=length(p); if(r>1.){gl_FragColor=vec4(0.);return;}
 float z=sqrt(max(0.,1.-dot(p,p))); vec3 n=vec3(p,z);
 float t=time*.035;
 float shoulder=pow(max(dot(n,normalize(vec3(-.52+sin(t)*.06,.7,.52))),0.),5.);
 float bounce=pow(max(dot(n,normalize(vec3(.68,-.6,.4))),0.),4.);
 float angle=atan(p.y,p.x);
 float fresnel=pow(1.-z,3.8);
 float reflection=.22+.78*pow(abs(sin(angle+.7)),4.);
 float edge=exp(-pow(abs((r-.984)/.009),2.));
 vec3 col=mix(ink,slate,.12+shoulder*.5)+iris*bounce*.1;
 col+=frost*shoulder*(.07+.025*energy)+pearl*pow(shoulder,3.)*.06;
 col+=mix(slate,pearl,reflection)*(fresnel*.2+edge*.3)*reflection;
 col=mix(col,pearl,edge*reflection*(.12+.025*level));
 float alpha=1.-smoothstep(.986,1.,r); gl_FragColor=vec4(col,alpha);
}`;

export function VoiceOrb({ phase, inputLevel, compact = false, task }: { phase: VoicePhase; inputLevel: number; compact?: boolean; task?: VoiceState['task'] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const values = useRef({ phase, inputLevel }); values.current = { phase, inputLevel };
  const reduced = useReducedMotion();
  const [fallback, setFallback] = useState(true);
  // CSS state cues must also pause when the static/WebGL-unavailable path is hidden.
  useEffect(() => {
    const element = canvas.current?.parentElement;
    if (!element) return;
    let visible = true;
    const update = () => element.setAttribute('data-visible', String(visible && !document.hidden));
    const observer = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; update(); });
    observer.observe(element); document.addEventListener('visibilitychange', update); update();
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', update); };
  }, []);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const gl = element.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: false });
    if (!gl) return;
    let frame = 0, last = -Infinity, visible = true, lost = false;
    const shaders: WebGLShader[] = [];
    const program = gl.createProgram(); const buffer = gl.createBuffer();
    if (!program || !buffer) return;
    const shader = (kind: number, source: string) => {
      const item = gl.createShader(kind)!; shaders.push(item); gl.shaderSource(item, source); gl.compileShader(item);
      if (!gl.getShaderParameter(item, gl.COMPILE_STATUS)) throw new Error('Voice orb shader unavailable');
      gl.attachShader(program, item);
    };
    try {
      shader(gl.VERTEX_SHADER, VERTEX); shader(gl.FRAGMENT_SHADER, FRAGMENT); gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Voice orb unavailable');
    } catch { for (const item of shaders) gl.deleteShader(item); gl.deleteProgram(program); gl.deleteBuffer(buffer); return; }
    gl.useProgram(program); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'a'); gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const time = gl.getUniformLocation(program, 'time'), energy = gl.getUniformLocation(program, 'energy'), level = gl.getUniformLocation(program, 'level');
    for (const [name, rgb] of Object.entries(ORB_MATERIAL)) gl.uniform3fv(gl.getUniformLocation(program, name), rgb);
    const draw = (stamp: number) => {
      if (lost || document.hidden || !visible) { frame = 0; return; }
      if (stamp - last >= FRAME_MS) {
        const size = Math.min(MAX_RENDER_PIXELS, Math.ceil(element.clientWidth * Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)));
        if (element.width !== size) element.width = element.height = size;
        gl.viewport(0, 0, size, size); gl.uniform1f(time, reduced ? 0 : stamp / 1000);
        gl.uniform1f(energy, PHASE_ENERGY[values.current.phase] || .08); gl.uniform1f(level, values.current.inputLevel);
        gl.drawArrays(gl.TRIANGLES, 0, 3); last = stamp;
      }
      frame = reduced ? 0 : requestAnimationFrame(draw);
    };
    const start = () => { if (!frame && !lost) { last = -Infinity; frame = requestAnimationFrame(draw); } };
    const visibility = () => {
      cancelAnimationFrame(frame); frame = 0; if (!document.hidden && visible) start();
    };
    const contextLost = (event: Event) => { event.preventDefault(); lost = true; cancelAnimationFrame(frame); setFallback(true); };
    const observer = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; visibility(); });
    observer.observe(element); document.addEventListener('visibilitychange', visibility); element.addEventListener('webglcontextlost', contextLost);
    setFallback(false); start();
    return () => { lost = true; cancelAnimationFrame(frame); observer.disconnect(); document.removeEventListener('visibilitychange', visibility);
      element.removeEventListener('webglcontextlost', contextLost); for (const item of shaders) gl.deleteShader(item); gl.deleteProgram(program); gl.deleteBuffer(buffer); };
  }, [reduced]);
  return <div className={`voice-orb ${compact ? 'is-compact' : ''} ${fallback ? 'is-fallback' : ''}`} data-phase={phase} aria-hidden="true"
    style={{ ...MATERIAL_STYLE, '--voice-level': inputLevel, '--voice-energy': PHASE_ENERGY[phase] || 0 } as CSSProperties}>
    <div className="voice-orb-aura" /><div className="voice-orb-glass" /><canvas ref={canvas} />
    <div className="voice-orb-process" />
    {task?.status === 'done' && <div key={task.id} className="voice-orb-complete" />}
    <div className="voice-orb-ground" />
  </div>;
}
