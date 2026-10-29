import { spawnSync } from "node:child_process";

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
        int RegisterEndpointNotificationCallback(IntPtr client);
        int UnregisterEndpointNotificationCallback(IntPtr client);
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
    private struct PROPERTYKEY { public Guid fmtid; public int pid; }

    [StructLayout(LayoutKind.Explicit)]
    private struct PROPVARIANT {
        [FieldOffset(0)] public short vt;
        [FieldOffset(8)] public IntPtr pointerValue;
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
                result.Add(flow + "|" + id + "|" + FriendlyName(dev));
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

function runPowerShell(body, timeoutMs = 20000) {
  const script = `$ErrorActionPreference='Stop'; Add-Type -TypeDefinition @'\n${CSHARP}\n'@; ${body}`;
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
      const [flow, id, ...rest] = line.split("|");
      return { flow: flow === "eRender" ? "render" : "capture", id, name: rest.join("|") };
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
  const route = { device, restore() {
    if (restored) return;
    restored = true;
    try {
      const current = io.current();
      const restore = Object.fromEntries(Object.keys(changed).filter(role => current[role]?.toLowerCase() === device.id.toLowerCase()).map(role => [role, previous[role]]));
      if (Object.keys(restore).length) return io.set(restore);
    } catch { return false; /* Unplugging the old speaker must not break session teardown. */ }
  } };
  try {
    if (Object.keys(changed).length && !io.set(changed)) throw new Error(OUTPUT_UNAVAILABLE);
  } catch (error) { route.restore(); throw error; }
  return route;
}
