import React, { useId } from 'react';

/** A small "?" that explains a term on hover or keyboard focus. */
export default function InfoTip({ text }) {
  const id = useId();
  return (
    <span className="info-tip">
      <button type="button" className="info-tip-trigger" aria-describedby={id} aria-label="What is this?">
        ?
      </button>
      <span role="tooltip" id={id} className="info-tip-bubble">
        {text}
      </span>
    </span>
  );
}
