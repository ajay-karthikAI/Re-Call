import { ArrowUp, Command, Sparkles } from "lucide-react";
import { useState } from "react";

export function OverlayAskBar({ disabled = false, onSubmitPrompt }) {
  const [value, setValue] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    const prompt = value.trim();
    if (!prompt || disabled) {
      return;
    }
    onSubmitPrompt?.(prompt);
    setValue("");
  }

  return (
    <form className="overlay-ask-bar" onSubmit={handleSubmit}>
      <div className="overlay-ask-input-wrap">
        <Sparkles size={16} />
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Ask about this meeting..."
          disabled={disabled}
          aria-label="Ask Re: Call about this meeting"
        />
        <kbd>
          <Command size={11} />
          K
        </kbd>
      </div>
      <button type="submit" disabled={disabled || !value.trim()} title="Ask Re: Call">
        <ArrowUp size={15} />
      </button>
    </form>
  );
}
