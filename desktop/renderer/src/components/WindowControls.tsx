/** macOS-style window controls for the frameless window. */
export function WindowControls() {
  return <div className="traffic" aria-label="Window controls">
    <button type="button" className="traffic-dot close" aria-label="Close window" onClick={() => void window.ankita.windowAction('close')} />
    <button type="button" className="traffic-dot minimize" aria-label="Minimize window" onClick={() => void window.ankita.windowAction('minimize')} />
    <button type="button" className="traffic-dot maximize" aria-label="Maximize window" onClick={() => void window.ankita.windowAction('maximize')} />
  </div>;
}
