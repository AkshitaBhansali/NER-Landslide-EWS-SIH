import { useRef, useState } from "react";
import type { MediaAttachment } from "@/types";
import { formatBytes, uid } from "@/utils";
import { IconCamera } from "@/components/ui/Icon";

/**
 * Media capture for field reporting. Files are held as object URLs only; the multipart
 * upload to `POST /api/reports/field` is the backend's job, and the offline queue will
 * persist the blobs in IndexedDB.
 */
export function FileUploader({
  media,
  onChange,
  maxFiles = 6,
}: {
  media: MediaAttachment[];
  onChange: (m: MediaAttachment[]) => void;
  maxFiles?: number;
}) {
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const accepted: MediaAttachment[] = [];
    let rejected = 0;

    Array.from(files).forEach((file) => {
      const isImage = file.type.startsWith("image/");
      const isVideo = file.type.startsWith("video/");
      if (!isImage && !isVideo) {
        rejected += 1;
        return;
      }
      if (media.length + accepted.length >= maxFiles) {
        rejected += 1;
        return;
      }
      accepted.push({
        id: uid("media"),
        name: file.name,
        file,
        kind: isImage ? "IMAGE" : "VIDEO",
        sizeBytes: file.size,
        previewUrl: URL.createObjectURL(file),
      });
    });

    setError(
      rejected > 0
        ? `${rejected} file(s) skipped — images and videos only, up to ${maxFiles} attachments.`
        : null,
    );
    if (accepted.length) onChange([...media, ...accepted]);
  };

  const remove = (id: string) => {
    const target = media.find((m) => m.id === id);
    if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
    onChange(media.filter((m) => m.id !== id));
  };

  return (
    <div>
      <div
        className={`dropzone${over ? " over" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          addFiles(e.dataTransfer.files);
        }}
        aria-label="Add photos or video of the incident"
      >
        <IconCamera size={22} style={{ opacity: 0.7 }} />
        <div style={{ marginTop: 6, fontWeight: 500 }}>Add photos or video</div>
        <div className="tiny">Tap to use the camera, or drag files here · up to {maxFiles} attachments</div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*,video/*"
        multiple
        capture="environment"
        className="sr-only"
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />

      {error && (
        <div className="tiny" style={{ color: "var(--sev)", marginTop: 6 }} role="alert">
          {error}
        </div>
      )}

      {media.length > 0 && (
        <div className="media-grid">
          {media.map((m) => (
            <div className="media-item" key={m.id}>
              {m.kind === "IMAGE" ? (
                <img src={m.previewUrl} alt={m.name} />
              ) : (
                <video src={m.previewUrl} muted playsInline />
              )}
              <button
                type="button"
                className="rm"
                onClick={() => remove(m.id)}
                aria-label={`Remove ${m.name}`}
              >
                ×
              </button>
              <span className="fname">
                {m.name} · {formatBytes(m.sizeBytes)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
