import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { VoicePhase } from '../../../../shared/voice.mjs';
import { useReducedMotion } from '../../lib/useReducedMotion';

const MAX_RENDER_PIXELS = 640; // Pixels per axis: cap GPU work on large and high-DPI displays.
const MAX_PIXEL_RATIO = 1.5; // Render density: soft glass needs no full retina buffer.
const FRAME_MS = 1000 / 30; // Milliseconds: smooth, bounded thirty-frame animation.
const PHASE_ENERGY: Partial<Record<VoicePhase, number>> = { listening: .25, speaking: .8, working: .48, transcribing: .38, approval: .12, paused: .04 };
const VERTEX = `attribute vec2 a; varying vec2 uv; void main(){uv=a;gl_Position=vec4(a,0.,1.);}`;
// Original pearl-glass sphere: flowing layered refraction, rim light and a soft terminator.
const FRAGMENT = `precision mediump float;
varying vec2 uv; uniform float time; uniform float energy; uniform float level;
float noise(vec3 p){return sin(p.x*2.4+sin(p.y*3.1))*cos(p.z*2.1+sin(p.x*1.8));}
void main(){
 vec2 p=uv*1.24; float r=length(p); if(r>1.){gl_FragColor=vec4(0.);return;}
 float z=sqrt(max(0.,1.-dot(p,p))); vec3 n=vec3(p,z);
 float t=time*(.11+energy*.14); float bend=noise(n*1.7+vec3(t,-t*.6,t*.4));
 float flow=sin(n.x*4.2+n.y*3.3+n.z*2.6+bend*2.8-t*2.);
 float vein=pow(max(0.,1.-abs(flow)),4.); float veil=sin(n.y*5.-n.x*2.+bend+t);
 vec3 deep=vec3(.14,.28,.63); vec3 ice=vec3(.65,.88,1.); vec3 pearl=vec3(.76,.69,.96);
 vec3 col=mix(deep,pearl,smoothstep(-1.,1.,veil)*.78);
 col=mix(col,ice,vein*.93); col+=vec3(.29,.31,.44)*pow(max(0.,dot(n,normalize(vec3(-.5,.7,1.)))),6.);
 float fres=pow(1.-z,2.8); col=mix(col,vec3(.68,.79,1.),fres*.85);
 float shine=pow(max(0.,dot(n,normalize(vec3(-.48,.6,.65)))),32.); col+=shine*.44;
 col*=.61+.39*z; col+=level*vein*.13;
 float alpha=smoothstep(1.,.986,r); gl_FragColor=vec4(col,alpha);
}`;

export function VoiceOrb({ phase, inputLevel, compact = false }: { phase: VoicePhase; inputLevel: number; compact?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const values = useRef({ phase, inputLevel }); values.current = { phase, inputLevel };
  const reduced = useReducedMotion();
  const [fallback, setFallback] = useState(true);
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
    const visibility = () => { cancelAnimationFrame(frame); frame = 0; if (!document.hidden) start(); };
    const contextLost = (event: Event) => { event.preventDefault(); lost = true; cancelAnimationFrame(frame); setFallback(true); };
    const observer = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (visible) start(); });
    observer.observe(element); document.addEventListener('visibilitychange', visibility); element.addEventListener('webglcontextlost', contextLost);
    setFallback(false); start();
    return () => { lost = true; cancelAnimationFrame(frame); observer.disconnect(); document.removeEventListener('visibilitychange', visibility);
      element.removeEventListener('webglcontextlost', contextLost); for (const item of shaders) gl.deleteShader(item); gl.deleteProgram(program); gl.deleteBuffer(buffer); };
  }, [reduced]);
  return <div className={`voice-orb ${compact ? 'is-compact' : ''} ${fallback ? 'is-fallback' : ''}`} data-phase={phase} aria-hidden="true"
    style={{ '--voice-level': inputLevel, '--voice-energy': PHASE_ENERGY[phase] || 0 } as CSSProperties}>
    <div className="voice-orb-aura" /><div className="voice-orb-glass" /><canvas ref={canvas} /><div className="voice-orb-ground" />
  </div>;
}
