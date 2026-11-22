# Functional Requirements

- **REQ-001:** Greet the user deterministically on `<event>session start</event>` through `before_model_callback`.
- **REQ-002:** Escalate to a human representative via `set_session_state` when the user requests human assistance.
- **REQ-003:** End the session cleanly on the third consecutive silence signal without hallucinated LLM prose.
