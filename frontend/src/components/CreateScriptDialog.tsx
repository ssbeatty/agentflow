"use client";
import { useState } from "react";
import { toast } from "sonner";
import { scripts } from "@/lib/api";
import type { ScriptSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (script: ScriptSummary) => void;
}

export default function CreateScriptDialog({ open, onOpenChange, onCreated }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [entryFn, setEntryFn] = useState("run");
  const [loading, setLoading] = useState(false);

  async function handleCreate() {
    if (!name.trim()) return toast.error("Name is required");
    setLoading(true);
    try {
      const s = await scripts.create({ name: name.trim(), description, entry_function: entryFn });
      onCreated(s);
      setName("");
      setDescription("");
      setEntryFn("run");
      toast.success("Script created");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New Script</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My LangGraph Agent"
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label>Description <span className="text-muted-foreground">(optional)</span></Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this agent do?"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Entry function</Label>
            <Input
              value={entryFn}
              onChange={(e) => setEntryFn(e.target.value)}
              placeholder="run"
              className="font-mono"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleCreate} disabled={loading}>
            {loading ? "Creating…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
