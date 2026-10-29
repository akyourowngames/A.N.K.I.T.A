import { spawnSync, spawn } from "node:child_process";

/**
 * Windows default-audio-device control via the Core Audio API, spoken over
 * an embedded C# helper. Zero npm dependencies and no PowerShell modules.
 *
 * Why this exists: a Bluetooth headset that is capturing through its
 * Hands-Free (HFP) mic drops out of A2DP, so audio sent to its Stereo
 * endpoint goes silent. Voice mode keeps the mic open for barge-in, so it
 * routes playback to the matching Hands-Free render endpoint instead.
 */

const CSHARP = `
using System;
using System.Runtime.InteropServices;
using System.Collections.Generic;

public static class AudioSwitch {
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class MMDeviceEnumeratorComObject { }

    private enum EDataFlow { eRender = 0, eCapture = 1, eAll = 2 }
    private enum ERole { eConsole = 0, eMultimedia = 1, eCommunications = 2 }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator {
        int EnumAudioEndpoints(EDataFlow dataFlow, int dwStateMask, out IMMDeviceCollection ppDevices);
        int GetDefaultAudioEndpoint(EDataFlow dataFlow, ERole role, out IMMDevice ppDevice);
        int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
        int RegisterEndpointNotificationCallback(IAudioNotification client);
        int UnregisterEndpointNotificationCallback(IAudioNotification client);
    }

    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceCollection {
        int GetCount(out int pcDevices);
        int Item(int nDevice, out IMMDevice ppDevice);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice {
        int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
        int OpenPropertyStore(int stgmAccess, out IPropertyStore ppProperties);
        int GetId([MarshalAs(UnmanagedType.LPWStr)] out string ppstrId);
        int GetState(out int pdwState);
    }

    [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore {
        int GetCount(out int cProps);
        int GetAt(int iProp, out PROPERTYKEY pkey);
        int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
        int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
        int Commit();
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROPERTYKEY { public Guid fmtid; public int pid; }

    [ComVisible(true), Guid("7991EEC9-7E89-4D85-8390-6C703CEC60C0"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IAudioNotification {
        [PreserveSig] int OnDeviceStateChanged([MarshalAs(UnmanagedType.LPWStr)] string id, uint state);
        [PreserveSig] int OnDeviceAdded([MarshalAs(UnmanagedType.LPWStr)] string id);
        [PreserveSig] int OnDeviceRemoved([MarshalAs(UnmanagedType.LPWStr)] string id);
        [PreserveSig] int OnDefaultDeviceChanged(int flow, int role, [MarshalAs(UnmanagedType.LPWStr)] string id);
        [PreserveSig] int OnPropertyValueChanged([MarshalAs(UnmanagedType.LPWStr)] string id, PROPERTYKEY key);
    }
    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public class AudioNotification : IAudioNotification {
        private int Changed() { Console.WriteLine("changed"); Console.Out.Flush(); return 0; }
        public int OnDeviceStateChanged(string id, uint state) { return Changed(); }
        public int OnDeviceAdded(string id) { return Changed(); }
        public int OnDeviceRemoved(string id) { return Changed(); }
        public int OnDefaultDeviceChanged(int flow, int role, string id) { return Changed(); }
        public int OnPropertyValueChanged(string id, PROPERTYKEY key) { return 0; }
    }
    public static void WatchOutput() {
        var e = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
        var callback = new AudioNotification();
        e.RegisterEndpointNotificationCallback(callback);
        try {
            IMMDevice device; e.GetDefaultAudioEndpoint(EDataFlow.eRender, ERole.eConsole, out device);
            Console.WriteLine("ready|" + FormFactor(device)); Console.Out.Flush();
            Console.ReadLine(); // stdin stays open; no polling or repeated helper compilation.
        } finally { e.UnregisterEndpointNotificationCallback(callback); }
    }

    // The largest PROPVARIANT union member determines native size: 24 bytes on x64, 16 on x86.
    [StructLayout(LayoutKind.Sequential)]
    private struct BLOB { public uint size; public IntPtr data; }

    [StructLayout(LayoutKind.Explicit)]
    private struct PROPVARIANT {
        [FieldOffset(0)] public short vt;
        [FieldOffset(8)] public IntPtr pointerValue;
        [FieldOffset(8)] public uint uintValue;
        [FieldOffset(8)] public BLOB blob;
    }

    [ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPolicyConfig {
        int GetMixFormat([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, IntPtr ppFormat);
        int GetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, bool bDefault, IntPtr ppFormat);
        int ResetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName);
        int SetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, IntPtr pEndpointFormat, IntPtr mixFormat);
        int GetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, bool bDefault, IntPtr pmftDefaultPeriod, IntPtr pmftMinimumPeriod);
        int SetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, IntPtr pmftPeriod);
        int GetShareMode([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, IntPtr pMode);
        int SetShareMode([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, IntPtr mode);
        int GetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, bool bFxStore, IntPtr key, IntPtr pv);
        int SetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, bool bFxStore, IntPtr key, IntPtr pv);
        int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, ERole role);
        int SetEndpointVisibility([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, bool bVisible);
    }

    [ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
    private class CPolicyConfigClient { }

    private static string FriendlyName(IMMDevice dev) {
        IPropertyStore store;
        dev.OpenPropertyStore(0, out store);
        var pk = new PROPERTYKEY();
        pk.fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0");
        pk.pid = 14;
        PROPVARIANT pv;
        store.GetValue(ref pk, out pv);
        return pv.pointerValue == IntPtr.Zero ? "" : Marshal.PtrToStringUni(pv.pointerValue);
    }

    public static string GetDefaultRender() { return GetDefaultRender((int)ERole.eConsole); }

    private const short VariantUnsignedInt = 19; // Native VT_UI4 discriminator.
    private const uint UnknownFormFactor = 10; // EndpointFormFactor fallback from the Windows ABI.
    private static uint FormFactor(IMMDevice dev) {
        try {
            IPropertyStore store; dev.OpenPropertyStore(0, out store);
            var key = new PROPERTYKEY(); key.fmtid = new Guid("1da5d803-d492-4edd-8c23-e0c0ffee7f0e"); key.pid = 0;
            PROPVARIANT value; store.GetValue(ref key, out value);
            return value.vt == VariantUnsignedInt ? value.uintValue : UnknownFormFactor;
        } catch { return UnknownFormFactor; }
    }

    public static string GetDefaultRender(int role) {
        var e = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
        IMMDevice dev;
        e.GetDefaultAudioEndpoint(EDataFlow.eRender, (ERole)role, out dev);
        string id;
        dev.GetId(out id);
        return id;
    }

    public static string[] List() {
        var result = new List<string>();
        var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
        foreach (EDataFlow flow in new EDataFlow[] { EDataFlow.eRender, EDataFlow.eCapture }) {
            IMMDeviceCollection coll;
            enumerator.EnumAudioEndpoints(flow, 1, out coll);
            int count;
            coll.GetCount(out count);
            for (int i = 0; i < count; i++) {
                IMMDevice dev;
                coll.Item(i, out dev);
                string id;
                dev.GetId(out id);
                result.Add(flow + "|" + id + "|" + FormFactor(dev) + "|" + FriendlyName(dev));
            }
        }
        return result.ToArray();
    }

    public static void SetDefault(string id) {
        var pc = (IPolicyConfig)new CPolicyConfigClient();
        pc.SetDefaultEndpoint(id, ERole.eConsole);
        pc.SetDefaultEndpoint(id, ERole.eMultimedia);
        pc.SetDefaultEndpoint(id, ERole.eCommunications);
    }

    public static void SetDefault(string id, int role) {
        var pc = (IPolicyConfig)new CPolicyConfigClient();
        pc.SetDefaultEndpoint(id, (ERole)role);
    }
}
`;

const DEVICE_ID_RE = /^\{0\.0\.[01]\.00000000\}\.\{[0-9a-f-]{36}\}$/i;
const RENDER_ROLES = Object.freeze({ console: 0, multimedia: 1, communications: 2 }); // Core Audio ERole values; preserve each Windows default separately.
const AUDIO_HELPER_TIMEOUT_MS = 20000; // Milliseconds: native helper startup/operations remain bounded.
const helperScript = body => `$ErrorActionPreference='Stop'; Add-Type -TypeDefinition @'\n${CSHARP}\n'@; ${body}`;

function runPowerShell(body, timeoutMs = AUDIO_HELPER_TIMEOUT_MS) {
  const script = helperScript(body);
  const res = spawnSync(
    "powershell",
    ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
    { windowsHide: true, encoding: "utf8", timeout: timeoutMs, maxBuffer: 8 * 1024 * 1024 }
  );
  return { code: res.status ?? -1, stdout: (res.stdout || "").trim(), stderr: (res.stderr || "").trim() };
}

export function audioDeviceSupported() {
  return process.platform === "win32";
}

/** All active render/capture endpoints: [{ flow: 'render'|'capture', id, name }]. */
export function listAudioDevices() {
  if (!audioDeviceSupported()) return [];
  const { code, stdout, stderr } = runPowerShell("[AudioSwitch]::List() | ForEach-Object { $_ }");
  if (code !== 0) throw new Error(stderr || "audio device list failed");
  return stdout
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      const [flow, id, formFactor, ...rest] = line.split("|");
      return { flow: flow === "eRender" ? "render" : "capture", id, formFactor: Number(formFactor), name: rest.join("|") };
    });
}

/** ID of the current default playback (render) endpoint. */
export function getDefaultRenderId() {
  if (!audioDeviceSupported()) return "";
  const { code, stdout, stderr } = runPowerShell("[AudioSwitch]::GetDefaultRender()");
  if (code !== 0) throw new Error(stderr || "audio default lookup failed");
  return stdout.trim();
}

/** Snapshot all Windows output defaults in one helper process. */
export function getDefaultRenderIds() {
  if (!audioDeviceSupported()) return {};
  const body = Object.entries(RENDER_ROLES).map(([name, role]) => `Write-Output ('${name}|' + [AudioSwitch]::GetDefaultRender(${role}))`).join('; ');
  const { code, stdout, stderr } = runPowerShell(body);
  if (code !== 0) throw new Error(stderr || 'audio defaults lookup failed');
  return Object.fromEntries(stdout.split(/\r?\n/).filter(Boolean).map(line => line.split('|')));
}

/** Apply only supplied, validated roles; no device names enter executable helper text. */
export function setDefaultRenderIds(defaults) {
  const entries = Object.entries(defaults);
  if (!audioDeviceSupported() || entries.some(([role, id]) => !Object.hasOwn(RENDER_ROLES, role) || !DEVICE_ID_RE.test(String(id)))) return false;
  if (!entries.length) return true;
  const { code, stderr } = runPowerShell(entries.map(([role, id]) => `[AudioSwitch]::SetDefault('${id}', ${RENDER_ROLES[role]})`).join('; '));
  if (code !== 0) throw new Error(stderr || 'audio defaults set failed');
  return true;
}

/** Set the default playback (and communication) endpoint. Returns true on success. */
export function setDefaultAudioDevice(id) {
  if (!audioDeviceSupported() || !DEVICE_ID_RE.test(String(id))) return false;
  const { code, stderr } = runPowerShell(`[AudioSwitch]::SetDefault('${id}')`);
  if (code !== 0) throw new Error(stderr || "audio device set failed");
  return true;
}

const norm = (s) => String(s || "").toLowerCase().replace(/\s+/g, " ").trim();
const PRIVATE_OUTPUT_FORMS = new Set([3, 5, 6]); // Core Audio EndpointFormFactor: headphones, headset and handset. Unknown outputs use safe turn-taking.
export const isPrivateAudioOutput = device => device?.flow === 'render' && PRIVATE_OUTPUT_FORMS.has(device.formFactor);

/** Native endpoint notifications, compiled once per voice session. Failure always disables full-duplex. */
export function watchAudioOutput(onChange) {
  if (!audioDeviceSupported()) return { ready: Promise.resolve(false), stop: async () => {} };
  const child = spawn('powershell', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', helperScript('[AudioSwitch]::WatchOutput()')],
    { windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'] });
  let complete, stopped = false, buffer = '', initialized = false;
  const ready = new Promise(resolve => { complete = value => { initialized = true; clearTimeout(timer); resolve(value); }; });
  const timer = setTimeout(() => { complete(false); child.kill(); }, AUDIO_HELPER_TIMEOUT_MS);
  const closed = new Promise(resolve => child.once('close', () => { if (!initialized) complete(false); if (!stopped) onChange(); resolve(); }));
  child.on('error', () => { if (!initialized) complete(false); if (!stopped) onChange(); });
  child.stdout.on('data', chunk => {
    buffer += chunk.toString();
    const lines = buffer.split(/\r?\n/); buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('ready|')) complete(PRIVATE_OUTPUT_FORMS.has(Number(line.split('|')[1])));
      else if (line === 'changed') onChange();
    }
  });
  return { ready, async stop() { if (!stopped) { stopped = true; child.kill(); } await closed; } };
}

/** The render endpoint that shares a name with this mic (Bluetooth HFP pair). */
export function findHandsFreePlayback(micName, devices) {
  const target = norm(micName);
  if (!target) return null;
  return devices.find((d) => d.flow === "render" && norm(d.name) === target) || null;
}

/**
 * If the given mic has a same-named render endpoint (a Bluetooth headset in
 * HFP), make that endpoint the default playback so speech stays audible while
 * the mic is open. Returns { device, restore } or null when nothing to do.
 */
export function useHandsFreePlayback(micName) {
  if (!audioDeviceSupported() || !micName) return null;
  try {
    const devices = listAudioDevices();
    const match = findHandsFreePlayback(micName, devices);
    return match ? usePlaybackDevice(match.id, { list: () => devices, current: getDefaultRenderIds, set: setDefaultRenderIds }) : null;
  } catch {
    return null;
  }
}

const OUTPUT_UNAVAILABLE = 'That speaker is unavailable. Refresh devices and choose another output.';

/** Temporarily select an OS-discovered output; do not undo a later manual device change. */
export function usePlaybackDevice(id, io = { list: listAudioDevices, current: getDefaultRenderIds, set: setDefaultRenderIds }) {
  const device = io.list().find(item => item.flow === 'render' && item.id === id);
  if (!device) throw new Error(OUTPUT_UNAVAILABLE);
  const previous = io.current();
  const changed = Object.fromEntries(Object.entries(previous).filter(([, old]) => old.toLowerCase() !== device.id.toLowerCase()).map(([role]) => [role, device.id]));
  let restored = false;
  const receipt = { previous, changed, deviceId: device.id };
  const route = { device, receipt, restore() {
    if (restored) return;
    restored = true;
    try {
      return restorePlaybackDevice(receipt, io);
    } catch { return false; /* Unplugging the old speaker must not break session teardown. */ }
  } };
  try {
    if (Object.keys(changed).length && !io.set(changed)) throw new Error(OUTPUT_UNAVAILABLE);
  } catch (error) { route.restore(); throw error; }
  return route;
}

/** Serializable restoration proof survives a worker restart; retain later manual role changes. */
export function restorePlaybackDevice({ previous, changed, deviceId }, io = { current: getDefaultRenderIds, set: setDefaultRenderIds }) {
  const current = io.current();
  const restore = Object.fromEntries(Object.keys(changed).filter(role => current[role]?.toLowerCase() === deviceId.toLowerCase()).map(role => [role, previous[role]]));
  return Object.keys(restore).length ? io.set(restore) : true;
}
