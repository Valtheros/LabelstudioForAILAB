import { useRef, useState } from "react";
import { Button } from "@humansignal/ui";
import { IconUpload } from "@humansignal/icons";
import { importFiles } from "./utils";

export const ImportPage = ({ project, show = true, onWaiting, addColumns }) => {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [accepted, setAccepted] = useState([]);
  async function upload(selected) {
    if (busy || !selected.length) return;
    const files = Array.from(selected);
    if (files.some(file => !/\.(png|jpe?g|webp|zip)$/i.test(file.name)) || (files.some(file => /\.zip$/i.test(file.name)) && files.length !== 1)) {
      setError("Choose JPEG, PNG, WebP images or one ZIP."); return;
    }
    if (files.reduce((sum, file) => sum + file.size, 0) > 2 * 1024 ** 3) {
      setError("The upload must not exceed 2 GB."); return;
    }
    setBusy(true); onWaiting?.(true); setError("");
    const body = new FormData();
    files.forEach(file => body.append("files", file));
    try {
      await importFiles({ body, project,
        onFinish: () => {
          setAccepted(previous => [...previous, ...files.map(file => file.name)]);
          addColumns?.(["image"]);
        },
        onError: response => setError(response?.detail || JSON.stringify(response?.validation_errors || response || "Upload failed. Please retry.")),
      });
    } catch (e) { setError(e.message || "Upload failed. Please retry."); }
    finally { setBusy(false); onWaiting?.(false); if (input.current) input.current.value = ""; }
  }
  return <div hidden={!show} className="p-6 space-y-5">
    <input ref={input} type="file" hidden multiple accept=".jpg,.jpeg,.png,.webp,.zip" disabled={busy} onChange={event => upload(event.target.files)} aria-label="Image files or ZIP" />
    <div onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); upload(event.dataTransfer.files); }} className="border border-dashed rounded-md p-8 flex flex-col items-center gap-4">
      <IconUpload width={40} height={40} />
      <span>JPEG · PNG · WebP · ZIP · 2 GB</span>
      <Button disabled={busy} onClick={() => input.current?.click()}>{busy ? "Uploading…" : "Upload images"}</Button>
    </div>
    {error && <p role="alert" className="text-red-500 break-words">{error}</p>}
    {accepted.length > 0 && <div role="status"><p>Queued for import</p><ul>{accepted.map((name, i) => <li className="break-all" key={`${i}-${name}`}>{name}</li>)}</ul></div>}
  </div>;
};
