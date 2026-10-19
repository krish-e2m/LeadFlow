import React, { useId } from "react";
import { cn } from "@/lib/utils";

interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: string;
  /** Helper text shown below the field. Replaced by `error` when present. */
  helper?: string;
  error?: string;
  size?: "sm" | "md" | "lg";
}

const heights = { sm: "h-control-sm", md: "h-control", lg: "h-control-lg" } as const;

export const inputBaseClass =
  "w-full rounded-control border border-border-strong bg-surface px-3 text-sm text-fg placeholder:text-fg-tertiary " +
  "transition-[border-color,box-shadow] duration-fast hover:border-fg-tertiary focus-ring " +
  "disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:opacity-60";

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, helper, error, size = "md", id, ...props }, ref) => {
    const autoId = useId();
    const inputId = id ?? autoId;
    const describedBy = error ? `${inputId}-error` : helper ? `${inputId}-helper` : undefined;

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="mb-1.5 block text-caption font-medium text-fg">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(inputBaseClass, heights[size], error && "border-danger hover:border-danger", className)}
          {...props}
        />
        {error ? (
          <p id={`${inputId}-error`} className="mt-1.5 text-xs text-danger">
            {error}
          </p>
        ) : helper ? (
          <p id={`${inputId}-helper`} className="mt-1.5 text-xs text-fg-tertiary">
            {helper}
          </p>
        ) : null}
      </div>
    );
  }
);

Input.displayName = "Input";

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  helper?: string;
  error?: string;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, helper, error, id, rows = 3, ...props }, ref) => {
    const autoId = useId();
    const fieldId = id ?? autoId;
    const describedBy = error ? `${fieldId}-error` : helper ? `${fieldId}-helper` : undefined;

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={fieldId} className="mb-1.5 block text-caption font-medium text-fg">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={fieldId}
          rows={rows}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(inputBaseClass, "resize-y py-2", error && "border-danger hover:border-danger", className)}
          {...props}
        />
        {error ? (
          <p id={`${fieldId}-error`} className="mt-1.5 text-xs text-danger">
            {error}
          </p>
        ) : helper ? (
          <p id={`${fieldId}-helper`} className="mt-1.5 text-xs text-fg-tertiary">
            {helper}
          </p>
        ) : null}
      </div>
    );
  }
);

Textarea.displayName = "Textarea";
