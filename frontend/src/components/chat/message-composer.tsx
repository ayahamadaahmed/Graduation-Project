import { useRef, useState, type KeyboardEvent } from "react";
import { Paperclip, Mic, Smile, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function MessageComposer({ onSend, disabled }: { onSend: (text: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState("");
  const [recording, setRecording] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const t = value.trim();
    if (!t) return;
    onSend(t);
    setValue("");
    ref.current?.focus();
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card p-2 shadow-card">
      <div className="flex items-end gap-1">
        <div className="flex items-center gap-1 pb-1">
          <Button type="button" variant="ghost" size="icon" className="h-9 w-9 rounded-xl text-muted-foreground hover:text-primary">
            <Paperclip className="h-5 w-5" />
          </Button>
          <Button type="button" variant="ghost" size="icon" className="h-9 w-9 rounded-xl text-muted-foreground hover:text-primary">
            <Smile className="h-5 w-5" />
          </Button>
        </div>
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKey}
          rows={1}
          placeholder="اكتب رسالتك للمساعد الطبي..."
          className="min-h-[40px] max-h-32 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-1 pb-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setRecording((r) => !r)}
            className={cn(
              "h-9 w-9 rounded-xl transition-colors",
              recording ? "bg-destructive text-destructive-foreground animate-pulse" : "text-muted-foreground hover:text-primary",
            )}
          >
            <Mic className="h-5 w-5" />
          </Button>
          <Button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            size="icon"
            className="h-9 w-9 rounded-xl bg-primary text-primary-foreground shadow-soft hover:bg-primary/90 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
